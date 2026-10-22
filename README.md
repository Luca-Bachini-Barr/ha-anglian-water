# Anglian Water (fork) for Home Assistant

A fork of Home Assistant's built-in [Anglian Water](https://www.home-assistant.io/integrations/anglian_water) integration, packaged as a custom component so it can be changed independently of HA releases.

**Based on:** `home-assistant/core` tag `2026.10.2`, `homeassistant/components/anglian_water` (uses `pyanglianwater==3.3.2`). Original code owner: @pantherale0. Licensed under Apache 2.0 like HA core; see [LICENSE](LICENSE).

> Installing this **overrides** the built-in integration (same `anglian_water` domain). Existing config entries carry over, so there's no need to re-add the account. Remove the folder and restart to go back to the core version.

## Added features
### Tariff rates (options)
**Settings → Devices & services → Anglian Water → Configure**:
- **Volume rate** (p/m³): water + sewerage charge per m³ used. On a bill showing a water rate and a sewerage rate with a 90% return-to-sewer allowance, that is `water + 0.9 × sewerage`.
- **Standing charge** (p/day): water + sewerage standing charges combined.

Cost features stay off until a volume rate is set.

### Daily cost history
The integration writes an hourly **cost statistic** `anglian_water:<account>_<meter>_cost` in GBP, derived from the existing usage statistic:
- Each record costs the change in the meter total × the volume rate, plus the standing charge for the time since the previous record. Gaps in the hourly data (for example while the login had expired) are still charged in full.
- On first setup it is backfilled over the whole usage history using the current rates. After that, new hours use whatever rates are configured at the time; past hours are never recalculated. When rates change each April, update the options. To re-cost all history at the new rates, clear the statistic in **Developer tools → Statistics**; it rebuilds on the next refresh.

Use it in a **Statistics graph** card (period `day`, stat type `change`), or as the water cost in the Energy dashboard.

### Month-to-date sensors
- **Month to date usage** (m³) and **Month to date cost** (GBP), totalled from the statistics since the 1st of the month (local time). Both update hourly. The cost sensor only appears once a volume rate is set.

## Changes from core
- Everything above (`coordinator.py`, `sensor.py`, `config_flow.py`, `__init__.py`, `const.py`, strings).
- `manifest.json`: added `version` (`2026.10.2.x` = based on core 2026.10.2), repo docs/issue links, dropped `quality_scale`.
- `strings.json` / `translations/en.json`: shared `[%key:common::…%]` references inlined, since custom components can't resolve them.
- `quality_scale.yaml` removed (core-only).

## Installation
**HACS:** add `https://github.com/Luca-Bachini-Barr/ha-anglian-water` as a custom repository (type Integration), install it, then restart.

**Manual:** copy `custom_components/anglian_water` into your HA `custom_components` folder, then restart.

Requires HA 2026.10+ (Python 3.14 syntax).

## Keeping up with core
When HA updates the core integration, diff it against this repo:
`https://github.com/home-assistant/core/tree/<version>/homeassistant/components/anglian_water`
