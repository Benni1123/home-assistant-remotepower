"""State semantics, discovery and action safeguards with HA test doubles."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

from support import HAError, load

api = load("api")
sensor = load("sensor")
binary = load("binary_sensor")
button = load("button")
select = load("select")
coordinator_module = load("coordinator")
services = load("services")


def make_coordinator():
    entry = SimpleNamespace(
        entry_id="entry", options={}, async_on_unload=MagicMock()
    )
    client = SimpleNamespace(
        url="https://rp.test", scan_packages=AsyncMock(),
        refresh_apt=AsyncMock(), action=AsyncMock(return_value={"status": "queued"}),
        bulk_control=AsyncMock(return_value={"one": {"status": "queued"}}),
        patch_report=AsyncMock(return_value={"devices": []}),
        host_versions=AsyncMock(return_value={}),
    )
    result = coordinator_module.RemotePowerCoordinator(SimpleNamespace(), entry, client)
    result.data = {"one": {
        "name": "Test", "online": True, "upgradable": 3, "security_updates": 1,
        "pkg_manager": "apt", "reboot_required": True, "last_seen": 1700000000,
        "group": "lab", "upgrade_mode": "standard",
    }}
    return result


class StateTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = make_coordinator()

    def test_count_and_unknown(self):
        entity = sensor.RemotePowerSensor(self.coordinator, "one", "upgradable")
        self.assertEqual(entity.native_value, 3)
        for value in (None, -1, False, "3"):
            self.coordinator.data["one"]["upgradable"] = value
            self.assertIsNone(entity.native_value)
        self.coordinator.data["one"]["upgradable"] = 0
        self.assertEqual(entity.native_value, 0)

    def test_offline_counts_unknown_connectivity_off(self):
        self.coordinator.data["one"]["online"] = False
        self.assertIsNone(
            sensor.RemotePowerSensor(self.coordinator, "one", "upgradable").native_value
        )
        self.assertFalse(binary.RemotePowerBinarySensor(self.coordinator, "one", "online").is_on)
        self.assertIsNone(
            binary.RemotePowerBinarySensor(self.coordinator, "one", "reboot_required").is_on
        )

    def test_fleet_never_silently_counts_unknown_as_zero(self):
        total = sensor.RemotePowerFleetSensor(self.coordinator, "total_updates")
        missing = sensor.RemotePowerFleetSensor(self.coordinator, "hosts_without_data")
        self.assertEqual(total.native_value, 3)
        self.coordinator.data["two"] = {"online": True, "upgradable": None}
        self.assertIsNone(total.native_value)
        self.assertEqual(missing.native_value, 1)

    def test_timestamp_utc(self):
        value = sensor.RemotePowerSensor(self.coordinator, "one", "last_seen").native_value
        self.assertEqual(value.utcoffset().total_seconds(), 0)

    def test_removed_host_unavailable(self):
        entity = sensor.RemotePowerSensor(self.coordinator, "one", "os")
        self.coordinator.data = {}
        self.assertFalse(entity.available)

    def test_controls_unavailable_by_default(self):
        for action in ("upgrade", "shutdown", "reboot"):
            entity = button.RemotePowerActionButton(self.coordinator, "one", action)
            self.assertFalse(entity.available)
            self.assertFalse(entity._attr_entity_registry_enabled_default)
        self.assertFalse(select.RemotePowerUpgradeMode(self.coordinator, "one").available)
        self.assertFalse(button.RemotePowerScanButton(self.coordinator, "one", True).available)

    def test_dynamic_discovery_no_duplicates(self):
        add = MagicMock()
        sensor.discover_hosts(
            self.coordinator, self.coordinator.entry, add,
            lambda device_id: [device_id],
        )
        self.coordinator.listeners[0]()
        self.assertEqual(add.call_count, 1)
        self.coordinator.data["two"] = {"name": "New"}
        self.coordinator.listeners[0]()
        self.assertEqual(add.call_args.args[0], ["two"])


class ActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = make_coordinator()

    async def test_poll_only_reads(self):
        await self.coordinator._async_update_data()
        self.coordinator.client.refresh_apt.assert_not_called()
        self.coordinator.client.scan_packages.assert_not_called()
        self.coordinator.client.action.assert_not_called()

    async def test_scan_only(self):
        await self.coordinator.async_scan("one")
        self.coordinator.client.scan_packages.assert_awaited_once_with("one")
        self.coordinator.client.refresh_apt.assert_not_called()

    async def test_apt_off_by_default(self):
        with self.assertRaises(HAError):
            await self.coordinator.async_scan("one", apt=True)
        self.coordinator.client.refresh_apt.assert_not_called()

    async def test_apt_requires_correct_manager(self):
        self.coordinator.apt_enabled = True
        self.coordinator.data["one"]["pkg_manager"] = "dnf"
        with self.assertRaises(HAError):
            await self.coordinator.async_scan("one", apt=True)

    async def test_apt_enabled(self):
        self.coordinator.apt_enabled = True
        await self.coordinator.async_scan("one", apt=True)
        self.coordinator.client.refresh_apt.assert_awaited_once_with("one")

    async def test_no_offline_or_missing_actions(self):
        self.coordinator.data["one"]["online"] = False
        for device_id in ("one", "unknown"):
            with self.assertRaises(HAError):
                await self.coordinator.async_scan(device_id)
        self.coordinator.client.scan_packages.assert_not_called()

    async def test_stale_coordinator_blocks_actions(self):
        self.coordinator.last_update_success = False
        with self.assertRaises(HAError):
            await self.coordinator.async_scan("one")
        self.coordinator.client.scan_packages.assert_not_called()

    async def test_controls_require_opt_in(self):
        for action in ("upgrade", "reboot", "shutdown", "mode_standard", "mode_extended"):
            with self.assertRaises(HAError):
                await self.coordinator.async_action("one", action)
        self.coordinator.client.action.assert_not_called()

    async def test_lock_prevents_parallel_actions(self):
        self.coordinator._actions.add("one")
        with self.assertRaises(HAError):
            await self.coordinator.async_scan("one")

    async def test_lock_released_on_failure(self):
        self.coordinator.client.scan_packages.side_effect = api.RemotePowerError("failure")
        with self.assertRaises(HAError):
            await self.coordinator.async_scan("one")
        self.assertFalse(self.coordinator._actions)

    async def test_approval_button_is_not_success(self):
        self.coordinator.control_enabled = True
        self.coordinator.client.action.return_value = {"status": "approval_required"}
        entity = button.RemotePowerActionButton(self.coordinator, "one", "reboot")
        with self.assertRaisesRegex(HAError, "approval"):
            await entity.async_press()


class BulkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = make_coordinator()
        self.hass = SimpleNamespace(
            data={"remotepower": {"entry": self.coordinator}},
            services=MagicMock(),
        )
        self.hass.services.has_service.return_value = False
        services.async_register_services(self.hass)
        self.handler = self.hass.services.async_register.call_args.args[2]

    async def call(self, **kwargs):
        data = services.SCHEMA({"entry_id": "entry", "action": "scan_packages", **kwargs})
        return await self.handler(SimpleNamespace(data=data))

    async def test_no_implicit_all_hosts(self):
        with self.assertRaises(HAError):
            await self.call()

    async def test_no_multiple_target_filters(self):
        with self.assertRaises(HAError):
            await self.call(group="lab", all_monitored=True)

    async def test_no_unknown_host(self):
        with self.assertRaises(HAError):
            await self.call(host_ids=["unknown"])

    async def test_group_target(self):
        result = await self.call(group="lab")
        self.assertEqual(result, {"results": {"one": {"status": "scan_queued"}}})

    async def test_explicit_ids_deduplicated(self):
        await self.call(host_ids=["one", "one"])
        self.coordinator.client.scan_packages.assert_awaited_once()

    async def test_controls_require_confirmation_and_option(self):
        with self.assertRaises(HAError):
            await self.call(group="lab", action="reboot")
        with self.assertRaises(HAError):
            await self.call(group="lab", action="reboot", confirm=True)
        self.coordinator.client.action.assert_not_called()

    async def test_native_bulk_guardrails_not_bypassed(self):
        self.coordinator.control_enabled = True
        result = await self.call(group="lab", action="reboot", confirm=True)
        self.assertEqual(result["results"]["one"]["status"], "queued")
        self.coordinator.client.bulk_control.assert_awaited_once_with(["one"], "reboot")
        self.coordinator.client.action.assert_not_called()

    async def test_explicit_monitored_filter(self):
        self.coordinator.data["two"] = {"online": True, "monitored": False}
        result = await self.call(all_monitored=True)
        self.assertEqual(set(result["results"]), {"one"})

    async def test_partial_failure_is_reported(self):
        self.coordinator.data["two"] = {"online": False, "group": "lab"}
        result = await self.call(group="lab")
        self.assertEqual(result["results"]["one"]["status"], "scan_queued")
        self.assertEqual(result["results"]["two"]["status"], "failed")
