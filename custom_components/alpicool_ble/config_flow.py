"""Config flow for Alpicool BLE."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DUAL_ZONE_MODES,
    CONF_LEFT_EXTERNAL_TEMP_SENSOR,
    CONF_LEFT_ZONE_NAME,
    CONF_RIGHT_EXTERNAL_TEMP_SENSOR,
    CONF_RIGHT_ZONE_NAME,
    DEFAULT_LEFT_ZONE_NAME,
    DEFAULT_RIGHT_ZONE_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def normalize_ble_address(addr: str) -> str | None:
    """Normalize BLE address to format XX:XX:XX:XX:XX:XX or return None if invalid."""
    addr = addr.replace("-", "").replace(":", "").lower()
    if len(addr) != 12 or not all(c in "0123456789abcdef" for c in addr):
        return None
    return ":".join(addr[i : i + 2] for i in range(0, 12, 2)).upper()


class AlpicoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alpicool BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return AlpicoolOptionsFlow(config_entry)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle discovery via Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to finish setup."""
        errors = {}

        if user_input is not None:
            raw_address = user_input.get(CONF_ADDRESS)
            if not isinstance(raw_address, str):
                errors["base"] = "invalid_address"
            else:
                normalized_address = normalize_ble_address(raw_address)

                if not normalized_address:
                    errors["base"] = "invalid_address"
                else:
                    name = user_input.get(CONF_NAME, normalized_address)
                    await self.async_set_unique_id(normalized_address)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_ADDRESS: normalized_address,
                            CONF_NAME: name,
                            CONF_DUAL_ZONE_MODES: user_input.get(
                                CONF_DUAL_ZONE_MODES, False
                            ),
                        },
                        options={
                            CONF_LEFT_ZONE_NAME: user_input.get(
                                CONF_LEFT_ZONE_NAME, DEFAULT_LEFT_ZONE_NAME
                            ),
                            CONF_RIGHT_ZONE_NAME: user_input.get(
                                CONF_RIGHT_ZONE_NAME, DEFAULT_RIGHT_ZONE_NAME
                            ),
                        },
                    )

        default_name = (
            self._discovery_info.name if self._discovery_info else "Alpicool Fridge"
        )
        default_address = self._discovery_info.address if self._discovery_info else ""

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default=default_address): str,
                vol.Optional(CONF_NAME, default=default_name): str,
                vol.Optional(CONF_DUAL_ZONE_MODES, default=False): bool,
                vol.Optional(
                    CONF_LEFT_ZONE_NAME, default=DEFAULT_LEFT_ZONE_NAME
                ): str,
                vol.Optional(
                    CONF_RIGHT_ZONE_NAME, default=DEFAULT_RIGHT_ZONE_NAME
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )


class AlpicoolOptionsFlow(OptionsFlow):
    """Handle options for the Alpicool BLE integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Strip empty strings so unset sensors don't store ""
            cleaned = {
                k: v
                for k, v in user_input.items()
                if v not in (None, "")
            }
            return self.async_create_entry(title="", data=cleaned)

        current = self.config_entry.options
        temp_sensor_selector = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="temperature",
            )
        )

        schema_dict: dict[Any, Any] = {
            vol.Optional(
                CONF_LEFT_ZONE_NAME,
                default=current.get(CONF_LEFT_ZONE_NAME, DEFAULT_LEFT_ZONE_NAME),
            ): str,
            vol.Optional(
                CONF_LEFT_EXTERNAL_TEMP_SENSOR,
                default=current.get(CONF_LEFT_EXTERNAL_TEMP_SENSOR, ""),
            ): temp_sensor_selector,
        }

        # Only show the right-zone fields if this is a dual-zone fridge
        if self.config_entry.data.get(CONF_DUAL_ZONE_MODES, False) or "right_current" in (
            getattr(self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id), "status", {}) or {}
        ):
            schema_dict[
                vol.Optional(
                    CONF_RIGHT_ZONE_NAME,
                    default=current.get(
                        CONF_RIGHT_ZONE_NAME, DEFAULT_RIGHT_ZONE_NAME
                    ),
                )
            ] = str
            schema_dict[
                vol.Optional(
                    CONF_RIGHT_EXTERNAL_TEMP_SENSOR,
                    default=current.get(CONF_RIGHT_EXTERNAL_TEMP_SENSOR, ""),
                )
            ] = temp_sensor_selector

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )
