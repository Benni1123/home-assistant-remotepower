"""Constants for RemotePower."""

DOMAIN = "remotepower"
PLATFORMS = ["sensor", "binary_sensor", "button", "select"]
CONF_VERIFY_SSL = "verify_ssl"
CONF_ENABLE_APT = "enable_apt_refresh"
CONF_ENABLE_CONTROL = "enable_control"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 60
# Fixed command, never composed from user/host input. No package installation.
# Error-Mode=any prevents partial repository failures from looking successful.
APT_REFRESH_COMMAND = "apt-get -o APT::Update::Error-Mode=any update"
CONTROL_ACTIONS = {"upgrade", "reboot", "shutdown", "mode_standard", "mode_extended"}
ACTIONS = ("scan_packages", "search_updates", "scan_acme", "upgrade",
           "reboot", "shutdown", "mode_standard", "mode_extended")
