"""Diagnostics support for Ariston: raw cloud data, credentials redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import COORDINATOR, DOMAIN

# gw/sn identify the gateway, loc/geofenceConfig locate the home, name is the
# user-chosen plant (often an address).
TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "gw", "sn", "loc", "geofenceConfig", "name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return what the cloud reports for this device, to add missing entities."""
    device = hass.data[DOMAIN][entry.unique_id][COORDINATOR].device
    return async_redact_data(
        {
            "options": dict(entry.options),
            "system_type": device.system_type.name,
            "attributes": device.attributes,
            "features": device.features,
            "custom_features": device.custom_features,
            "data": device.data,
            "menu_items": getattr(device, "menu_items", None),
            "bus_errors": device.bus_errors,
        },
        TO_REDACT,
    )
