"""Climate platform for the Alpicool BLE integration."""

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.unit_conversion import TemperatureConverter

from .api import FridgeApi
from .const import (
    CONF_DUAL_ZONE_MODES,
    CONF_LEFT_EXTERNAL_TEMP_SENSOR,
    CONF_LEFT_ZONE_NAME,
    CONF_RIGHT_EXTERNAL_TEMP_SENSOR,
    CONF_RIGHT_ZONE_NAME,
    DEFAULT_LEFT_ZONE_NAME,
    DEFAULT_RIGHT_ZONE_NAME,
    DOMAIN,
    PRESET_ECO,
    PRESET_FREEZER,
    PRESET_FRIDGE,
    PRESET_MAX,
)
from .entity import AlpicoolEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alpicool climate entities based on initial status."""
    api: FridgeApi = hass.data[DOMAIN][entry.entry_id]

    entities = [AlpicoolClimateZone(entry, api, "left")]

    if "right_current" in api.status:
        _LOGGER.debug("Dual-zone fridge detected, adding right zone entity")
        entities.append(AlpicoolClimateZone(entry, api, "right"))

    async_add_entities(entities)


class AlpicoolClimateZone(AlpicoolEntity, ClimateEntity):
    """Representation of an Alpicool refrigerator zone."""

    _attr_hvac_modes = [HVACMode.COOL, HVACMode.OFF]
    _attr_target_temperature_step = 1.0
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(self, entry: ConfigEntry, api: FridgeApi, zone: str) -> None:
        """Initialize the climate entity for a specific zone."""
        super().__init__(entry, api)
        self._entry = entry
        self._zone = zone
        self._has_fridge_freezer_mode = entry.data.get(CONF_DUAL_ZONE_MODES, False)

        self._attr_unique_id = f"{self._address}_{self._zone}"
        # Display name comes from options (user-configurable), falling back to
        # the original "Left"/"Right" defaults.
        self._attr_name = self._zone_display_name

    @property
    def _zone_display_name(self) -> str:
        """Return the user-configured display name for this zone."""
        options = self._entry.options
        if self._zone == "left":
            return options.get(CONF_LEFT_ZONE_NAME, DEFAULT_LEFT_ZONE_NAME)
        return options.get(CONF_RIGHT_ZONE_NAME, DEFAULT_RIGHT_ZONE_NAME)

    @property
    def _external_temp_sensor(self) -> str | None:
        """Return the external temperature sensor entity_id for this zone, if any."""
        key = (
            CONF_LEFT_EXTERNAL_TEMP_SENSOR
            if self._zone == "left"
            else CONF_RIGHT_EXTERNAL_TEMP_SENSOR
        )
        sensor = self._entry.options.get(key)
        return sensor or None

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit the device is currently configured for.

        Byte 9 of the BLE status payload is the unit flag: 0 = Celsius,
        1 = Fahrenheit. Reporting this dynamically lets Home Assistant
        handle any display conversion without round-trip precision loss.
        """
        return (
            UnitOfTemperature.FAHRENHEIT
            if self.api.status.get("unit") == 1
            else UnitOfTemperature.CELSIUS
        )

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature, in the device's native unit."""
        val = self.api.status.get("temp_min")
        if val is not None:
            return float(val)
        return -4.0 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else -20.0

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature, in the device's native unit."""
        val = self.api.status.get("temp_max")
        if val is not None:
            return float(val)
        return 68.0 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 20.0

    @property
    def _is_dual_zone(self) -> bool:
        """Helper to check if this is a dual-zone model."""
        return "right_current" in self.api.status

    @property
    def preset_modes(self) -> list[str] | None:
        """Return a list of available preset modes based on user configuration."""
        if self._is_dual_zone and self._has_fridge_freezer_mode:
            return [PRESET_FRIDGE, PRESET_FREEZER]
        return [PRESET_MAX, PRESET_ECO]

    @property
    def available(self) -> bool:
        """Return True if the device and this specific zone are available."""
        if not super().available:
            return False

        # For configured dual-zone models, the right zone is only available in Freezer mode
        if (
            self._is_dual_zone
            and self._has_fridge_freezer_mode
            and self._zone == "right"
        ):
            # run_mode 0 is Fridge, 1 is Freezer
            if self.api.status.get("run_mode") == 0:
                return False

        return True

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation."""
        return HVACMode.COOL if self.api.status.get("powered_on") else HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature for this zone.

        Prefers an external temperature sensor (e.g. a Ruuvi tag) if one is
        configured in the integration options. Falls back to the fridge's
        internal NTC reading. Handles unit mismatch between the external
        sensor and the climate entity's declared unit automatically.
        """
        ext_sensor = self._external_temp_sensor
        if ext_sensor:
            state = self.hass.states.get(ext_sensor)
            if state and state.state not in (None, "", STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    value = float(state.state)
                except (TypeError, ValueError):
                    _LOGGER.debug(
                        "External sensor %s has non-numeric state %s; "
                        "falling back to internal sensor",
                        ext_sensor,
                        state.state,
                    )
                else:
                    ext_unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                    own_unit = self.temperature_unit
                    if ext_unit and ext_unit != own_unit:
                        try:
                            value = TemperatureConverter.convert(
                                value, ext_unit, own_unit
                            )
                        except (ValueError, TypeError) as err:
                            _LOGGER.debug(
                                "Could not convert %s from %s to %s: %s",
                                ext_sensor,
                                ext_unit,
                                own_unit,
                                err,
                            )
                    return value

        return self.api.status.get(f"{self._zone}_current")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature for this zone."""
        return self.api.status.get(f"{self._zone}_target")

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode, adapted for user configuration."""
        run_mode = self.api.status.get("run_mode")
        if self._is_dual_zone and self._has_fridge_freezer_mode:
            return PRESET_FREEZER if run_mode == 1 else PRESET_FRIDGE
        return PRESET_ECO if run_mode == 1 else PRESET_MAX

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        is_on = hvac_mode == HVACMode.COOL
        await self.api.async_set_values({"powered_on": is_on})

        await asyncio.sleep(0.5)
        if await self.api.update_status():
            async_dispatcher_send(self.hass, f"{DOMAIN}_{self._address}_update")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature for this zone."""
        if ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            await self.api.async_set_temperature(self._zone, temp)

            await asyncio.sleep(0.5)
            if await self.api.update_status():
                async_dispatcher_send(self.hass, f"{DOMAIN}_{self._address}_update")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        is_mode_1 = preset_mode in [PRESET_ECO, PRESET_FREEZER]
        run_mode_value = 1 if is_mode_1 else 0
        await self.api.async_set_values({"run_mode": run_mode_value})
        await asyncio.sleep(0.5)
        if await self.api.update_status():
            async_dispatcher_send(self.hass, f"{DOMAIN}_{self._address}_update")

    async def async_added_to_hass(self) -> None:
        """Register listeners when the entity is added to HA."""
        await super().async_added_to_hass()

        # Update this entity when its external temp sensor changes state.
        ext_sensor = self._external_temp_sensor
        if ext_sensor:
            _LOGGER.debug(
                "Tracking external temp sensor %s for zone %s",
                ext_sensor,
                self._zone,
            )

            @callback
            def _async_external_temp_changed(event: Event) -> None:
                self.async_write_ha_state()

            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [ext_sensor], _async_external_temp_changed
                )
            )
