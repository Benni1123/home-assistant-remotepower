"""API tests with no network or host execution."""

import asyncio
import unittest
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
            const.APT_REFRESH_COMMAND, "apt-get -o APT::Update::Error-Mode=any update"
        )
