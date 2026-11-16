"""Allowlisted diagnostics: no keys, URLs, names, IPs, commands or raw outputs."""

from .const import (
    CONF_ALLOW_PROXMOX, CONF_ENABLE_APT, CONF_ENABLE_CONTROL,
    CONF_REPAIRS, CONF_SCAN_INTERVAL, CONF_VERIFY_SSL, DOMAIN,
    CONF_UPDATE_REPAIR_THRESHOLD,
)


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = coordinator.data if coordinator and coordinator.data else {}
    hosts = []
    for index, (device_id, row) in enumerate(data.items(), 1):
        host = {"host": index}
        host.update({key: row.get(key) for key in (
            "online", "upgradable", "security_updates", "pkg_manager",
            "reboot_required", "last_scan", "last_boot", "is_proxmox", "maintenance",
        )})
        operation = coordinator.operations.get(device_id, {})
        host["operation"] = {key: operation.get(key) for key in (
            "action", "status", "requested_at", "finished_at", "exit_code", "rescan_status",
        )}
        hosts.append(host)
    return {
        "options": {key: entry.options.get(key, entry.data.get(key)) for key in (
            CONF_VERIFY_SSL, CONF_ENABLE_APT, CONF_ENABLE_CONTROL, CONF_ALLOW_PROXMOX,
            CONF_REPAIRS, CONF_SCAN_INTERVAL,
            CONF_UPDATE_REPAIR_THRESHOLD,
        )},
        "last_update_success": coordinator.last_update_success if coordinator else False,
        "hosts": hosts,
    }
