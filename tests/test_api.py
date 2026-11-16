"""API tests with no network or host execution."""

import asyncio
import unittest
import hashlib
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from support import load

api = load("api")
const = load("const")


def response(data=None, status=200):
    value = MagicMock()
    value.status = status
    value.json = AsyncMock(return_value=data)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=value)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = MagicMock()
        self.client = api.RemotePowerClient(
            self.session, "https://rp.test:8443/", "secret", False
        )

    async def test_report_and_tls(self):
        report = {"devices": [{"device_id": "one", "upgradable": None}]}
        self.session.request.return_value = response(report)
        self.assertEqual(await self.client.patch_report(), report)
        args = self.session.request.call_args
        self.assertEqual(args.args, ("GET", "https://rp.test:8443/api/patch-report"))
        self.assertFalse(args.kwargs["ssl"])
        self.assertFalse(args.kwargs["allow_redirects"])
        self.assertEqual(args.kwargs["headers"], {"X-Token": "secret"})

    async def test_tls_on_by_default(self):
        client = api.RemotePowerClient(self.session, "https://rp.test", "key")
        self.session.request.return_value = response({"devices": []})
        await client.patch_report()
        self.assertTrue(self.session.request.call_args.kwargs["ssl"])

    async def test_bad_statuses(self):
        for code in (301, 302, 400, 401, 403, 404, 500, 503):
            with self.subTest(code=code):
                self.session.request.return_value = response({"key": "secret"}, code)
                with self.assertRaises(api.RemotePowerError) as error:
                    await self.client.patch_report()
                self.assertNotIn("secret", str(error.exception))

    async def test_bad_report(self):
        for data in (None, [], {}, {"devices": {}}, {"devices": [None]}, {"devices": [{}]}):
            with self.subTest(data=data):
                self.session.request.return_value = response(data)
                with self.assertRaises(api.RemotePowerError):
                    await self.client.patch_report()

    async def test_transport_errors_are_not_retried(self):
        for failure in (aiohttp.ClientConnectionError(), asyncio.TimeoutError()):
            self.session.request.reset_mock()
            self.session.request.side_effect = failure
            with self.assertRaises(api.RemotePowerConnectionError):
                await self.client.scan_packages("one")
            self.assertEqual(self.session.request.call_count, 1)

    async def test_scan(self):
        self.session.request.return_value = response({"ok": True})
        await self.client.scan_packages("one")
        args = self.session.request.call_args
        self.assertEqual(args.args[1], "https://rp.test:8443/api/devices/one/scan-packages")
        self.assertEqual(args.kwargs["json"], {})

    async def test_refresh_waits_for_success_before_scan(self):
        self.session.request.side_effect = [
            response({"ok": True, "output": {
                "cmd": f"exec:{const.APT_REFRESH_COMMAND}", "rc": 0, "output": "done"
            }}),
            response({"ok": True}),
        ]
        await self.client.refresh_apt("one")
        calls = self.session.request.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].args[1].endswith("/api/exec/wait"))
        self.assertEqual(calls[0].kwargs["json"]["cmd"], const.APT_REFRESH_COMMAND)
        self.assertTrue(calls[1].args[1].endswith("/scan-packages"))

    async def test_failed_unconfirmed_or_wrong_output_never_scans(self):
        for data in (
            {"approval_required": True}, {"ok": False, "timeout": True},
            {"ok": True, "output": {"cmd": "other", "rc": 0}},
            {"ok": True, "output": {"cmd": const.APT_REFRESH_COMMAND, "rc": 100}},
            {"ok": True, "output": {"cmd": const.APT_REFRESH_COMMAND, "rc": False}},
            {"ok": True, "output": {}}, {"ok": True},
        ):
            with self.subTest(data=data):
                self.session.request.reset_mock()
                self.session.request.return_value = response(data)
                with self.assertRaises(api.RemotePowerError):
                    await self.client.refresh_apt("one")
                self.assertEqual(self.session.request.call_count, 1)

    async def test_native_action_endpoints(self):
        for action, method, suffix in (
            ("upgrade", "POST", "/api/upgrade-device"),
            ("reboot", "POST", "/api/reboot"),
            ("shutdown", "POST", "/api/shutdown"),
            ("scan_acme", "POST", "/api/devices/one/acme/force-rescan"),
            ("mode_standard", "PUT", "/api/devices/one/upgrade-mode"),
            ("mode_extended", "PUT", "/api/devices/one/upgrade-mode"),
        ):
            with self.subTest(action=action):
                self.session.request.return_value = response({"ok": True})
                result = await self.client.action("one", action)
                self.assertIn(result["status"], ("queued", "applied"))
                self.assertEqual(self.session.request.call_args.args, (
                    method, "https://rp.test:8443" + suffix,
                ))
                if action.startswith("mode_"):
                    self.assertEqual(
                        self.session.request.call_args.kwargs["json"],
                        {"mode": action.removeprefix("mode_")},
                    )

    async def test_approval_is_not_execution(self):
        self.session.request.return_value = response(
            {"ok": True, "approval_required": True}, 202
        )
        self.assertEqual(await self.client.action("one", "reboot"),
                         {"status": "approval_required"})

    async def test_unsupported_action_never_posts(self):
        with self.assertRaises(api.RemotePowerError):
            await self.client.action("one", "exec rm")
        self.session.request.assert_not_called()

    async def test_roster(self):
        self.session.request.return_value = response([{"id": "one", "version": "8.0.0"}])
        self.assertEqual(await self.client.host_versions(), {"one": "8.0.0"})

    async def test_full_roster_projection_omits_unneeded_data(self):
        self.session.request.return_value = response([{
            "id": "one", "version": "8.0.0", "hw_health": {"kernel_reboot": True},
            "ssh_password": "SECRET", "sysinfo": {"accounts": "SECRET", "pkg_scan_ts": 100},
        }])
        result = await self.client.host_details()
        self.assertTrue(result["one"]["kernel_reboot_required"])
        self.assertNotIn("SECRET", repr(result))

    async def test_maintenance_requires_valid_complete_response(self):
        self.session.request.side_effect = [
            response({"enabled": False}), response({"windows": [{"active": "yes"}]}),
        ]
        with self.assertRaises(api.RemotePowerError):
            await self.client.maintenance()

    async def test_safe_upgrade_is_short_tagged_and_has_no_cleanup(self):
        self.session.request.return_value = response({"ok": True})
        result = await self.client.safe_upgrade("one", "a" * 32)
        body = self.session.request.call_args.kwargs["json"]
        self.assertTrue(self.session.request.call_args.args[1].endswith("/api/exec"))
        self.assertEqual(body["timeout"], 1800)
        full = f"exec:to=1800:{body['cmd']}"
        self.assertLessEqual(len(full), 512)
        self.assertEqual(result["fingerprint"], hashlib.sha256(full.encode()).hexdigest())
        self.assertIn("--with-new-pkgs", body["cmd"])
        self.assertIn("/lib/modules", body["cmd"])
        for forbidden in ("autoremove", " clean", "reboot", "dist-upgrade"):
            self.assertNotIn(forbidden, body["cmd"])

    async def test_safe_upgrade_retains_approval(self):
        self.session.request.return_value = response({"approval_required": True}, 202)
        result = await self.client.safe_upgrade("one", "b" * 32)
        self.assertEqual(result["status"], "approval_required")
        self.assertTrue(result["fingerprint"])

    async def test_safe_upgrade_rejects_shell_injection_token(self):
        with self.assertRaises(api.RemotePowerError):
            await self.client.safe_upgrade("one", "; rm -rf /")
        self.session.request.assert_not_called()

    async def test_kernel_projection_omits_hardware_inventory(self):
        self.session.request.return_value = response({
            "kernel": {"running": "old", "latest_installed": "new"},
            "accounts": [{"password": "SECRET"}],
        })
        result = await self.client.kernel_state("one")
        self.assertEqual(result, {"running_kernel": "old", "installed_kernel": "new"})

    async def test_output_projection_never_returns_raw_output(self):
        self.session.request.return_value = response({"outputs": [{
            "cmd": "exec:echo SECRET", "output": "SECRET", "ts": 100, "rc": 0,
        }]})
        self.assertNotIn("SECRET", repr(await self.client.outputs("one")))

    async def test_native_batch_preserves_approvals_and_failures(self):
        self.session.request.return_value = response({"ok": True, "results": {
            "one": {"ok": True}, "two": {"ok": True, "approval_required": True},
            "three": {"ok": False},
        }})
        result = await self.client.bulk_control(["one", "two", "three"], "reboot")
        self.assertEqual(result["one"]["status"], "queued")
        self.assertEqual(result["two"]["status"], "approval_required")
        self.assertEqual(result["three"]["status"], "failed")
        self.assertEqual(self.session.request.call_args.kwargs["json"],
                         {"device_ids": ["one", "two", "three"]})

    async def test_batch_missing_results_never_claims_success(self):
        self.session.request.return_value = response({"ok": True})
        with self.assertRaises(api.RemotePowerError):
            await self.client.bulk_control(["one", "two"], "reboot")

    def test_origin_validation(self):
        for value in (
            "http://rp.test", "https://user:pass@rp.test",
            "https://rp.test/path", "https://rp.test/?a=b", "https://rp.test/#a",
            "file:///etc/passwd", "https://rp.test:bad",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                api.normalize_url(value)

    def test_command_has_no_upgrade(self):
        self.assertEqual(
            const.APT_REFRESH_COMMAND,
            "command -v apt-get >/dev/null 2>&1 || exit 127; "
            "apt-get -o APT::Update::Error-Mode=any update",
        )

    async def test_missing_apt_never_scans(self):
        self.session.request.return_value = response({"ok": True, "output": {
            "cmd": f"exec:{const.APT_REFRESH_COMMAND}", "rc": 127,
        }})
        with self.assertRaisesRegex(api.RemotePowerError, "APT is not available"):
            await self.client.refresh_apt("one")
        self.assertEqual(self.session.request.call_count, 1)
