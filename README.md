# Alpicool, BrassMonkey, Ocean Comfort, Bodega, ... 12V/24V BLE Fridge Integration for Home Assistant

This is a Home Assistant Custom Component to control Alpicool, BrassMonkey, Ocean Comfort, Bodega, or other compatible portable fridges via Bluetooth Low Energy (BLE).

This integration creates multiple entities in Home Assistant, allowing you to monitor and control all known aspects of your fridge.

This component was inspired by the prior work done by klightspeed's [BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor).

***
## About this fork

This is a fork of [`Gruni22/alpicool_ha_ble`](https://github.com/Gruni22/alpicool_ha_ble), extended to work cleanly on a **Bodega**-branded RV fridge that shares the underlying Alpicool BLE protocol. Bodega is one of several rebadges of the same OEM platform (others include BougeRV, Euhomy, Setpower, JoyTutus), so these changes apply broadly to fridges in that family. All credit for the original integration goes to upstream — full upstream functionality is preserved.

Tested on a **Bodega 83L dual-zone** fridge/freezer (`PSP-CR65-AK` main board).

What this fork adds on top of upstream:

* **Correct temperatures in °F mode (bugfix).** The BLE status payload reports temperatures in whatever unit the fridge panel is currently set to, and byte 9 is the unit flag (`0` = °C, `1` = °F). Upstream decoded that flag but never acted on it, so a fridge in °F mode reported wrong values (raw `4`°F was published as `4`°C and displayed as `39`°F). The climate entity now exposes its temperature unit, min, and max dynamically from the device, letting Home Assistant handle any display conversion natively with no round-trip precision loss.
* **Configurable zone names.** Rename the Left/Right zones to anything meaningful (e.g. Refrigerator/Freezer, Top/Bottom).
* **External temperature sensors per zone.** Feed each zone's `current_temperature` from any HA temperature sensor (Ruuvi, Govee, etc.) instead of the fridge's internal NTC.

See [Fork Options](#fork-options-zone-names--external-sensors) below for usage.

## Features & Supported Entities

* **Climate:** A central `climate` entity for each cooling zone to:
    * Turn the fridge on and off.
    * Set the target temperature (in 1°C increments).
    * Switch between `Max` and `Eco` preset modes.
    * Display the current temperature.
* **Sensor:** Separate `sensor` entities for diagnostic data:
    * Battery charge percentage.
    * Battery voltage.
* **Switch:** A `switch` entity to enable or disable the fridge's control panel lock.
* **Number:** `number` entities to configure advanced settings directly from the UI:
    * Compressor start delay (in minutes).
    * Temperature hysteresis (return difference).
* **Select:** `select` entities to configure advanced settings directly from the UI:
    * Battery saver

## Dual-Zone Support
This integration supports !!!untested!!! **both single and dual-zone fridges**. 

* For **dual-zone** models, it will create two `climate` entities (`... Left` and `... Right`), which will both become available.
* For **single-zone** models, it will also create two `climate` entities, but the `... Right` entity will remain permanently `unavailable` as the fridge does not report data for it. You can disable or hide this second entity in Home Assistant.

***
## Installation

Easiest install is via [HACS](https://hacs.xyz/):

### Method 1: HACS (Recommended)
1.  [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Gruni22&repository=alpicool_ha_ble&category=integration)
4.  Search for "Alpicool BLE" and click "Install".
5.  Restart Home Assistant.

### Method 2: Manual Installation
1.  Download the latest release from this repository.
2.  Copy the `alpicool_ble` directory into the `custom_components` directory of your Home Assistant instance.
3.  Restart Home Assistant.

***
## Configuration

Configuration is done via the Home Assistant UI.

1.  Navigate to **Settings > Devices & Services**.
2.  Home Assistant should automatically discover your fridge if it is powered on and nearby. If so, click **Configure** on the discovered device card.
3.  If it's not discovered automatically, click **Add Integration**, search for "Alpicool BLE", and follow the prompts to select your device.
4.  Select "dual_zone_modes" if your freezer has a Freezer or Fridge Mode. This will disable seperate controls, when the device is in fridge mode.
5.  Press the pairing button on the fridge, if "APP" is written on the display.

***
## Fork Options: Zone Names & External Sensors

These options are added by this fork. After the integration is set up, click **Configure** on the integration card (**Settings > Devices & Services**) to open the options dialog. Changes take effect immediately — no Home Assistant restart needed.

### Zone display names

Free-form text fields let you relabel the Left and Right zones to whatever makes sense for your fridge (e.g. `Refrigerator` / `Freezer`, `Top` / `Bottom`). The internal zone identifiers and entity unique IDs are left unchanged, so renaming preserves all existing entity history. On single-zone fridges only the Left field is shown.

### External temperature sensors

Each zone can optionally read its `current_temperature` from any Home Assistant sensor with `device_class: temperature`, instead of the fridge's internal NTC thermistor. This is useful if you have a more accurate sensor (a Ruuvi tag, Govee, etc.) physically inside the cabinet. Pick a sensor per zone from the dropdown; clearing the field reverts to the fridge's internal sensor.

Notes:
* If the external sensor and the fridge report different units, Home Assistant converts automatically — a °C-reporting Ruuvi works fine even when the fridge is set to °F mode, and vice versa.
* If the external sensor becomes `unavailable`/`unknown` or reports non-numeric data, the zone falls back to the fridge's internal reading.
* The climate card refreshes the moment the external sensor updates, rather than waiting for the next BLE poll.
* **This affects display/monitoring only.** The fridge's compressor still cycles off its own internal thermistor; the external sensor does not change how the fridge regulates temperature.

If your sensor doesn't appear in the picker, confirm it has `device_class: temperature` set (check **Developer Tools > States**). Sensors sourced from some integrations may need this added via `customize:` in `configuration.yaml`.

***
## Technical Details & Protocol Quirks

The development of this integration revealed several quirks in the Alpicool BLE protocol that required specific workarounds in the code.

* **Inconsistent Protocol:** The rules for calculating packet length and checksums are not consistent across all commands.
* **Special Command Handling:** `BIND`, `QUERY`, `SET_LEFT`, and `SET_RIGHT` commands are treated as special cases with a different packet structure than more complex commands like `SET`.
* **Concatenated BLE Responses:** The fridge responds to `SET` commands by sending two packets concatenated into a single BLE notification: first an echo of the sent command, followed by a full status update. The notification handler was specifically rewritten to parse this data stream correctly and ignore the echo.
* **Signed Byte Conversion:** Temperature values are transmitted as signed 8-bit integers. The code correctly converts between negative temperature values (e.g., -20°C) and their unsigned byte representation (e.g., 236) for both sending and receiving data.
