"""Poll cached reports only; never scan or execute during polling."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RemotePowerAuthError, RemotePowerError
from .const import (
    ACTIONS, CONF_ENABLE_APT, CONF_ENABLE_CONTROL, CONF_SCAN_INTERVAL,
    CONTROL_ACTIONS, DEFAULT_SCAN_INTERVAL, DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class RemotePowerCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.entry = entry
        self.client = client
        self._actions = set()
        self.apt_enabled = entry.options.get(CONF_ENABLE_APT, False)
        self.control_enabled = entry.options.get(CONF_ENABLE_CONTROL, False)

    async def _async_update_data(self):
        try:
            report = await self.client.patch_report()
            versions = await self.client.host_versions()
            return {
                str(row["device_id"]): {
                    **row, "version": versions.get(str(row["device_id"]))
                }
                for row in report["devices"]
            }
        except RemotePowerAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RemotePowerError as err:
            raise UpdateFailed(str(err)) from err

    async def async_scan(self, device_id, apt=False):
        return await self.async_action(
            device_id, "search_updates" if apt else "scan_packages"
        )

    async def async_bulk_control(self, device_ids, action):
        if not self.last_update_success:
            raise HomeAssistantError("RemotePower data is unavailable")
        if action not in ("upgrade", "reboot", "shutdown") or not self.control_enabled:
            raise HomeAssistantError("Control actions are disabled or invalid")
        eligible = []
        results = {}
        for device_id in device_ids:
            row = self.data.get(device_id, {})
            if not row.get("online") or device_id in self._actions:
                results[device_id] = {"status": "failed", "error": "Host offline or busy"}
            else:
                eligible.append(device_id)
        if not eligible:
            return results
        self._actions.update(eligible)
        try:
            results.update(await self.client.bulk_control(eligible, action))
        except RemotePowerError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            self._actions.difference_update(eligible)
        await self.async_request_refresh()
        return results

    async def async_action(self, device_id, action):
        if not self.last_update_success:
            raise HomeAssistantError("RemotePower data is unavailable")
        if action not in ACTIONS:
            raise HomeAssistantError("Unsupported action")
        row = self.data.get(device_id)
        if not row or not row.get("online"):
            raise HomeAssistantError("Host is offline or no longer available")
        if action == "search_updates" and (
            not self.apt_enabled or row.get("pkg_manager") != "apt"
        ):
            raise HomeAssistantError("APT refresh is not enabled for this host")
        if action in CONTROL_ACTIONS and not self.control_enabled:
            raise HomeAssistantError("Control actions are disabled in integration options")
        if action.startswith("mode_") and row.get("pkg_manager") != "apt":
            raise HomeAssistantError("Upgrade mode only applies to APT hosts")
        if device_id in self._actions:
            raise HomeAssistantError("An action is already running for this host")
        self._actions.add(device_id)
        try:
            if action == "search_updates":
                await self.client.refresh_apt(device_id)
                result = {"status": "scan_queued"}
            elif action == "scan_packages":
                await self.client.scan_packages(device_id)
                result = {"status": "scan_queued"}
            else:
                result = await self.client.action(device_id, action)
        except RemotePowerError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            self._actions.discard(device_id)
        # Subsequent regular polls pick up the asynchronous agent report.
        await self.async_request_refresh()
        return result
