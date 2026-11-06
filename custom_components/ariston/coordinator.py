"""Coordinator class for Ariston module."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
import time
from typing import Any

from ariston.ariston_api import AristonAPI, ConnectionException
from ariston.base_device import AristonBaseDevice
from ariston.const import (
    ARISTON_DATA_ITEMS,
    ARISTON_REMOTE,
    DeviceFeatures,
    PropertyType,
    ZoneAttribute,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class DeviceDataUpdateCoordinator(DataUpdateCoordinator):
    """Manages polling for state changes from the device."""

    def __init__(
        self,
        hass: HomeAssistant,
        device: AristonBaseDevice,
        scan_interval_seconds: int,
        coordinator_name: str,
        async_update_state: Callable,
    ) -> None:
        """Initialize the data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{device.name}-{coordinator_name}",
            update_interval=timedelta(seconds=scan_interval_seconds),
            update_method=self._async_update,
        )

        self.device = device
        self._async_update_state = async_update_state
        self.after_update: Callable | None = None

    async def _async_update(self) -> None:
        """Fetch data; cloud errors are expected, not crashes."""
        try:
            await self._async_update_state()
        except ConnectionException as error:
            raise UpdateFailed(f"Ariston cloud error: {error}") from error
        if self.after_update:
            await self.after_update()


WRITE_RETRIES = 2
WRITE_SETTLE_SECONDS = 60


def _same(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return a == b


def verify_writes(coordinator: DeviceDataUpdateCoordinator) -> None:
    """Re-send a write the boiler silently dropped.

    The cloud sometimes accepts a dataItems/set but the boiler keeps the old
    value. After each poll, a write still showing the value it had *before* the
    write is sent again (max WRITE_RETRIES), with the fresh cloud value as
    prevValue. A value changed by someone else in between is left alone.
    """
    device = coordinator.device
    if not hasattr(device, "async_set_item_by_id") or not hasattr(
        device, "_get_item_by_id"
    ):
        return
    send = device.async_set_item_by_id
    pending: dict[tuple[str, int], dict[str, Any]] = {}

    def cloud_value(item_id: str, zone: int) -> Any:
        return device._get_item_by_id(item_id, PropertyType.VALUE, zone)

    async def tracked_set(item_id: str, value: float, zone_number: int = 0) -> None:
        before = cloud_value(item_id, zone_number)
        await send(item_id, value, zone_number)
        pending[(item_id, zone_number)] = {
            "value": value, "before": before, "retries": 0, "at": time.monotonic()
        }

    async def check() -> None:
        for key, write in list(pending.items()):
            now = cloud_value(*key)
            if _same(now, write["value"]) or not _same(now, write["before"]):
                pending.pop(key)  # applied, or changed by someone else
                continue
            if time.monotonic() - write["at"] < WRITE_SETTLE_SECONDS:
                continue  # give the boiler time to report it
            if write["retries"] >= WRITE_RETRIES:
                _LOGGER.warning(
                    "Boiler did not apply %s=%s (zone %s), giving up",
                    key[0], write["value"], key[1],
                )
                pending.pop(key)
                continue
            write["retries"] += 1
            write["at"] = time.monotonic()
            _LOGGER.info(
                "Boiler did not apply %s=%s (zone %s), resending (%s/%s)",
                key[0], write["value"], key[1], write["retries"], WRITE_RETRIES,
            )
            try:
                await send(key[0], write["value"], key[1])
            except ConnectionException as error:
                _LOGGER.debug("Resend failed: %s", error)

    device.async_set_item_by_id = tracked_set
    coordinator.after_update = check


def drop_hidden_zones(device: AristonBaseDevice) -> None:
    """Forget zones the app hides: no phantom thermostats, smaller requests."""
    zones = device.features.get(DeviceFeatures.ZONES)
    if isinstance(zones, list):
        device.features[DeviceFeatures.ZONES] = [
            zone for zone in zones if not zone.get(ZoneAttribute.IS_HIDDEN)
        ]


PROPERTIES_CHUNK_SIZE = 2


def use_chunked_properties_fallback(api: AristonAPI) -> None:
    """Retry dataItems in small chunks when the batched request answers 500.

    Some gateways (GALEVO, Cube S Net) fail with "Gateway error ... InternalError"
    when asked for many datapoints at once, while 1-2 items per request work and
    items that fail live work from the cloud cache (fustom issue 492).
    """
    batched = api.async_get_properties

    async def async_get_properties(gw_id, features, culture, umsys):
        try:
            return await batched(gw_id, features, culture, umsys)
        except ConnectionException as error:
            if error.args[:1] != (500,):
                raise
            _LOGGER.debug("Batched dataItems answered 500, retrying in chunks")

        # ponytail: library private attribute; ariston is pinned in manifest.json
        url = (
            f"{api._AristonAPI__api_url}{ARISTON_REMOTE}/{ARISTON_DATA_ITEMS}"
            f"/{gw_id}/get?umsys={umsys}"
        )

        async def post(items, use_cache):
            body = {"useCache": use_cache, "items": items,
                    "features": features, "culture": culture}
            try:
                return ((await api._async_post(url, body)) or {}).get("items")
            except ConnectionException:
                return None

        result: list = []
        all_items = api.get_items(features)
        for start in range(0, len(all_items), PROPERTIES_CHUNK_SIZE):
            chunk = all_items[start : start + PROPERTIES_CHUNK_SIZE]
            items = await post(chunk, False)
            if items is None:
                items = []
                for item in chunk:
                    single = (await post([item], False) if len(chunk) > 1 else None)
                    if single is None:
                        single = await post([item], True)
                    items.extend(single or [])
            result.extend(items)

        if not result:
            raise ConnectionException(500)
        return {"items": result}

    api.async_get_properties = async_get_properties
