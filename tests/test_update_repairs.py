"""Threshold, stale-data and options regressions for package-update repairs."""

from types import SimpleNamespace
import unittest

import voluptuous as vol

from support import issue_registry, load
from test_platforms import make_coordinator

issues = load("issues")
config_flow = load("config_flow")
KEY = ("remotepower", "entry_one_updates")


class UpdateRepairTests(unittest.TestCase):
    def setUp(self):
        self.c = make_coordinator()
        self.c.update_repair_threshold = 10
        self.hass = SimpleNamespace()

    def sync(self, count, online=True):
        self.c.data["one"].update(upgradable=count, online=online)
        issues.sync_issues(self.hass, self.c, self.c.data)
        return issue_registry(self.hass).issues

    def test_no_issue_below_threshold(self):
        self.assertNotIn(KEY, self.sync(9))

    def test_threshold_is_inclusive(self):
        issue = self.sync(10)[KEY]
        self.assertEqual(issue["translation_key"], "package_updates")
        self.assertEqual(issue["translation_placeholders"]["count"], "10")
        self.assertEqual(issue["translation_placeholders"]["threshold"], "10")
        self.assertFalse(issue["is_fixable"])

    def test_updates_same_issue_instead_of_creating_duplicates(self):
        self.sync(12)
        result = self.sync(67)
        self.assertEqual(result[KEY]["translation_placeholders"]["count"], "67")
        self.assertEqual(sum(key[1].endswith("_updates") for key in result), 1)

    def test_clears_when_count_drops_below_threshold(self):
        self.sync(12)
        self.assertNotIn(KEY, self.sync(9))

    def test_zero_disables_and_removes_existing_update_issue(self):
        self.sync(12)
        self.c.update_repair_threshold = 0
        result = self.sync(67)
        self.assertNotIn(KEY, result)
        # Other repair types are unaffected by the update-only threshold.
        self.assertIn(("remotepower", "entry_one_reboot"), result)

    def test_global_repairs_switch_disables_update_issues(self):
        self.sync(12)
        self.c.repairs_enabled = False
        self.assertFalse(self.sync(67))

    def test_unknown_counts_do_not_create_new_issues(self):
        for count in (None, -1, True, "67"):
            with self.subTest(count=count):
                self.assertNotIn(KEY, self.sync(count))

    def test_offline_counts_do_not_create_new_issues(self):
        self.assertNotIn(KEY, self.sync(67, online=False))

    def test_unknown_or_offline_does_not_clear_existing_issue(self):
        self.sync(12)
        self.assertIn(KEY, self.sync(None))
        self.assertIn(KEY, self.sync(0, online=False))
        self.assertNotIn(KEY, self.sync(0, online=True))

    def test_raising_threshold_clears_current_issue(self):
        self.sync(12)
        self.c.update_repair_threshold = 20
        self.assertNotIn(KEY, self.sync(12))

    def test_removed_host_issue_is_cleaned_up(self):
        self.sync(12)
        self.c.data = {}
        issues.sync_issues(self.hass, self.c, {})
        self.assertNotIn(KEY, issue_registry(self.hass).issues)


class UpdateRepairOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_and_range(self):
        flow = config_flow.RemotePowerOptionsFlow()
        flow.config_entry = SimpleNamespace(options={}, data={})
        schema = (await flow.async_step_init())["data_schema"]
        self.assertEqual(schema({})["update_repair_threshold"], 100)
        for value in (0, 1, 10, 100000):
            self.assertEqual(
                schema({"update_repair_threshold": value})["update_repair_threshold"], value
            )
        for value in (-1, 100001, "not-a-number"):
            with self.subTest(value=value), self.assertRaises(vol.Invalid):
                schema({"update_repair_threshold": value})

    async def test_existing_threshold_is_preserved_in_form(self):
        flow = config_flow.RemotePowerOptionsFlow()
        flow.config_entry = SimpleNamespace(
            options={"update_repair_threshold": 15}, data={}
        )
        schema = (await flow.async_step_init())["data_schema"]
        self.assertEqual(schema({})["update_repair_threshold"], 15)
