"""Explicitly requested scans only."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .entity import RemotePowerEntity, discover_hosts


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    discover_hosts(
        coordinator, entry, async_add_entities,
        lambda device_id: [
            RemotePowerScanButton(coordinator, device_id, apt)
            for apt in (False, True)
        ] + [
            RemotePowerActionButton(coordinator, device_id, action)
            for action in ("scan_acme", "upgrade", "reboot", "shutdown")
        ],
    )


class RemotePowerScanButton(RemotePowerEntity, ButtonEntity):
    _attr_icon = "mdi:package-search"

    def __init__(self, coordinator, device_id, apt):
        key = "search_updates" if apt else "scan_packages"
        super().__init__(coordinator, device_id, key)
        self.apt = apt
        self._attr_translation_key = key

    @property
    def available(self):
        return (
            super().available and bool(self.row.get("online"))
            and (not self.apt or (
                self.coordinator.apt_enabled and self.row.get("pkg_manager") == "apt"
            ))
        )

    async def async_press(self):
        await self.coordinator.async_scan(self.device_id, apt=self.apt)


class RemotePowerActionButton(RemotePowerEntity, ButtonEntity):
    def __init__(self, coordinator, device_id, action):
        super().__init__(coordinator, device_id, action)
        self.action = action
        self._attr_translation_key = action
        self._attr_entity_registry_enabled_default = False
        self._attr_icon = {
            "reboot": "mdi:restart", "shutdown": "mdi:power",
            "upgrade": "mdi:package-up", "scan_acme": "mdi:certificate",
        }[action]

    @property
    def available(self):
        return (
            super().available and bool(self.row.get("online"))
            and (self.action == "scan_acme" or self.coordinator.control_enabled)
        )

    async def async_press(self):
        result = await self.coordinator.async_action(self.device_id, self.action)
        if result["status"] == "approval_required":
            raise HomeAssistantError("Action is waiting for approval in RemotePower")
