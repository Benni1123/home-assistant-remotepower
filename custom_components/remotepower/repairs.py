"""Confirmed reboot from the HA Repairs UI, using existing action safeguards."""

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


async def async_create_fix_flow(hass, issue_id, data):
    return RemotePowerRebootRepair(data or {})


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
