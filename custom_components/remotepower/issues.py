"""Repair issues are observations, never automatic remediation."""

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def clear_issues(hass, entry_id):
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and issue_id.startswith(f"{entry_id}_"):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def sync_issues(hass, coordinator, rows):
    prefix = coordinator.entry.entry_id
    expected = set()
    if coordinator.repairs_enabled:
        for device_id, row in rows.items():
            updates_id = f"{prefix}_{device_id}_updates"
            count = row.get("upgradable")
            threshold = coordinator.update_repair_threshold
            if threshold > 0:
                if not row.get("online") or type(count) is not int or count < 0:
                    # Unknown/offline is not "zero updates". Keep an existing
                    # issue, but do not create a new one from stale counts.
                    expected.add(updates_id)
                elif count >= threshold:
                    expected.add(updates_id)
                    ir.async_create_issue(
                        hass, DOMAIN, updates_id,
                        is_fixable=coordinator.update_repair_actions, is_persistent=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="package_updates",
                        translation_placeholders={
                            "host": str(row.get("name", device_id))[:128],
                            "count": str(count), "threshold": str(threshold),
                        },
                        learn_more_url=coordinator.client.url,
                        data={"entry_id": prefix, "device_id": device_id, "kind": "updates"},
                    )
            issue_id = f"{prefix}_{device_id}_reboot"
            # Retain a pending-reboot issue while the host is offline. Silence
            # isn't evidence of a successful reboot.
            if row.get("reboot_required") or not row.get("online"):
                expected.add(issue_id)
            if row.get("reboot_required"):
                ir.async_create_issue(
                    hass, DOMAIN, issue_id,
                    is_fixable=True, is_persistent=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="reboot_required",
                    translation_placeholders={"host": str(row.get("name", device_id))[:128]},
                    data={"entry_id": prefix, "device_id": device_id},
                )
            operation = coordinator.operations.get(device_id, {})
            if operation.get("status") == "failed":
                failed_id = f"{prefix}_{device_id}_action"
                expected.add(failed_id)
                ir.async_create_issue(
                    hass, DOMAIN, failed_id,
                    is_fixable=False, is_persistent=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="action_failed",
                    translation_placeholders={"host": str(row.get("name", device_id))[:128]},
                )
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and issue_id.startswith(f"{prefix}_") and issue_id not in expected:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
