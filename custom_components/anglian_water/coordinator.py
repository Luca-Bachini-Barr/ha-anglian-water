"""Anglian Water data coordinator."""

from datetime import timedelta
import logging
from typing import Any, override

from pyanglianwater import AnglianWater
from pyanglianwater.exceptions import (
    ConsentRequiredError,
    ExpiredAccessTokenError,
    InvalidGrantError,
    UnknownEndpointError,
)

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_STANDING_CHARGE,
    CONF_VOLUME_RATE,
    DOMAIN,
)
from .helpers import (
    async_create_consent_required_issue,
    async_delete_consent_required_issue,
)

type AnglianWaterConfigEntry = ConfigEntry[AnglianWaterUpdateCoordinator]

_LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = timedelta(minutes=60)


class AnglianWaterUpdateCoordinator(DataUpdateCoordinator[None]):
    """Anglian Water data update coordinator."""

    config_entry: AnglianWaterConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        api: AnglianWater,
        config_entry: AnglianWaterConfigEntry,
    ) -> None:
        """Initialize update coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=config_entry,
        )
        self.api = api
        self.month_to_date: dict[str, dict[str, float]] = {}

    @override
    async def _async_update_data(self) -> None:
        """Update data from Anglian Water's API."""
        try:
            await self.api.update(self.config_entry.data[CONF_ACCOUNT_NUMBER])
            await self._insert_statistics()
        except ConsentRequiredError as err:
            async_create_consent_required_issue(
                self.hass, self.config_entry.data[CONF_ACCOUNT_NUMBER]
            )
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="consent_required",
                retry_after=900.0,
            ) from err
        except (ExpiredAccessTokenError, InvalidGrantError) as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_expired",
            ) from err
        except UnknownEndpointError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="service_unavailable",
                retry_after=60.0,
            ) from err
        else:
            async_delete_consent_required_issue(
                self.hass, self.config_entry.data[CONF_ACCOUNT_NUMBER]
            )

    def _statistic_id_prefix(self, meter_serial: str) -> str:
        """Return the statistic id prefix for a meter."""
        return (
            f"{DOMAIN}:{self.config_entry.data[CONF_ACCOUNT_NUMBER]}_{meter_serial}"
        ).lower()

    @property
    def costs_configured(self) -> bool:
        """Return True when tariff rates are set in the options."""
        return bool(self.config_entry.options.get(CONF_VOLUME_RATE))

    async def _insert_statistics(self) -> None:
        """Insert usage, then cost statistics, then refresh month-to-date."""
        await self._insert_usage_statistics()
        # The recorder doesn't commit queued statistics until startup has
        # finished, so only wait for it once HA is running. During startup the
        # cost and month-to-date figures catch up on the next refresh.
        recorder = get_instance(self.hass)
        if self.hass.is_running:
            await recorder.async_block_till_done()
        if self.costs_configured:
            for meter in self.api.meters.values():
                await self._insert_cost_statistics(meter.serial_number)
            if self.hass.is_running:
                await recorder.async_block_till_done()
        await self._update_month_to_date()

    async def _insert_cost_statistics(self, meter_serial: str) -> None:
        """Derive hourly cost statistics from the hourly usage statistics.

        Each record costs the change in the meter total times the volume rate,
        plus the standing charge for the time since the previous record, so
        gaps in the hourly data (e.g. while the login had expired) are still
        charged in full. Hours keep the rates configured when first written.
        """
        prefix = self._statistic_id_prefix(meter_serial)
        usage_statistic_id = f"{prefix}_usage"
        cost_statistic_id = f"{prefix}_cost"
        volume_rate = float(self.config_entry.options.get(CONF_VOLUME_RATE, 0))
        standing_charge = float(self.config_entry.options.get(CONF_STANDING_CHARGE, 0))
        recorder = get_instance(self.hass)

        last_cost = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, cost_statistic_id, True, {"sum"}
        )
        if last_cost:
            last_record = last_cost[cost_statistic_id][0]
            cost_sum = float(last_record.get("sum") or 0.0)
            # Start at the last costed hour so its usage total is the baseline.
            start = dt_util.utc_from_timestamp(last_record["start"])
        else:
            cost_sum = 0.0
            start = dt_util.utc_from_timestamp(0)

        usage = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            None,
            {usage_statistic_id},
            "hour",
            None,
            {"state", "sum"},
        )
        records = usage.get(usage_statistic_id, [])
        previous: dict[str, Any] | None = None
        if last_cost and records and records[0]["start"] == start.timestamp():
            previous = records.pop(0)
        cost_statistics = []
        for record in records:
            if previous is None:
                volume = float(record.get("state") or 0.0)
                hours = 1.0
            else:
                volume = max(
                    0.0,
                    float(record.get("sum") or 0.0) - float(previous.get("sum") or 0.0),
                )
                hours = (record["start"] - previous["start"]) / 3600
            previous = record
            hour_cost = (volume * volume_rate + standing_charge * hours / 24) / 100
            cost_sum += hour_cost
            cost_statistics.append(
                StatisticData(
                    start=dt_util.utc_from_timestamp(record["start"]),
                    state=round(hour_cost, 6),
                    sum=round(cost_sum, 6),
                )
            )
        if not cost_statistics:
            return
        _LOGGER.debug(
            "Adding %s cost statistics for %s", len(cost_statistics), cost_statistic_id
        )
        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=(
                    f"Anglian Water {self.config_entry.data[CONF_ACCOUNT_NUMBER]} "
                    f"{meter_serial} Cost"
                ),
                source=DOMAIN,
                statistic_id=cost_statistic_id,
                unit_class=None,
                unit_of_measurement="GBP",
            ),
            cost_statistics,
        )

    async def _update_month_to_date(self) -> None:
        """Total this month's usage and cost from the statistics."""
        month_start = dt_util.start_of_local_day(dt_util.now().replace(day=1))
        for meter in self.api.meters.values():
            prefix = self._statistic_id_prefix(meter.serial_number)
            ids = {f"{prefix}_usage", f"{prefix}_cost"}
            stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                month_start,
                None,
                ids,
                "month",
                None,
                {"change"},
            )
            self.month_to_date[meter.serial_number] = {
                key: sum(float(r.get("change") or 0.0) for r in stats.get(f"{prefix}_{key}", []))
                for key in ("usage", "cost")
            }

    async def _insert_usage_statistics(self) -> None:
        """Insert statistics for water meters into Home Assistant."""
        for meter in self.api.meters.values():
            id_prefix = (
                f"{self.config_entry.data[CONF_ACCOUNT_NUMBER]}_{meter.serial_number}"
            )
            usage_statistic_id = f"{DOMAIN}:{id_prefix}_usage".lower()
            _LOGGER.debug("Updating statistics for meter %s", meter.serial_number)
            name_prefix = (
                f"Anglian Water {self.config_entry.data[CONF_ACCOUNT_NUMBER]} "
                f"{meter.serial_number}"
            )
            usage_metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name_prefix} Usage",
                source=DOMAIN,
                statistic_id=usage_statistic_id,
                unit_class=VolumeConverter.UNIT_CLASS,
                unit_of_measurement=UnitOfVolume.CUBIC_METERS,
            )
            last_stat = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, usage_statistic_id, True, set()
            )
            if not last_stat:
                _LOGGER.debug("Updating statistics for the first time")
                usage_sum = 0.0
                last_stats_time = None
                allow_update_last_stored_hour = False
            else:
                if not meter.readings or len(meter.readings) == 0:
                    _LOGGER.debug("No recent usage statistics found, skipping update")
                    continue
                # Anglian Water stats are hourly, the read_at time
                # is the time that the meter took the reading.
                # We remove 1 hour from this so that the data is
                # shown in the correct hour on the dashboards
                parsed_read_at = dt_util.parse_datetime(meter.readings[0]["read_at"])
                if not parsed_read_at:
                    _LOGGER.debug(
                        "Could not parse read_at time %s, skipping update",
                        meter.readings[0]["read_at"],
                    )
                    continue
                start = dt_util.as_local(parsed_read_at) - timedelta(hours=1)
                _LOGGER.debug("Getting statistics at %s", start)
                stats: dict[str, list[Any]] = {}
                for end in (start + timedelta(seconds=1), None):
                    stats = await get_instance(self.hass).async_add_executor_job(
                        statistics_during_period,
                        self.hass,
                        start,
                        end,
                        {
                            usage_statistic_id,
                        },
                        "hour",
                        None,
                        {"sum"},
                    )
                    if stats:
                        break
                    if end:
                        _LOGGER.debug(
                            "Not found, trying to find oldest statistic after %s",
                            start,
                        )

                if not stats or not stats.get(usage_statistic_id):
                    _LOGGER.debug(
                        "Could not find existing statistics during"
                        " period lookup for %s, falling back to"
                        " last stored statistic",
                        usage_statistic_id,
                    )
                    allow_update_last_stored_hour = True
                    last_records = last_stat[usage_statistic_id]
                    usage_sum = float(last_records[0].get("sum") or 0.0)
                    last_stats_time = last_records[0]["start"]
                else:
                    allow_update_last_stored_hour = False
                    records = stats[usage_statistic_id]

                    def _safe_get_sum(records: list[Any]) -> float:
                        if records and "sum" in records[0]:
                            return float(records[0]["sum"])
                        return 0.0

                    usage_sum = _safe_get_sum(records)
                    last_stats_time = records[0]["start"]

            usage_statistics = []

            for read in meter.readings:
                parsed_read_at = dt_util.parse_datetime(read["read_at"])
                if not parsed_read_at:
                    _LOGGER.debug(
                        "Could not parse read_at time %s, skipping reading",
                        read["read_at"],
                    )
                    continue
                start = dt_util.as_local(parsed_read_at) - timedelta(hours=1)
                if last_stats_time is not None and (
                    start.timestamp() < last_stats_time
                    or (
                        start.timestamp() == last_stats_time
                        and not allow_update_last_stored_hour
                    )
                ):
                    continue
                usage_state = max(0, read["consumption"] / 1000)
                usage_sum = max(0, read["read"])
                usage_statistics.append(
                    StatisticData(
                        start=start,
                        state=usage_state,
                        sum=usage_sum,
                    )
                )
            _LOGGER.debug(
                "Adding %s statistics for %s", len(usage_statistics), usage_statistic_id
            )
            async_add_external_statistics(self.hass, usage_metadata, usage_statistics)
