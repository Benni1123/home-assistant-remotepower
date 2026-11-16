"""Constants for RemotePower."""

DOMAIN = "remotepower"
PLATFORMS = ["sensor", "binary_sensor", "button", "select"]
CONF_VERIFY_SSL = "verify_ssl"
CONF_ENABLE_APT = "enable_apt_refresh"
CONF_ENABLE_CONTROL = "enable_control"
CONF_ALLOW_PROXMOX = "allow_proxmox_control"
CONF_REPAIRS = "enable_repairs"
CONF_UPDATE_REPAIR_THRESHOLD = "update_repair_threshold"
DEFAULT_UPDATE_REPAIR_THRESHOLD = 100
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 60
# Fixed command, never composed from user/host input. No package installation.
# Error-Mode=any prevents partial repository failures from looking successful.
APT_REFRESH_COMMAND = (
    "command -v apt-get >/dev/null 2>&1 || exit 127; "
    "apt-get -o APT::Update::Error-Mode=any update"
)
CONTROL_ACTIONS = {"upgrade", "upgrade_no_cleanup", "reboot", "shutdown", "mode_standard", "mode_extended"}
ACTIONS = ("scan_packages", "search_updates", "scan_acme", "upgrade",
           "upgrade_no_cleanup", "reboot", "shutdown", "mode_standard", "mode_extended")
# Separate opt-in path: no autoremove, cache cleanup or automatic reboot.
APT_SAFE_UPGRADE = (
    "set -e; if command -v update-initramfs >/dev/null; then "
    "test -n \"$(ls -A /lib/modules 2>/dev/null)\" || exit 3; fi; "
    "export DEBIAN_FRONTEND=noninteractive; "
    "apt-get -o APT::Update::Error-Mode=any update; "
    "apt-get -o DPkg::Lock::Timeout=300 "
    "-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "
    "-y upgrade --with-new-pkgs"
)
