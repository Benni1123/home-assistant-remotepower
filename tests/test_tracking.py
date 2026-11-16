"""Evidence-based state transitions, safety guards and reboot repairs."""

import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

from support import HAError, issue_registry, load
from test_platforms import make_coordinator

models = load("models")
api = load("api")
issues = load("issues")
repairs = load("repairs")
diagnostics = load("diagnostics")
flow = load("config_flow")


def output(ts=110, rc=0, kind="upgrade", fingerprint="new"):
    return {"ts": ts, "rc": rc, "kind": kind, "fingerprint": fingerprint}


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.row = {"online": True, "last_boot": 10, "last_seen": 150}
        self.operation = models.start_operation("upgrade", self.row, [], 100)
        self.operation["status"] = "queued"

    def test_queued_is_not_success(self):
        models.update_operation(self.operation, self.row, [], ["upgrade"], 110)
        self.assertEqual(self.operation["status"], "queued")

    def test_dispatched_is_not_running_or_success(self):
        models.update_operation(self.operation, self.row, [], [], 110)
        self.assertEqual(self.operation["status"], "awaiting_result")

    def test_old_outputs_do_not_complete_new_action(self):
        models.update_operation(self.operation, self.row, [output(90)], [], 110)
        self.assertNotEqual(self.operation["status"], "success")

    def test_baseline_outputs_are_excluded(self):
        self.operation["baseline_outputs"] = [[110, "new", 0]]
        models.update_operation(self.operation, self.row, [output()], [], 110)
        self.assertNotEqual(self.operation["status"], "success")

    def test_zero_pending_does_not_prove_success(self):
        models.update_operation(self.operation, {**self.row, "upgradable": 0}, [], [], 110)
        self.assertNotEqual(self.operation["status"], "success")

    def test_confirmed_result(self):
        models.update_operation(self.operation, self.row, [output()], [], 120)
        self.assertEqual(self.operation["status"], "success")
        self.assertTrue(self.operation["rescan_due"])

    def test_failed_result_never_requests_rescan(self):
        models.update_operation(self.operation, self.row, [output(rc=100)], [], 120)
        self.assertEqual(self.operation["status"], "failed")
        self.assertFalse(self.operation["rescan_due"])

    def test_ambiguous_results_unknown(self):
        models.update_operation(self.operation, self.row, [output(), output(115)], [], 120)
        self.assertEqual(self.operation["status"], "unknown")

    def test_unrelated_output_is_ignored(self):
        models.update_operation(self.operation, self.row, [output(kind="other")], [], 120)
        self.assertNotEqual(self.operation["status"], "success")

    def test_tagged_command_requires_exact_fingerprint(self):
        self.operation.update(action="upgrade_no_cleanup", fingerprint="specific")
        models.update_operation(self.operation, self.row, [
            output(kind="upgrade_no_cleanup")
        ], [], 120)
        self.assertNotEqual(self.operation["status"], "success")
        models.update_operation(self.operation, self.row, [
            output(kind="upgrade_no_cleanup", fingerprint="specific")
        ], [], 120)
        self.assertEqual(self.operation["status"], "success")

    def test_approval_stays_pending_without_result(self):
        self.operation["status"] = "approval_required"
        models.update_operation(self.operation, self.row, [], [], 120)
        self.assertEqual(self.operation["status"], "approval_required")

    def test_timeout_is_unknown_not_failed(self):
        models.update_operation(self.operation, self.row, [], None, 8000)
        self.assertEqual(self.operation["status"], "unknown")

    def test_reboot_needs_new_boot_and_fresh_online_report(self):
        op = models.start_operation("reboot", self.row, [], 100)
        op["status"] = "queued"
        models.update_operation(op, {**self.row, "online": False}, [], None, 120)
        self.assertEqual(op["status"], "waiting_for_return")
        models.update_operation(op, self.row, [], None, 130)
        self.assertNotEqual(op["status"], "success")
        models.update_operation(op, {**self.row, "last_boot": 125}, [], None, 150)
        self.assertEqual(op["status"], "success")

    def test_reboot_without_baseline_never_claims_success(self):
        op = models.start_operation("reboot", {}, [], 100)
        models.update_operation(op, {**self.row, "last_boot": 120}, [], None, 150)
        self.assertNotEqual(op["status"], "success")

    def test_project_output_removes_secrets(self):
        projected = models.project_output({
            "ts": 10, "rc": 0, "cmd": "exec:echo mysecret", "output": "password=secret",
        })
        self.assertNotIn("secret", json.dumps(projected))

    def test_kernel_flag_distinct_from_patch_flag(self):
        projected = models.project_host({
            "hw_health": {"kernel_reboot": True}, "sysinfo": {},
        })
        self.assertTrue(projected["kernel_reboot_required"])

    def test_package_projection_and_proxmox_detection(self):
        projected = models.project_host({"sysinfo": {"packages": {
            "upgradable_names": ["proxmox-kernel-7.0"], "kept_back": ["proxmox-kernel-7.0"],
        }, "pkg_scan_ts": 123, "last_boot": 100}})
        self.assertTrue(projected["is_proxmox"])
        self.assertEqual(projected["last_scan"], 123)
        self.assertEqual(projected["kept_back"], ["proxmox-kernel-7.0"])

    def test_hostnames_do_not_classify_proxmox(self):
        self.assertFalse(models.project_host({"name": "pve"})["is_proxmox"])
        self.assertTrue(models.project_host({"tags": ["proxmox-host"]})["is_proxmox"])

    def test_maintenance_scopes(self):
        row = {"group": "lab", "site": "home", "tags": ["test"]}
        for scope, target in (
            ("global", ""), ("device", "one"), ("group", "lab"),
            ("site", "home"), ("tag", "test"), ("smart", "unevaluated"),
        ):
            with self.subTest(scope=scope):
                data = {"enabled": False, "windows": [
                    {"active": True, "scope": scope, "target": target},
                ]}
                self.assertTrue(models.maintenance_for("one", row, data))
                data["windows"][0]["active"] = False
                self.assertFalse(models.maintenance_for("one", row, data))

    def test_maintenance_unknown_fails_closed(self):
        self.assertTrue(models.maintenance_for("one", {}, None))


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = make_coordinator()
        self.c.control_enabled = True

    async def test_pending_action_blocks_second_control(self):
        self.c.operations["one"] = {"status": "queued"}
        with self.assertRaises(HAError):
            await self.c.async_action("one", "reboot")
        self.c.client.action.assert_not_called()

    async def test_proxmox_native_upgrade_always_blocked(self):
        self.c.data["one"]["is_proxmox"] = True
        self.c.proxmox_enabled = True
        with self.assertRaisesRegex(HAError, "autoremove"):
            await self.c.async_action("one", "upgrade")

    async def test_proxmox_reboot_requires_extra_opt_in(self):
        self.c.data["one"]["is_proxmox"] = True
        with self.assertRaisesRegex(HAError, "Proxmox"):
            await self.c.async_action("one", "reboot")

    async def test_safe_upgrade_uses_separate_endpoint(self):
        await self.c.async_action("one", "upgrade_no_cleanup")
        self.c.client.safe_upgrade.assert_awaited_once()
        self.c.client.action.assert_not_called()

    async def test_action_restored_without_replaying_command(self):
        await self.c.async_action("one", "reboot")
        saved = copy.deepcopy(self.c._store.data)
        restored = make_coordinator()
        restored._store.data = saved
        await restored.async_restore()
        self.assertEqual(restored.operations["one"]["status"], "queued")
        restored.client.action.assert_not_called()

    async def test_auto_rescan_only_once_after_success(self):
        self.c.operations["one"] = {
            "action": "upgrade", "status": "success", "rescan_due": True,
            "finished_at": 10,
        }
        await self.c._refresh_operations(self.c.data)
        await self.c._refresh_operations(self.c.data)
        self.c.client.scan_packages.assert_awaited_once_with("one")

    async def test_failed_auto_scan_not_retried_after_restart(self):
        self.c.operations["one"] = {
            "action": "upgrade", "status": "success", "rescan_due": True,
        }
        self.c.client.scan_packages.side_effect = api.RemotePowerConnectionError()
        await self.c._refresh_operations(self.c.data)
        restored = make_coordinator()
        restored._store.data = copy.deepcopy(self.c._store.data)
        await restored.async_restore()
        await restored._refresh_operations(restored.data)
        restored.client.scan_packages.assert_not_called()

    async def test_maintenance_excludes_bulk_hosts(self):
        self.c.client.maintenance.return_value = {"enabled": False, "windows": [
            {"active": True, "scope": "device", "target": "one"},
        ]}
        result = await self.c.async_bulk_control(["one"], "reboot")
        self.assertEqual(result["one"]["status"], "skipped_maintenance")
        self.c.client.bulk_control.assert_not_called()

    async def test_maintenance_fetch_failure_blocks_bulk(self):
        self.c.client.maintenance.side_effect = api.RemotePowerError()
        with self.assertRaises(HAError):
            await self.c.async_bulk_control(["one"], "reboot")
        self.c.client.bulk_control.assert_not_called()

    async def test_kernel_reboot_propagates_to_sensor_and_repairs(self):
        self.c.client.patch_report.return_value = {"devices": [{
            "device_id": "one", "name": "pve", "online": True, "reboot_required": False,
        }]}
        self.c.client.host_details.return_value = {
            "one": {"kernel_reboot_required": True},
        }
        self.c.client.kernel_state = AsyncMock(return_value={
            "running_kernel": "7.0.14-24-pve", "installed_kernel": "7.0.14-29-pve",
        })
        rows = await self.c._async_update_data()
        self.assertTrue(rows["one"]["reboot_required"])
        self.assertEqual(rows["one"]["reboot_sources"], ["kernel"])
        self.assertIn(("remotepower", "entry_one_reboot"), issue_registry(self.c.hass).issues)

    async def test_diagnostics_do_not_leak_credentials_or_hostnames(self):
        entry = SimpleNamespace(entry_id="entry", data={
            "url": "https://secret-host", "api_key": "MYSECRET",
        }, options={})
        hass = SimpleNamespace(data={"remotepower": {"entry": self.c}})
        self.c.data["one"].update(name="secret-host", upgradable_names=["sensitive-package"])
        value = json.dumps(await diagnostics.async_get_config_entry_diagnostics(hass, entry))
        for secret in ("MYSECRET", "secret-host", "sensitive-package"):
            self.assertNotIn(secret, value)


class RepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = make_coordinator()
        self.hass = SimpleNamespace(data={"remotepower": {"entry": self.c}})
        self.repair = repairs.RemotePowerRebootRepair({"entry_id": "entry", "device_id": "one"})
        self.repair.hass = self.hass

    async def test_dialog_never_reboots_without_confirmation(self):
        result = await self.repair.async_step_confirm({"confirm_reboot": False})
        self.assertEqual(result["errors"]["base"], "confirmation_required")
        self.c.client.action.assert_not_called()

    async def test_disabled_controls_block_repair_reboot(self):
        result = await self.repair.async_step_confirm({"confirm_reboot": True})
        self.assertEqual(result["errors"]["base"], "reboot_blocked")
        self.c.client.action.assert_not_called()

    async def test_queued_repair_is_not_closed_as_fixed(self):
        self.c.control_enabled = True
        result = await self.repair.async_step_confirm({"confirm_reboot": True})
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reboot_queued")

    async def test_clear_only_after_reboot_requirement_clears(self):
        issues.sync_issues(self.hass, self.c, self.c.data)
        key = ("remotepower", "entry_one_reboot")
        self.assertIn(key, issue_registry(self.hass).issues)
        self.c.data["one"].update(online=False, reboot_required=False)
        issues.sync_issues(self.hass, self.c, self.c.data)
        self.assertIn(key, issue_registry(self.hass).issues)
        self.c.data["one"]["online"] = True
        issues.sync_issues(self.hass, self.c, self.c.data)
        self.assertNotIn(key, issue_registry(self.hass).issues)

    async def test_repairs_can_be_disabled(self):
        issues.sync_issues(self.hass, self.c, self.c.data)
        self.c.repairs_enabled = False
        issues.sync_issues(self.hass, self.c, self.c.data)
        self.assertFalse(issue_registry(self.hass).issues)


class ReconfigureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.entry = SimpleNamespace(
            entry_id="entry", data={"url": "https://old.test", "api_key": "MYSECRET"},
            options={"verify_ssl": False},
        )
        self.flow = flow.RemotePowerConfigFlow()
        self.flow.hass = SimpleNamespace(config_entries=SimpleNamespace(
            async_update_entry=MagicMock()
        ))
        self.flow._get_reconfigure_entry = lambda: self.entry
        self.flow._async_current_entries = lambda: [self.entry]

    async def test_form_does_not_expose_existing_key(self):
        result = await self.flow.async_step_reconfigure()
        self.assertNotIn("MYSECRET", repr(result))

    async def test_reconfigure_validates_before_saving(self):
        from unittest.mock import patch
        client = SimpleNamespace(
            patch_report=AsyncMock(return_value={}),
            host_details=AsyncMock(return_value={}),
            maintenance=AsyncMock(return_value={}),
        )
        with patch.object(flow, "RemotePowerClient", return_value=client):
            result = await self.flow.async_step_reconfigure({
                "url": "https://new.test", "verify_ssl": False, "api_key": "",
            })
        self.assertEqual(result["reason"], "updated")
        self.assertEqual(self.flow.updates["data_updates"]["api_key"], "MYSECRET")
        self.assertEqual(self.flow.updates["data_updates"]["url"], "https://new.test")

    async def test_failed_reconfigure_keeps_existing_connection(self):
        from unittest.mock import patch
        client = SimpleNamespace(patch_report=AsyncMock(side_effect=api.RemotePowerAuthError()))
        with patch.object(flow, "RemotePowerClient", return_value=client):
            result = await self.flow.async_step_reconfigure({
                "url": "https://new.test", "verify_ssl": True, "api_key": "wrong",
            })
        self.assertEqual(result["errors"]["base"], "invalid_auth")
        self.flow.hass.config_entries.async_update_entry.assert_not_called()

    async def test_duplicate_server_rejected(self):
        other = SimpleNamespace(entry_id="other", data={"url": "https://new.test"})
        self.flow._async_current_entries = lambda: [self.entry, other]
        result = await self.flow.async_step_reconfigure({
            "url": "https://new.test", "verify_ssl": True,
        })
        self.assertEqual(result["reason"], "already_configured")
