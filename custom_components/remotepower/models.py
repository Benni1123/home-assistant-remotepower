"""Pure projection and tracking helpers. Never retain raw commands or journal data."""

import hashlib
import math
import time


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def can_try_apt_refresh(manager):
    """Unknown metadata must not require a preliminary scan; check APT at runtime."""
    return manager in (None, "", "unknown", "apt")


def names(value, limit=300):
    return [item[:128] for item in value[:limit] if isinstance(item, str)] if isinstance(value, list) else []


def command_kind(command):
    if not isinstance(command, str):
        return "other"
    if ": ha-rp:" in command[:100]:
        return "upgrade_no_cleanup"
    if command in ("reboot", "shutdown", "upgrade"):
        return command
    if command.startswith("exec:") and (
        "KV=$(uname -r)" in command[:100]
        or any(word in command for word in (
            "apt-get -y upgrade", "apt-get $ALT -y upgrade", "dnf upgrade",
            "yum -y update", "pacman -Syu",
        ))
    ):
        return "upgrade"
    return "other"


def project_output(row):
    command = row.get("cmd", "")
    return {
        "kind": command_kind(command),
        "ts": number(row.get("ts")),
        "rc": row.get("rc") if type(row.get("rc")) is int else None,
        "fingerprint": hashlib.sha256(str(command).encode()).hexdigest(),
    }


def project_host(row):
    si = row.get("sysinfo") if isinstance(row.get("sysinfo"), dict) else {}
    pkg = si.get("packages") if isinstance(si.get("packages"), dict) else {}
    pending = names(pkg.get("upgradable_names"))
    tags = names(row.get("tags"))
    hw = row.get("hw_health") if isinstance(row.get("hw_health"), dict) else {}
    return {
        "version": row.get("version"),
        "site": row.get("site"),
        "tags": tags,
        "last_scan": number(si.get("pkg_scan_ts")),
        "last_boot": number(si.get("last_boot")),
        "upgradable_names": pending,
        "kept_back": names(pkg.get("kept_back"), 50),
        "kernel_reboot_required": (
            hw.get("kernel_reboot") if type(hw.get("kernel_reboot")) is bool else None
        ),
        "is_proxmox": (
            "proxmox-host" in tags
            or str(row.get("group", "")).lower() in ("proxmoxhost", "proxmox-host")
            or "proxmox" in str(row.get("os", "")).lower()
            or any(name.startswith(("proxmox-kernel", "proxmox-ve", "pve-manager"))
                   for name in pending)
        ),
    }


def maintenance_for(device_id, row, maintenance):
    """Active smart scopes cannot be evaluated locally: conservatively exclude."""
    if maintenance is None:
        return True
    if maintenance["enabled"]:
        return True
    for window in maintenance["windows"]:
        if not window["active"]:
            continue
        scope, target = window.get("scope"), window.get("target")
        if (
            scope in ("global", "smart")
            or (scope == "device" and target == device_id)
            or (scope == "group" and target and target == row.get("group"))
            or (scope == "site" and target and target == row.get("site"))
            or (scope == "tag" and target and target in row.get("tags", []))
        ):
            return True
        if scope not in ("global", "smart", "device", "group", "site", "tag"):
            return True
    return False


TERMINAL = {"success", "failed", "unknown", "applied"}


def start_operation(action, row, outputs, now=None):
    return {
        "action": action, "status": "submitting",
        "requested_at": now if now is not None else time.time(),
        "baseline_boot": row.get("last_boot"), "baseline_scan": row.get("last_scan"),
        "baseline_outputs": [
            [item.get("ts"), item.get("fingerprint"), item.get("rc")] for item in outputs
        ],
        "history": [],
    }


def update_operation(operation, row, outputs, queued_kinds=None, now=None):
    """Use evidence, not a reduced update count, to decide command success."""
    now = time.time() if now is None else now
    action, status = operation["action"], operation["status"]
    if status in TERMINAL:
        return
    if action == "reboot":
        boot, baseline = number(row.get("last_boot")), number(operation.get("baseline_boot"))
        if (
            row.get("online") and boot and baseline is not None
            and boot > baseline + 5
            and (number(row.get("last_seen")) or 0) >= operation["requested_at"]
        ):
            operation["status"] = "success"
            operation["finished_at"] = now
        elif not row.get("online"):
            operation["status"] = "waiting_for_return"
    elif action in ("upgrade", "upgrade_no_cleanup"):
        candidates = [
            item for item in outputs
            if item["kind"] == action
            and item.get("ts") is not None
            and item["ts"] >= operation["requested_at"]
            and [item["ts"], item["fingerprint"], item["rc"]] not in operation["baseline_outputs"]
            and (not operation.get("fingerprint")
                 or item["fingerprint"] == operation["fingerprint"])
        ]
        # No native per-command ID: concurrent, indistinguishable results are ambiguous.
        if len(candidates) > 1:
            operation["status"] = "unknown"
        elif candidates:
            result = candidates[0]
            if result["rc"] is not None:
                operation["status"] = "success" if result["rc"] == 0 else "failed"
                operation["exit_code"] = result["rc"]
                operation["finished_at"] = result["ts"]
                operation["rescan_due"] = result["rc"] == 0
    if operation["status"] not in TERMINAL and queued_kinds is not None:
        if action in queued_kinds:
            operation["status"] = "queued"
        elif status != "approval_required" and action != "reboot":
            operation["status"] = "awaiting_result"
    if now - operation["requested_at"] > 7200 and operation["status"] not in TERMINAL:
        operation["status"] = "unknown"
