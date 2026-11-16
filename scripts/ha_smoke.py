"""Exercise real HA entity/repair APIs with a fake host, never a network client."""

import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.remotepower.issues import sync_issues
from custom_components.remotepower.repairs import RemotePowerRebootRepair
from custom_components.remotepower.sensor import RemotePowerSensor


async def main():
    with tempfile.TemporaryDirectory() as directory:
        hass = HomeAssistant(str(Path(directory)))
        coordinator = SimpleNamespace(
            entry=SimpleNamespace(entry_id="smoke"),
            repairs_enabled=True,
            operations={},
            history={},
            data={"host": {
                "name": "Fake host", "online": True, "reboot_required": True,
                "upgradable": 1, "kept_back": ["example-package"],
            }},
            async_action=AsyncMock(return_value={"status": "queued"}),
        )
        hass.data["remotepower"] = {"smoke": coordinator}
        sync_issues(hass, coordinator, coordinator.data)
        registry = ir.async_get(hass)
        assert registry.async_get_issue("remotepower", "smoke_host_reboot") is not None
        sensor = RemotePowerSensor(coordinator, "host", "upgradable")
        assert sensor.native_value == 1
        assert sensor.extra_state_attributes["kept_back"] == ["example-package"]
        repair = RemotePowerRebootRepair({"entry_id": "smoke", "device_id": "host"})
        repair.hass = hass
        repair.context = {"issue_id": "smoke_host_reboot"}
        repair.handler = "remotepower"
        repair.flow_id = "smoke-flow"
        assert (await repair.async_step_init())["type"] == "form"
        coordinator.async_action.assert_not_called()
        result = await repair.async_step_confirm({"confirm_reboot": True})
        assert result["type"] == "abort" and result["reason"] == "reboot_queued"
        # The issue must remain until the host reports that it is fixed.
        assert registry.async_get_issue("remotepower", "smoke_host_reboot") is not None
        coordinator.data["host"]["reboot_required"] = False
        sync_issues(hass, coordinator, coordinator.data)
        assert registry.async_get_issue("remotepower", "smoke_host_reboot") is None
        await hass.async_stop(force=True)


if __name__ == "__main__":
    asyncio.run(main())
