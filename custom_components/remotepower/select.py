"""Native APT upgrade-mode selection."""

from homeassistant.components.select import SelectEntity

from .const import DOMAIN
from .entity import RemotePowerEntity, discover_hosts


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    discover_hosts(
        coordinator, entry, async_add_entities,
        lambda device_id: [RemotePowerUpgradeMode(coordinator, device_id)],
    )


class RemotePowerUpgradeMode(RemotePowerEntity, SelectEntity):
    _attr_options = ["standard", "extended"]
    _attr_translation_key = "upgrade_mode"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id, "upgrade_mode")

    @property
    def available(self):
        return (
            super().available and self.row.get("pkg_manager") == "apt"
            and self.coordinator.control_enabled
        )

    @property
    def current_option(self):
        value = self.row.get("upgrade_mode")
        return value if value in self._attr_options else None

    async def async_select_option(self, option):
        await self.coordinator.async_action(self.device_id, f"mode_{option}")
