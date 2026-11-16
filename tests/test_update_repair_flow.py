"""Opt-in package repair UI, confirmation and existing safeguards."""

from types import SimpleNamespace
import unittest

from support import issue_registry, load
from test_platforms import make_coordinator

issues = load("issues")
repairs = load("repairs")
config_flow = load("config_flow")


class UpdateRepairFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = make_coordinator()
        self.c.update_repair_threshold = 1
        self.hass = SimpleNamespace(data={"remotepower": {"entry": self.c}})
        self.flow = repairs.RemotePowerUpdateRepair({
            "entry_id": "entry", "device_id": "one", "kind": "updates",
        })
        self.flow.hass = self.hass

    async def test_disabled_by_default(self):
        self.assertFalse(self.c.update_repair_actions)
        issues.sync_issues(self.hass, self.c, self.c.data)
        issue = issue_registry(self.hass).issues[("remotepower", "entry_one_updates")]
        self.assertFalse(issue["is_fixable"])
        self.assertEqual((await self.flow.async_step_init())["reason"], "management_disabled")

    async def test_enabled_routes_to_package_flow(self):
        self.c.update_repair_actions = True
        issues.sync_issues(self.hass, self.c, self.c.data)
        issue = issue_registry(self.hass).issues[("remotepower", "entry_one_updates")]
        self.assertTrue(issue["is_fixable"])
        flow = await repairs.async_create_fix_flow(self.hass, "unused", issue["data"])
        self.assertIsInstance(flow, repairs.RemotePowerUpdateRepair)

    async def test_open_dialog_is_read_only(self):
        self.c.update_repair_actions = True
        self.c.apt_enabled = True
        self.c.data["one"]["upgradable_names"] = ["curl", "apache2"]
        result = await self.flow.async_step_init()
        self.assertEqual(result["type"], "menu")
        self.assertIn("search_updates", result["menu_options"])
        self.assertIn("curl", result["description_placeholders"]["packages"])
        self.c.client.action.assert_not_called()
        self.c.client.refresh_apt.assert_not_called()
        self.c.client.scan_packages.assert_not_called()

    async def test_apt_choice_requires_existing_option(self):
        self.c.update_repair_actions = True
        self.assertNotIn("search_updates", (await self.flow.async_step_init())["menu_options"])

    async def test_install_view_and_unchecked_confirmation_do_not_act(self):
        self.c.update_repair_actions = True
        self.c.control_enabled = True
        self.assertEqual((await self.flow.async_step_install())["type"], "form")
        result = await self.flow.async_step_install({"confirm_install": False})
        self.assertEqual(result["errors"]["base"], "confirmation_required")
        self.c.client.action.assert_not_called()

    async def test_confirmed_upgrade_uses_existing_control_gate(self):
        self.c.update_repair_actions = True
        result = await self.flow.async_step_install({"confirm_install": True})
        self.assertEqual(result["errors"]["base"], "install_blocked")
        self.c.client.action.assert_not_called()

    async def test_confirmed_upgrade_stays_open_as_queued(self):
        self.c.update_repair_actions = True
        self.c.control_enabled = True
        result = await self.flow.async_step_install({"confirm_install": True})
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "upgrade_queued")
        self.c.client.action.assert_awaited_once_with("one", "upgrade")

    async def test_proxmox_requires_additional_permission(self):
        self.c.update_repair_actions = True
        self.c.control_enabled = True
        self.c.data["one"]["is_proxmox"] = True
        result = await self.flow.async_step_install({"confirm_install": True})
        self.assertEqual(result["errors"]["base"], "install_blocked")
        self.c.client.action.assert_not_called()
        self.c.client.safe_upgrade.assert_not_called()

    async def test_proxmox_uses_no_cleanup_path(self):
        self.c.update_repair_actions = True
        self.c.control_enabled = True
        self.c.proxmox_enabled = True
        self.c.data["one"]["is_proxmox"] = True
        result = await self.flow.async_step_install({"confirm_install": True})
        self.assertEqual(result["reason"], "upgrade_queued")
        self.c.client.action.assert_not_called()
        self.c.client.safe_upgrade.assert_awaited_once()

    async def test_approval_is_not_reported_as_success(self):
        self.c.update_repair_actions = True
        self.c.control_enabled = True
        self.c.client.action.return_value = {"status": "approval_required"}
        result = await self.flow.async_step_install({"confirm_install": True})
        self.assertEqual(result["reason"], "approval_required")

    async def test_disabling_option_blocks_existing_dialog(self):
        self.c.update_repair_actions = True
        await self.flow.async_step_install()
        self.c.update_repair_actions = False
        result = await self.flow.async_step_install({"confirm_install": True})
        self.assertEqual(result["reason"], "management_disabled")
        self.c.client.action.assert_not_called()

    async def test_offline_host_cannot_install(self):
        self.c.update_repair_actions = True
        self.c.control_enabled = True
        self.c.data["one"]["online"] = False
        result = await self.flow.async_step_install({"confirm_install": True})
        self.assertEqual(result["errors"]["base"], "install_blocked")
        self.c.client.action.assert_not_called()

    async def test_scan_actions_only_run_when_selected(self):
        self.c.update_repair_actions = True
        self.c.apt_enabled = True
        self.assertEqual((await self.flow.async_step_scan_packages())["reason"], "scan_queued")
        self.c.client.scan_packages.assert_awaited_once_with("one")
        self.assertEqual((await self.flow.async_step_search_updates())["reason"], "scan_queued")
        self.c.client.refresh_apt.assert_awaited_once_with("one")
        self.c.client.action.assert_not_called()

    async def test_fresh_count_below_threshold_closes_without_command(self):
        self.c.update_repair_actions = True
        self.c.data["one"]["upgradable"] = 0
        result = await self.flow.async_step_init()
        self.assertEqual(result["type"], "create_entry")
        self.c.client.action.assert_not_called()

    async def test_package_display_is_bounded_and_escaped(self):
        self.c.update_repair_actions = True
        self.c.data["one"]["upgradable_names"] = ["bad`[link](https://example.com)"] * 120
        placeholders = (await self.flow.async_step_init())["description_placeholders"]
        self.assertEqual(placeholders["shown"], "100")
        self.assertNotIn("[link]", placeholders["packages"])

    async def test_options_default_off(self):
        flow = config_flow.RemotePowerOptionsFlow()
        flow.config_entry = SimpleNamespace(options={}, data={})
        schema = (await flow.async_step_init())["data_schema"]
        self.assertFalse(schema({})["update_repair_actions"])
