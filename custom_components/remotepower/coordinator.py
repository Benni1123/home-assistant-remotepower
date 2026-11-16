"""Read reports and observe explicit actions; one scan after confirmed upgrades."""

from datetime import timedelta
import copy
import logging
import time
from uuid import uuid4

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .api import RemotePowerAuthError, RemotePowerError, RemotePowerRejected
from .const import (
    ACTIONS, CONF_ENABLE_APT, CONF_ENABLE_CONTROL, CONF_SCAN_INTERVAL,
    CONTROL_ACTIONS, DEFAULT_SCAN_INTERVAL, DOMAIN,
    CONF_ALLOW_PROXMOX, CONF_REPAIRS,
    CONF_UPDATE_REPAIR_THRESHOLD, DEFAULT_UPDATE_REPAIR_THRESHOLD,
)
from .models import (
    TERMINAL, can_try_apt_refresh, maintenance_for, number, project_output,
    start_operation, update_operation,
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
        self.proxmox_enabled = entry.options.get(CONF_ALLOW_PROXMOX, False)
        self.repairs_enabled = entry.options.get(CONF_REPAIRS, True)
        self.update_repair_threshold = entry.options.get(
            CONF_UPDATE_REPAIR_THRESHOLD, DEFAULT_UPDATE_REPAIR_THRESHOLD
        )
        self.operations = {}
        self.history = {}
        self.proxmox_hosts = set()
        self.maintenance = None
        self.server_offset = 0
        self._last_saved = None
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.operations")

    async def async_restore(self):
        data = await self._store.async_load()
        if isinstance(data, dict):
            self.operations = data.get("operations", {})
            self.history = data.get("history", {})
            self.proxmox_hosts = set(data.get("proxmox_hosts", []))
            self._last_saved = copy.deepcopy(data)

    async def _save(self):
        snapshot = {
            "operations": self.operations, "history": self.history,
            "proxmox_hosts": sorted(self.proxmox_hosts),
        }
        if snapshot != self._last_saved:
            snapshot = copy.deepcopy(snapshot)
            await self._store.async_save(snapshot)
            self._last_saved = snapshot

    def now(self):
        return int(time.time() + self.server_offset)

    async def _async_update_data(self):
        try:
            report = await self.client.patch_report()
            details = await self.client.host_details()
            self.maintenance = await self.client.maintenance()
            server_now = number(report.get("generated_at"))
            if server_now:
                self.server_offset = server_now - time.time()
            rows = {
                str(row["device_id"]): {
                    **row, **details.get(str(row["device_id"]), {})
                }
                for row in report["devices"]
            }
            for device_id, row in rows.items():
                row["reboot_sources"] = []
                if row.get("reboot_required"):
                    row["reboot_sources"].append("system")
                if row.get("kernel_reboot_required"):
                    row["reboot_sources"].append("kernel")
                    try:
                        row.update(await self.client.kernel_state(device_id))
                    except RemotePowerError:
                        pass  # The roster flag is already positive evidence.
                row["reboot_required"] = bool(row["reboot_sources"])
                if row.get("is_proxmox"):
                    self.proxmox_hosts.add(device_id)
                row["is_proxmox"] = device_id in self.proxmox_hosts
                row["maintenance"] = maintenance_for(device_id, row, self.maintenance)
                # The patch report already contains the recent update history.
                recent = [project_output(item) for item in row.pop("recent_patch_commands", [])
                          if isinstance(item, dict)]
                row["update_history"] = [
                    {"finished_at": item["ts"], "exit_code": item["rc"],
                     "status": "success" if item["rc"] == 0 else "failed"}
                    for item in recent if item["kind"] in ("upgrade", "upgrade_no_cleanup")
                    and item["rc"] is not None
                ][-10:]
            await self._refresh_operations(rows)
            from .issues import sync_issues
            sync_issues(self.hass, self, rows)
            await self._save()
            return rows
        except RemotePowerAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RemotePowerError as err:
            raise UpdateFailed(str(err)) from err

    async def _refresh_operations(self, rows):
        active = {key: value for key, value in self.operations.items()
                  if key in rows and value["status"] not in TERMINAL
                  and key not in self._actions}
        queue = None
        if active:
            try:
                queue = await self.client.command_queue()
            except RemotePowerError:
                pass  # Read-only keys cannot access the queue; never invent "running".
        for device_id, operation in active.items():
            try:
                outputs = await self.client.outputs(device_id)
            except RemotePowerError:
                outputs = []
            update_operation(
                operation, rows[device_id], outputs,
                queue.get(device_id, []) if queue is not None else None, self.now(),
            )
        for device_id, operation in self.operations.items():
            if device_id not in rows:
                continue
            # Persist intent BEFORE issuing the follow-up scan. Never replay it
            # after HA restart if transport failed after the server accepted it.
            if operation.get("rescan_due") and not operation.get("rescan_attempted"):
                operation["rescan_attempted"] = True
                await self._save()
                try:
                    await self.client.scan_packages(device_id)
                    operation["rescan_status"] = "queued"
                except RemotePowerError:
                    operation["rescan_status"] = "unconfirmed"
            if (
                operation.get("rescan_status") == "queued"
                and (number(rows[device_id].get("last_scan")) or 0)
                > (number(operation.get("finished_at")) or 0)
            ):
                operation["rescan_status"] = "reported"
            rows[device_id]["operation_status"] = operation["status"]

    def _control_guard(self, device_id, action):
        row = self.data.get(device_id, {})
        if action in CONTROL_ACTIONS and not self.control_enabled:
            raise HomeAssistantError("Control actions are disabled in integration options")
        if row.get("is_proxmox"):
            if action == "upgrade":
                raise HomeAssistantError(
                    "Native upgrade includes autoremove. Use 'Upgrade without cleanup' for Proxmox."
                )
            if action in ("reboot", "shutdown", "upgrade_no_cleanup") and not self.proxmox_enabled:
                raise HomeAssistantError(
                    "Proxmox controls are locked. Enable them explicitly; host power actions affect all guests."
                )
        if action == "upgrade_no_cleanup" and row.get("pkg_manager") != "apt":
            raise HomeAssistantError("Upgrade without cleanup is only available for APT hosts")
        pending = self.operations.get(device_id)
        if action in CONTROL_ACTIONS and pending and pending["status"] not in TERMINAL:
            raise HomeAssistantError("A previous action is not yet confirmed; check RemotePower")

    async def async_filter_bulk(self, device_ids):
        # Re-read maintenance immediately before a bulk request, not just from
        # the last polling cycle. Failure blocks the batch.
        try:
            self.maintenance = await self.client.maintenance()
        except RemotePowerError as err:
            raise HomeAssistantError("Maintenance state unavailable; bulk action blocked") from err
        eligible, skipped = [], {}
        for device_id in device_ids:
            if maintenance_for(device_id, self.data.get(device_id, {}), self.maintenance):
                skipped[device_id] = {"status": "skipped_maintenance"}
            else:
                eligible.append(device_id)
        return eligible, skipped

    async def _prepare_operation(self, device_id, action):
        try:
            outputs = await self.client.outputs(device_id)
        except RemotePowerError as err:
            raise HomeAssistantError("Cannot establish command-history baseline; action blocked") from err
        previous = self.operations.get(device_id)
        if previous:
            archived = {key: previous.get(key) for key in
                        ("action", "status", "requested_at", "finished_at", "exit_code")}
            self.history[device_id] = (self.history.get(device_id, []) + [archived])[-10:]
        operation = start_operation(action, self.data[device_id], outputs, self.now())
        self.operations[device_id] = operation
        await self._save()
        return operation

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
        device_ids, skipped = await self.async_filter_bulk(device_ids)
        results.update(skipped)
        for device_id in device_ids:
            row = self.data.get(device_id, {})
            if not row.get("online") or device_id in self._actions:
                results[device_id] = {"status": "failed", "error": "Host offline or busy"}
            else:
                try:
                    self._control_guard(device_id, action)
                    self._actions.add(device_id)
                    await self._prepare_operation(device_id, action)
                except HomeAssistantError as err:
                    self._actions.discard(device_id)
                    results[device_id] = {"status": "failed", "error": str(err)}
                else:
                    eligible.append(device_id)
        if not eligible:
            return results
        self._actions.update(eligible)
        try:
            results.update(await self.client.bulk_control(eligible, action))
            for device_id in eligible:
                self.operations[device_id]["status"] = results[device_id]["status"]
        except RemotePowerError as err:
            for device_id in eligible:
                self.operations[device_id]["status"] = (
                    "failed" if isinstance(err, (RemotePowerAuthError, RemotePowerRejected)) else "unknown"
                )
                self.operations[device_id]["finished_at"] = self.now()
            raise HomeAssistantError(str(err)) from err
        finally:
            self._actions.difference_update(eligible)
            await self._save()
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
            not self.apt_enabled or not can_try_apt_refresh(row.get("pkg_manager"))
        ):
            raise HomeAssistantError("APT refresh is not enabled for this host")
        self._control_guard(device_id, action)
        if self.maintenance and self.maintenance["enabled"]:
            raise HomeAssistantError("RemotePower global maintenance mode is active")
        if action.startswith("mode_") and row.get("pkg_manager") != "apt":
            raise HomeAssistantError("Upgrade mode only applies to APT hosts")
        if device_id in self._actions:
            raise HomeAssistantError("An action is already running for this host")
        self._actions.add(device_id)
        operation = None
        try:
            if action in ("upgrade", "upgrade_no_cleanup", "reboot", "shutdown"):
                operation = await self._prepare_operation(device_id, action)
            if action == "search_updates":
                await self.client.refresh_apt(device_id)
                result = {"status": "scan_queued"}
            elif action == "scan_packages":
                await self.client.scan_packages(device_id)
                result = {"status": "scan_queued"}
            elif action == "upgrade_no_cleanup":
                result = await self.client.safe_upgrade(device_id, uuid4().hex)
            else:
                result = await self.client.action(device_id, action)
            if operation is not None:
                operation.update(result)
        except RemotePowerError as err:
            if operation is not None:
                operation["status"] = (
                    "failed" if isinstance(err, (RemotePowerAuthError, RemotePowerRejected)) else "unknown"
                )
                operation["finished_at"] = self.now()
            raise HomeAssistantError(str(err)) from err
        finally:
            self._actions.discard(device_id)
            await self._save()
        # Subsequent regular polls pick up the asynchronous agent report.
        await self.async_request_refresh()
        return result
