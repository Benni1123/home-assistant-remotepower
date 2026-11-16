"""Explicitly targeted bulk actions with per-host results."""

import voluptuous as vol

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .const import ACTIONS, CONTROL_ACTIONS, DOMAIN

SCHEMA = vol.Schema({
    vol.Required("entry_id"): str,
    vol.Required("action"): vol.In(ACTIONS),
    vol.Optional("host_ids"): [str],
    vol.Optional("group"): str,
    vol.Optional("all_monitored", default=False): bool,
    vol.Optional("confirm", default=False): bool,
})


def async_register_services(hass):
    if hass.services.has_service(DOMAIN, "bulk_action"):
        return

    async def bulk_action(call):
        coordinator = hass.data.get(DOMAIN, {}).get(call.data["entry_id"])
        if coordinator is None:
            raise HomeAssistantError("Unknown or unloaded RemotePower entry")
        if not coordinator.last_update_success:
            raise HomeAssistantError("RemotePower data is unavailable")
        ids = call.data.get("host_ids", [])
        group = call.data.get("group", "")
        all_monitored = call.data["all_monitored"]
        if sum((bool(ids), bool(group), all_monitored)) != 1:
            raise HomeAssistantError("Choose exactly one: host_ids, group, all_monitored")
        action = call.data["action"]
        if action in CONTROL_ACTIONS and not call.data["confirm"]:
            raise HomeAssistantError("Control actions require confirm: true")
        rows = coordinator.data or {}
        if group:
            ids = [key for key, row in rows.items() if row.get("group") == group]
        elif all_monitored:
            ids = [key for key, row in rows.items() if row.get("monitored") is not False]
        ids = list(dict.fromkeys(ids))
        if not ids or any(key not in rows for key in ids):
            raise HomeAssistantError("Selection is empty or contains unknown hosts")
        if action in ("upgrade", "reboot", "shutdown"):
            return {"results": await coordinator.async_bulk_control(ids, action)}
        results = {}
        for device_id in ids:
            try:
                results[device_id] = await coordinator.async_action(device_id, action)
            except HomeAssistantError as err:
                results[device_id] = {"status": "failed", "error": str(err)}
        return {"results": results}

    hass.services.async_register(
        DOMAIN, "bulk_action", bulk_action, schema=SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
