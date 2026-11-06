"""Self-check for verify_writes. Run: python tests/verify_writes_test.py"""

import asyncio
import os
import sys
from types import SimpleNamespace

import homeassistant  # noqa: F401  (import before anything pulls in httpx)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import custom_components.ariston.coordinator as coord  # noqa: E402

coord.WRITE_SETTLE_SECONDS = 0


class FakeBoiler:
    """Cloud value + a boiler that drops the first `drop` writes."""

    def __init__(self, value, drop):
        self.cloud = {("HeatingFlowTemp", 1): value}
        self.local = dict(self.cloud)
        self.drop = drop
        self.sent = []

    def _get_item_by_id(self, item_id, prop, zone=0):
        return self.local[(item_id, zone)]

    async def async_set_item_by_id(self, item_id, value, zone_number=0):
        self.sent.append((value, self.local[(item_id, zone_number)]))  # (value, prevValue)
        self.local[(item_id, zone_number)] = value  # library updates locally
        if self.drop:
            self.drop -= 1
        else:
            self.cloud[(item_id, zone_number)] = value

    def poll(self):
        self.local = dict(self.cloud)


async def run(drop, external_change=None):
    boiler = FakeBoiler(40, drop)
    c = SimpleNamespace(device=boiler, after_update=None)
    coord.verify_writes(c)
    await boiler.async_set_item_by_id("HeatingFlowTemp", 60, 1)
    for _ in range(4):
        if external_change is not None:
            boiler.cloud[("HeatingFlowTemp", 1)] = external_change
        boiler.poll()
        await c.after_update()
    return boiler


async def main():
    b = await run(drop=1)  # first write lost -> one resend with fresh prevValue
    assert b.cloud[("HeatingFlowTemp", 1)] == 60, b.cloud
    assert b.sent == [(60, 40), (60, 40)], b.sent

    b = await run(drop=0)  # applied first time -> no resend
    assert b.sent == [(60, 40)], b.sent

    b = await run(drop=1, external_change=55)  # someone set 55 -> leave it
    assert b.cloud[("HeatingFlowTemp", 1)] == 55 and len(b.sent) == 1, b.sent

    b = await run(drop=10)  # never applied -> 1 write + 2 resends, then give up
    assert len(b.sent) == 3, b.sent
    print("verify_writes OK")


asyncio.run(main())
