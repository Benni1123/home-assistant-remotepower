"""Small, secret-safe RemotePower API client."""

from __future__ import annotations

import asyncio
from urllib.parse import quote, urlsplit

import aiohttp

from .const import APT_REFRESH_COMMAND


class RemotePowerError(Exception):
    """API or protocol failure."""


class RemotePowerAuthError(RemotePowerError):
    """Invalid credentials or insufficient permissions."""


class RemotePowerConnectionError(RemotePowerError):
    """Transport failure."""


def normalize_url(value: str) -> str:
    """Only allow HTTPS server origins; never send keys to URL credentials."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an HTTPS server URL without a path or credentials")
    _ = parsed.port
    return f"https://{parsed.netloc}".rstrip("/")


def host_path(device_id: str) -> str:
    """Encode a host identifier as a single path segment."""
    if not device_id:
        raise RemotePowerError("Missing host ID")
    return f"/api/devices/{quote(device_id, safe='')}"


class RemotePowerClient:
    """Never retry writes: an interrupted request might already be queued."""

    def __init__(self, session, url: str, api_key: str, verify_ssl: bool = True):
        self.session = session
        self.url = normalize_url(url)
        self._api_key = api_key
        self.verify_ssl = verify_ssl

    async def request(self, method: str, path: str, body=None, timeout=30):
        """Do not include response bodies or request headers in errors."""
        try:
            async with self.session.request(
                method,
                self.url + path,
                headers={"X-Token": self._api_key},
                json=body,
                ssl=self.verify_ssl,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise RemotePowerAuthError("API key invalid or permission denied")
                if response.status not in (200, 201, 202):
                    raise RemotePowerError(f"RemotePower HTTP {response.status}")
                data = await response.json()
                if not isinstance(data, (dict, list)):
                    raise RemotePowerError("Unexpected API response")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise RemotePowerConnectionError("Cannot reach RemotePower") from err
        except ValueError as err:
            raise RemotePowerError("Invalid JSON response") from err

    async def patch_report(self) -> dict:
        data = await self.request("GET", "/api/patch-report")
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("devices"), list)
            or not all(isinstance(row, dict) and row.get("device_id") for row in data["devices"])
        ):
            raise RemotePowerError("Invalid patch report")
        return data

    async def host_versions(self) -> dict:
        """Use the lightweight roster; no sysinfo/secrets are fetched."""
        data = await self.request("GET", "/api/devices?slim=1")
        if not isinstance(data, list) or not all(
            isinstance(row, dict) and row.get("id") for row in data
        ):
            raise RemotePowerError("Invalid host roster")
        return {str(row["id"]): row.get("version") for row in data}

    async def scan_packages(self, device_id: str) -> None:
        data = await self.request("POST", host_path(device_id) + "/scan-packages", {})
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise RemotePowerError("Package scan was not accepted")

    async def action(self, device_id: str, action: str) -> dict:
        """Use native endpoints; never invent shell commands for power/upgrade."""
        if action == "scan_acme":
            method, path, body = "POST", host_path(device_id) + "/acme/force-rescan", {}
        elif action in ("mode_standard", "mode_extended"):
            method, path = "PUT", host_path(device_id) + "/upgrade-mode"
            body = {"mode": action.removeprefix("mode_")}
        elif action in ("upgrade", "reboot", "shutdown"):
            method = "POST"
            path = {
                "upgrade": "/api/upgrade-device", "reboot": "/api/reboot",
                "shutdown": "/api/shutdown",
            }[action]
            body = {"device_id": device_id}
        else:
            raise RemotePowerError("Unsupported action")
        data = await self.request(method, path, body)
        if not isinstance(data, dict):
            raise RemotePowerError("Invalid action response")
        if data.get("approval_required"):
            return {"status": "approval_required"}
        if data.get("ok") is not True:
            raise RemotePowerError("RemotePower did not accept the action")
        return {"status": "applied" if action.startswith("mode_") else "queued"}

    async def bulk_control(self, device_ids: list[str], action: str) -> dict:
        """Preserve native batch guardrails, rather than looping single requests."""
        paths = {
            "upgrade": "/api/upgrade-device", "reboot": "/api/reboot",
            "shutdown": "/api/shutdown",
        }
        if action not in paths or not device_ids:
            raise RemotePowerError("Invalid bulk action")
        data = await self.request(
            "POST", paths[action], {"device_ids": device_ids}
        )
        if not isinstance(data, dict):
            raise RemotePowerError("Invalid batch response")
        # Native routes return a single-host shape if exactly one ID is sent.
        rows = data.get("results") if len(device_ids) > 1 else {device_ids[0]: data}
        if not isinstance(rows, dict):
            raise RemotePowerError("Batch response has no per-host results")
        result = {}
        for device_id in device_ids:
            row = rows.get(device_id)
            if not isinstance(row, dict) or row.get("ok") is not True:
                result[device_id] = {
                    "status": "failed", "error": "Host action rejected or result missing; check RemotePower"
                }
            elif row.get("approval_required"):
                result[device_id] = {"status": "approval_required"}
            else:
                result[device_id] = {"status": "queued"}
        return result

    async def refresh_apt(self, device_id: str) -> None:
        """Only request a rescan after this exact command has succeeded."""
        data = await self.request(
            "POST",
            "/api/exec/wait",
            {"device_id": device_id, "cmd": APT_REFRESH_COMMAND, "timeout": 120},
            timeout=135,
        )
        if not isinstance(data, dict):
            raise RemotePowerError("Invalid command response")
        if data.get("approval_required"):
            raise RemotePowerError(
                "Approval required in RemotePower. After execution, use 'Rescan package data'."
            )
        if data.get("timeout") or data.get("ok") is not True:
            raise RemotePowerError(
                "Execution not confirmed. The command may still run; check RemotePower before retrying."
            )
        output = data.get("output")
        if (
            not isinstance(output, dict)
            or output.get("cmd") not in (APT_REFRESH_COMMAND, f"exec:{APT_REFRESH_COMMAND}")
            or type(output.get("rc")) is not int
            or output["rc"] != 0
        ):
            raise RemotePowerError(
                "APT refresh failed or returned an unrelated result. Check command history."
            )
        await self.scan_packages(device_id)
