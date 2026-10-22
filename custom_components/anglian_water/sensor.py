"""Anglian Water sensor platform."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import override

from pyanglianwater.meter import SmartMeter

from homeassistant.components.sensor import (
    EntityCategory,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AnglianWaterConfigEntry, AnglianWaterUpdateCoordinator
from .entity import AnglianWaterEntity

PARALLEL_UPDATES = 0


class AnglianWaterSensor(StrEnum):
    """Store keys for Anglian Water sensors."""

    YESTERDAY_CONSUMPTION = "yesterday_consumption"
    YESTERDAY_WATER_COST = "yesterday_water_cost"
    YESTERDAY_SEWERAGE_COST = "yesterday_sewerage_cost"
    LATEST_READING = "latest_reading"
    LAST_UPDATED = "last_updated"
    MONTH_TO_DATE_USAGE = "month_to_date_usage"
    MONTH_TO_DATE_COST = "month_to_date_cost"


@dataclass(frozen=True, kw_only=True)
class AnglianWaterSensorEntityDescription(SensorEntityDescription):
    """Describes AnglianWater sensor entity."""

    value_fn: Callable[[SmartMeter], float | datetime | None]


ENTITY_DESCRIPTIONS: tuple[AnglianWaterSensorEntityDescription, ...] = (
    AnglianWaterSensorEntityDescription(
        key=AnglianWaterSensor.YESTERDAY_CONSUMPTION,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        value_fn=lambda entity: entity.get_yesterday_consumption,
        state_class=SensorStateClass.TOTAL,
        translation_key=AnglianWaterSensor.YESTERDAY_CONSUMPTION,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnglianWaterSensorEntityDescription(
        key=AnglianWaterSensor.LATEST_READING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        value_fn=lambda entity: entity.latest_read,
        state_class=SensorStateClass.TOTAL_INCREASING,
        translation_key=AnglianWaterSensor.LATEST_READING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnglianWaterSensorEntityDescription(
        key=AnglianWaterSensor.YESTERDAY_WATER_COST,
        native_unit_of_measurement="GBP",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda entity: entity.yesterday_water_cost,
        translation_key=AnglianWaterSensor.YESTERDAY_WATER_COST,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnglianWaterSensorEntityDescription(
        key=AnglianWaterSensor.YESTERDAY_SEWERAGE_COST,
        native_unit_of_measurement="GBP",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda entity: entity.yesterday_sewerage_cost,
        translation_key=AnglianWaterSensor.YESTERDAY_SEWERAGE_COST,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnglianWaterSensorEntityDescription(
        key=AnglianWaterSensor.LAST_UPDATED,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda entity: entity.last_updated,
        translation_key=AnglianWaterSensor.LAST_UPDATED,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


@dataclass(frozen=True, kw_only=True)
class AnglianWaterMonthToDateEntityDescription(SensorEntityDescription):
    """Describes a month-to-date sensor computed from statistics."""

    statistic_key: str
    requires_costs: bool = False


MONTH_TO_DATE_DESCRIPTIONS: tuple[AnglianWaterMonthToDateEntityDescription, ...] = (
    AnglianWaterMonthToDateEntityDescription(
        key=AnglianWaterSensor.MONTH_TO_DATE_USAGE,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        suggested_display_precision=3,
        statistic_key="usage",
        translation_key=AnglianWaterSensor.MONTH_TO_DATE_USAGE,
    ),
    AnglianWaterMonthToDateEntityDescription(
        key=AnglianWaterSensor.MONTH_TO_DATE_COST,
        native_unit_of_measurement="GBP",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        statistic_key="cost",
        requires_costs=True,
        translation_key=AnglianWaterSensor.MONTH_TO_DATE_COST,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnglianWaterConfigEntry,
    async_add_devices: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_devices(
        AnglianWaterSensorEntity(
            coordinator=entry.runtime_data,
            description=entity_description,
            smart_meter=smart_meter,
        )
        for entity_description in ENTITY_DESCRIPTIONS
        for smart_meter in entry.runtime_data.api.meters.values()
    )
    async_add_devices(
        AnglianWaterMonthToDateSensorEntity(
            coordinator=entry.runtime_data,
            description=entity_description,
            smart_meter=smart_meter,
        )
        for entity_description in MONTH_TO_DATE_DESCRIPTIONS
        for smart_meter in entry.runtime_data.api.meters.values()
        if entry.runtime_data.costs_configured or not entity_description.requires_costs
    )


class AnglianWaterSensorEntity(AnglianWaterEntity, SensorEntity):
    """Defines a Anglian Water sensor."""

    entity_description: AnglianWaterSensorEntityDescription

    def __init__(
        self,
        coordinator: AnglianWaterUpdateCoordinator,
        smart_meter: SmartMeter,
        description: AnglianWaterSensorEntityDescription,
    ) -> None:
        """Initialize Anglian Water sensor."""
        super().__init__(coordinator, smart_meter, description.key)
        self.entity_description = description

    @property
    @override
    def native_value(self) -> float | datetime | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.smart_meter)


class AnglianWaterMonthToDateSensorEntity(AnglianWaterEntity, SensorEntity):
    """Defines a month-to-date sensor computed from statistics."""

    entity_description: AnglianWaterMonthToDateEntityDescription

    def __init__(
        self,
        coordinator: AnglianWaterUpdateCoordinator,
        smart_meter: SmartMeter,
        description: AnglianWaterMonthToDateEntityDescription,
    ) -> None:
        """Initialize month-to-date sensor."""
        super().__init__(coordinator, smart_meter, description.key)
        self.entity_description = description

    @property
    @override
    def native_value(self) -> float | None:
        """Return this month's total so far."""
        totals = self.coordinator.month_to_date.get(self.smart_meter.serial_number)
        if totals is None:
            return None
        return round(totals[self.entity_description.statistic_key], 4)
