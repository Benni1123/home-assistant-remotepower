"""Optional package-management and confirmed-reboot repair dialogs."""

import re
import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .models import can_try_apt_refresh


async def async_create_fix_flow(hass, issue_id, data):
    if (data or {}).get("kind") == "updates":
        return RemotePowerUpdateRepair(data)
    return RemotePowerRebootRepair(data or {})


class RemotePowerUpdateRepair(RepairsFlow):
    """Never install or mark a queued request as fixed merely by opening a dialog."""

    def __init__(self, data):
        super().__init__()
        self._issue_data = data

    def _host(self):
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._issue_data.get("entry_id"))
        device_id = self._issue_data.get("device_id")
        if coordinator is None or device_id not in (coordinator.data or {}):
            return None, {}, "host_unavailable"
        if (
            not coordinator.update_repair_actions or not coordinator.repairs_enabled
            or coordinator.update_repair_threshold <= 0
        ):
            return None, {}, "management_disabled"
        return coordinator, coordinator.data[device_id], None

    def _placeholders(self, row):
        # Package names are display-only; never interpolate them into a command.
        packages = row.get("upgradable_names") or []
        shown = [
            re.sub(r"[^a-zA-Z0-9.+:~_@/-]", "?", name)[:128]
            for name in packages[:100] if isinstance(name, str)
        ]
        return {
            "host": str(row.get("name", self._issue_data.get("device_id")))[:128],
            "count": str(row.get("upgradable")) if type(row.get("upgradable")) is int else "?",
            "packages": "\n".join(f"- `{name}`" for name in shown) or "—",
            "shown": str(len(shown)),
        }

    async def async_step_init(self, user_input=None):
        coordinator, row, error = self._host()
        if error:
            return self.async_abort(reason=error)
        count = row.get("upgradable")
        if (
            coordinator.last_update_success and row.get("online")
            and type(count) is int and 0 <= count < coordinator.update_repair_threshold
        ):
            return self.async_create_entry(data={})
        choices = ["scan_packages"]
        if coordinator.apt_enabled and can_try_apt_refresh(row.get("pkg_manager")):
            choices.append("search_updates")
        choices.append("install")
        return self.async_show_menu(
            step_id="init", menu_options=choices,
            description_placeholders=self._placeholders(row),
        )

    async def _async_scan(self, action):
        coordinator, row, error = self._host()
        if error:
            return self.async_abort(reason=error)
        try:
            await coordinator.async_action(self._issue_data["device_id"], action)
        except HomeAssistantError:
            return self.async_abort(reason="action_unconfirmed")
        return self.async_abort(reason="scan_queued")

    async def async_step_scan_packages(self, user_input=None):
        return await self._async_scan("scan_packages")

    async def async_step_search_updates(self, user_input=None):
        return await self._async_scan("search_updates")

    async def async_step_install(self, user_input=None):
        coordinator, row, error = self._host()
        if error:
            return self.async_abort(reason=error)
        errors = {}
        if user_input is not None:
            if not user_input.get("confirm_install"):
                errors["base"] = "confirmation_required"
            else:
                # Reuse the native protection logic; do not allow user-supplied
                # package names or shell commands from a repair dialog.
                action = "upgrade_no_cleanup" if row.get("is_proxmox") else "upgrade"
                try:
                    result = await coordinator.async_action(self._issue_data["device_id"], action)
                except HomeAssistantError:
                    errors["base"] = "install_blocked"
                else:
                    return self.async_abort(reason=(
                        "approval_required" if result["status"] == "approval_required"
                        else "upgrade_queued"
                    ))
        return self.async_show_form(
            step_id="install",
            data_schema=vol.Schema({vol.Required("confirm_install", default=False): bool}),
            description_placeholders=self._placeholders(row),
            errors=errors,
        )


class RemotePowerRebootRepair(RepairsFlow):
    def __init__(self, data):
        super().__init__()
        self._issue_data = data

    async def async_step_init(self, user_input=None):
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._issue_data.get("entry_id"))
        device_id = self._issue_data.get("device_id")
        if coordinator is None or device_id not in (coordinator.data or {}):
            return self.async_abort(reason="host_unavailable")
        row = coordinator.data[device_id]
        if row.get("online") and not row.get("reboot_required"):
            return self.async_create_entry(data={})
        errors = {}
        if user_input is not None:
            if not user_input.get("confirm_reboot"):
                errors["base"] = "confirmation_required"
            else:
                try:
                    result = await coordinator.async_action(device_id, "reboot")
                except HomeAssistantError:
                    errors["base"] = "reboot_blocked"
                else:
                    # ABORT closes the dialog WITHOUT deleting the repair.
                    # The normal report removes it when reboot_required clears.
                    return self.async_abort(reason=(
                        "approval_required" if result["status"] == "approval_required"
                        else "reboot_queued"
                    ))
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Required("confirm_reboot", default=False): bool}),
            description_placeholders={"host": str(row.get("name", device_id))[:128]},
            errors=errors,
        )
