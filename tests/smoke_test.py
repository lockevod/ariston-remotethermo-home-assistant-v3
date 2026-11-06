"""End-to-end smoke test on a real Home Assistant core (no cloud access).

Boots HA from a temp config dir, adds the integration through its config flow
with the cloud API mocked (busErrors and energy endpoints answer HTTP 500),
then checks entities and a write.

Run:  python tests/smoke_test.py   (inside a venv with homeassistant + ariston)
"""

import asyncio
import logging
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant  # noqa: F401  (must be imported before anything pulls in httpx)
from ariston.ariston_api import ConnectionException
from ariston.const import (
    DeviceAttribute,
    DeviceFeatures,
    DeviceProperties,
    SystemType,
    ThermostatProperties,
)
from ariston.galevo_device import AristonGalevoDevice
from homeassistant import bootstrap, runner
from homeassistant.config_entries import ConfigEntryState

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = "TESTGW"
ATTRS = {
    DeviceAttribute.GW: GW,
    DeviceAttribute.SYS: SystemType.GALEVO.value,
    DeviceAttribute.NAME: "Mira",
    DeviceAttribute.SN: "SN1",
}


def _item(id_, value, zone=0, **kw):
    return {"id": id_, "value": value, "zone": zone, "unit": "°C", "decimals": 1,
            "min": 35, "max": 60, "step": 1, **kw}


def _api():
    api = AsyncMock()
    api.async_get_features_for_device.return_value = {
        DeviceFeatures.ZONES: [{"num": 1}],
        DeviceFeatures.HAS_BOILER: True,
        DeviceFeatures.HAS_METERING: True,
    }
    api.async_get_properties.return_value = {"items": [
        _item(DeviceProperties.DHW_TEMP, 50),
        _item(DeviceProperties.DHW_MODE, 0, options=[0, 1], optTexts=["Comfort", "Eco"]),
        _item(DeviceProperties.PLANT_MODE, 1, options=[0, 1, 5],
              optTexts=["Summer", "Winter", "Off"]),
        _item(ThermostatProperties.ZONE_MEASURED_TEMP, 20.5, zone=1),
        _item(ThermostatProperties.ZONE_DESIRED_TEMP, 21, zone=1),
        _item(ThermostatProperties.ZONE_COMFORT_TEMP, 21, zone=1, min=10, max=30),
        _item(ThermostatProperties.ZONE_MODE, 2, zone=1, options=[0, 1, 2],
              optTexts=["Off", "Time", "Manual"]),
    ]}
    api.async_get_menu_items.return_value = []
    for name in ("async_get_bus_errors", "async_get_consumptions_settings",
                 "async_get_energy_account", "async_get_consumptions_sequences"):
        getattr(api, name).side_effect = ConnectionException(500)
    return api


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, record):
        msg = self.format(record)
        if record.name.startswith("custom_components.ariston") or "platform ariston" in msg:
            self.records.append(f"{record.levelname} {record.name}: {msg}")


async def main():
    config_dir = tempfile.mkdtemp()
    os.makedirs(f"{config_dir}/custom_components")
    os.symlink(f"{REPO}/custom_components/ariston",
               f"{config_dir}/custom_components/ariston")
    with open(f"{config_dir}/configuration.yaml", "w") as f:
        f.write("homeassistant:\n  unit_system: metric\n")
    sys.path.insert(0, config_dir)

    import custom_components.ariston as integration
    import custom_components.ariston.config_flow as flow

    device = AristonGalevoDevice(_api(), ATTRS)
    cloud = MagicMock()
    cloud.async_connect = AsyncMock(return_value=True)
    cloud.async_discover = AsyncMock(return_value=[ATTRS])
    cloud.async_hello = AsyncMock(return_value=device)

    logs = _Logs()
    logging.getLogger().addHandler(logs)

    with patch.object(integration, "Ariston", return_value=cloud), \
         patch.object(flow, "Ariston", return_value=cloud):
        hass = await bootstrap.async_setup_hass(
            runner.RuntimeConfig(config_dir=config_dir, skip_pip=True))
        assert hass is not None, "HA failed to boot"
        await hass.async_start()

        result = await hass.config_entries.flow.async_init(
            "ariston", context={"source": "user"},
            data={"username": "u", "password": "p",
                  "api_url_setting": "https://example.invalid/api/v2/",
                  "api_user_agent": "test"})
        assert result["type"] == "create_entry", result
        await hass.async_block_till_done()

        entry = hass.config_entries.async_entries("ariston")[0]
        assert entry.state is ConfigEntryState.LOADED, entry.state

        climate = hass.states.get("climate.mira")
        assert climate, sorted(hass.states.async_entity_ids())
        assert climate.attributes["current_temperature"] == 20.5, climate
        assert climate.attributes["temperature"] == 21, climate

        wh = hass.states.get("water_heater.mira")
        assert wh and wh.attributes["temperature"] == 50, wh

        errors = [s for s in hass.states.async_all("sensor") if "errors" in s.entity_id]
        assert errors and errors[0].state == "unavailable", (
            errors, sorted(hass.states.async_entity_ids("sensor")))

        await hass.services.async_call(
            "water_heater", "set_temperature",
            {"entity_id": "water_heater.mira", "temperature": 55}, blocking=True)
        device.api.async_set_property.assert_awaited()
        assert hass.states.get("water_heater.mira").attributes["temperature"] == 55

        from custom_components.ariston.diagnostics import (
            async_get_config_entry_diagnostics,
        )
        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["attributes"]["gw"] == "**REDACTED**", diag["attributes"]
        assert diag["attributes"]["name"] == "**REDACTED**"
        assert diag["data"]["items"], diag
        import json
        assert "password" not in json.dumps(diag)  # serialisable, no credentials

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_stop()

    ours = logs.records
    bad = [r for r in ours if "deprecat" in r.lower() or "Traceback" in r
           or (r.startswith(("ERROR", "CRITICAL")) and "Ariston cloud error" not in r)]
    assert not bad, "\n".join(bad)
    print = lambda *a: sys.__stdout__.write(" ".join(map(str, a)) + "\n")  # noqa: A001
    print(f"OK - {len(hass.states.async_entity_ids())} entities; "
          f"ariston warnings: {len(ours)}")
    for r in ours:
        print("  warn:", r.splitlines()[0][:200])


if __name__ == "__main__":
    # HA's logging setup swallows stderr, so report through the real stdout.
    try:
        asyncio.run(main())
    except BaseException:
        import traceback
        sys.__stdout__.write(traceback.format_exc())
        sys.exit(1)
