# Anglian Water (fork) for Home Assistant

A fork of Home Assistant's built-in [Anglian Water](https://www.home-assistant.io/integrations/anglian_water) integration, packaged as a custom component so it can be changed independently of HA releases.

**Based on:** `home-assistant/core` tag `2026.10.2`, `homeassistant/components/anglian_water` (uses `pyanglianwater==3.3.2`). Original code owner: @pantherale0. Licensed under Apache 2.0 like HA core; see [LICENSE](LICENSE).

> Installing this **overrides** the built-in integration (same `anglian_water` domain). Existing config entries carry over, so there's no need to re-add the account. Remove the folder and restart to go back to the core version.

## Changes from core
- `manifest.json`: added `version`, repo docs/issue links, dropped `quality_scale`.
- `strings.json` / `translations/en.json`: shared `[%key:common::…%]` references inlined, since custom components can't resolve them.
- `quality_scale.yaml` removed (core-only).

No functional changes yet.

## Installation
**HACS:** add `https://github.com/Luca-Bachini-Barr/ha-anglian-water` as a custom repository (type Integration), install it, then restart.

**Manual:** copy `custom_components/anglian_water` into your HA `custom_components` folder, then restart.

Requires HA 2026.10+ (Python 3.14 syntax).

## Keeping up with core
When HA updates the core integration, diff it against this repo:
`https://github.com/home-assistant/core/tree/<version>/homeassistant/components/anglian_water`
