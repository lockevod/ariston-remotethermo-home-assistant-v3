"""End-to-end smoke test on a real Home Assistant core (no cloud access).

Boots HA from a temp config dir, adds the integration through its config flow
with the cloud API mocked (busErrors and energy endpoints answer HTTP 500),
then checks entities and a write.

Run:  python tests/smoke_test.py   (inside a venv with homeassistant + ariston)
Scenarios: normal, and flaky (batched dataItems answers 500, hidden zone).
"""

import asyncio
import logging
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant  # noqa: F401  (must be imported before anything pulls in httpx)
from ariston.ariston_api import AristonAPI, ConnectionException
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


def _api(flaky_gateway: bool):
    api = AsyncMock()
    api.async_get_features_for_device.return_value = {
        DeviceFeatures.ZONES: [{"num": 1, "roomSens": False}, {"num": 2, "isHidden": True}],
        DeviceFeatures.HAS_BOILER: True,
        DeviceFeatures.HAS_METERING: True,
    }
    api.async_get_properties.return_value = {"items": [
        _item(DeviceProperties.DHW_TEMP, 50),
        _item(DeviceProperties.DHW_MODE, 0, options=[0, 1], optTexts=["Comfort", "Eco"]),
        _item(DeviceProperties.PLANT_MODE, 1, options=[0, 1, 5],
              optTexts=["Summer", "Winter", "OFF"]),
        _item(ThermostatProperties.ZONE_MEASURED_TEMP, 0.0, zone=1),  # no room sensor
        _item(ThermostatProperties.ZONE_DESIRED_TEMP, 21, zone=1),
        _item(DeviceProperties.CH_FLOW_TEMP, 29, decimals=0),
        _item(ThermostatProperties.HEATING_FLOW_TEMP, 60, zone=1, min=35, max=82, decimals=0),
        _item(ThermostatProperties.ZONE_COMFORT_TEMP, 21, zone=1, min=10, max=30),
        # Real Chaffoteaux Mira Link: no "Off" zone mode
        _item(ThermostatProperties.ZONE_MODE, 2, zone=1, options=[2, 3],
              optTexts=["Manual", "Time program"]),
    ]}
    if flaky_gateway:
        # Cloud behaviour from fustom issue 492: big batches fail, PlantMode only
        # comes through from the cache.
        known = api.async_get_properties.return_value["items"]
        api.async_get_properties.side_effect = ConnectionException(500)
        api._AristonAPI__api_url = "https://example.invalid/api/v2/"
        api.get_items = AristonAPI.get_items

        async def post(url, body):
            ids = [(i["id"], i["zn"]) for i in body["items"]]
            assert all(zn != 2 for _, zn in ids), "hidden zone requested"
            if len(ids) > 2 or (
                (DeviceProperties.PLANT_MODE, 0) in ids and not body["useCache"]
            ):
                raise ConnectionException(500)
            return {"items": [i for i in known if (i["id"], i["zone"]) in ids]}

        api._async_post.side_effect = post
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


async def main(flaky_gateway: bool):
    config_dir = tempfile.mkdtemp()
    os.makedirs(f"{config_dir}/custom_components")
    os.symlink(f"{REPO}/custom_components/ariston",
               f"{config_dir}/custom_components/ariston")
    with open(f"{config_dir}/configuration.yaml", "w") as f:
        f.write("homeassistant:\n  unit_system: metric\n")
    sys.path.insert(0, config_dir)

    import custom_components.ariston as integration
    import custom_components.ariston.config_flow as flow

    device = AristonGalevoDevice(_api(flaky_gateway), ATTRS)
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
        assert len(hass.states.async_entity_ids("climate")) == 1, "hidden zone shown"
        assert climate.attributes["preset_mode"] == "Winter", climate
        # No room sensor: no fake current temperature; target is the zone setpoint
        # that drives the gateway's virtual thermostat.
        assert climate.attributes["current_temperature"] is None, climate
        assert climate.attributes["max_temp"] == 30, climate
        assert "off" in climate.attributes["hvac_modes"], climate

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

        await hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": "climate.mira", "temperature": 24}, blocking=True)
        assert device.get_comfort_temp_value(1) == 24

        # Heating off keeps hot water: plant mode Summer, not OFF.
        await hass.services.async_call(
            "climate", "set_hvac_mode",
            {"entity_id": "climate.mira", "hvac_mode": "off"}, blocking=True)
        assert hass.states.get("climate.mira").state == "off"
        assert device.plant_mode.value == 0, device.plant_mode
        await hass.services.async_call(
            "climate", "set_hvac_mode",
            {"entity_id": "climate.mira", "hvac_mode": "heat"}, blocking=True)
        assert hass.states.get("climate.mira").state == "heat"

        plant = [s for s in hass.states.async_all("select") if "plant_mode" in s.entity_id]
        assert plant and plant[0].state == "Winter", plant
        await hass.services.async_call(
            "select", "select_option",
            {"entity_id": plant[0].entity_id, "option": "OFF"}, blocking=True)
        assert hass.states.get(plant[0].entity_id).state == "OFF"
        assert device.plant_mode.value == 5
        assert hass.states.get("climate.mira").state == "off"

        # Central heating switch = what generic_thermostat drives.
        heating = [s for s in hass.states.async_all("switch") if "central_heating" in s.entity_id]
        assert heating and heating[0].state == "off", heating  # plant is OFF here
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": heating[0].entity_id}, blocking=True)
        # Virtual zone: on = Winter + comfort at max (heat request without TA).
        assert device.plant_mode.value == 1 and device.get_comfort_temp_value(1) == 30
        assert hass.states.get(heating[0].entity_id).state == "on"
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": heating[0].entity_id}, blocking=True)
        # off = comfort at min, plant stays Winter (hot water untouched).
        assert device.get_comfort_temp_value(1) == 10 and device.plant_mode.value == 1
        assert hass.states.get(heating[0].entity_id).state == "off"

        # The library debug-logs the login response; it must come out redacted.
        api_log = logging.getLogger("ariston.ariston_api")
        seen = []
        catcher = logging.Handler()
        catcher.emit = lambda record: seen.append(record.getMessage())
        api_log.addHandler(catcher)
        api_log.setLevel(logging.DEBUG)
        api_log.debug("Response %s", {"token": "SECRET", "act": {"Email": "a@b.c"}})
        api_log.debug("Response %s", [{"gw": "F0AD4E000000", "loc": {"addr": "x"}}])
        api_log.debug("Request method %s, path: %s, params: %s", "GET",
                      "https://h/api/v2/remote/plants/F0AD4E000000/features", None)
        api_log.removeHandler(catcher)
        leaked = [m for m in seen if any(s in m for s in ("SECRET", "a@b.c", "F0AD4E000000", "addr"))]
        assert not leaked and len(seen) == 3, seen

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_stop()

    ours = logs.records
    bad = [r for r in ours if "deprecat" in r.lower() or "Traceback" in r
           or (r.startswith(("ERROR", "CRITICAL")) and "Ariston cloud error" not in r)]
    assert not bad, "\n".join(bad)
    print = lambda *a: sys.__stdout__.write(" ".join(map(str, a)) + "\n")  # noqa: A001
    print(f"OK flaky_gateway={flaky_gateway} - {len(hass.states.async_entity_ids())} entities; "
          f"ariston warnings: {len(ours)}")
    for r in ours:
        print("  warn:", r.splitlines()[0][:200])


if __name__ == "__main__":
    if len(sys.argv) == 1:  # HA boots once per process: one run per scenario
        import subprocess
        sys.exit(max(subprocess.call([sys.executable, __file__, flag])
                     for flag in ("normal", "flaky")))
    # HA's logging setup swallows stderr, so report through the real stdout.
    try:
        asyncio.run(main(flaky_gateway=sys.argv[1] == "flaky"))
    except BaseException:
        import traceback
        sys.__stdout__.write(traceback.format_exc())
        sys.exit(1)
