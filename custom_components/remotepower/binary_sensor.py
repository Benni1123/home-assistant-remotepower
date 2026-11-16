"""Host availability and pending reboot."""

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass

from .const import DOMAIN
from .entity import RemotePowerEntity, discover_hosts


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    discover_hosts(
        coordinator, entry, async_add_entities,
        lambda device_id: [
            RemotePowerBinarySensor(coordinator, device_id, key)
            for key in ("online", "reboot_required", "maintenance", "is_proxmox")
        ],
    )


class RemotePowerBinarySensor(RemotePowerEntity, BinarySensorEntity):
    def __init__(self, coordinator, device_id, key):
        super().__init__(coordinator, device_id, key)
        self.key = key
        self._attr_translation_key = key
        self._attr_device_class = (
            BinarySensorDeviceClass.CONNECTIVITY if key == "online"
            else BinarySensorDeviceClass.PROBLEM if key == "reboot_required" else None
        )

    @property
    def is_on(self):
        if self.key != "online" and not self.row.get("online"):
            return None
        return self.row.get(self.key)

    @property
    def extra_state_attributes(self):
        if self.key == "reboot_required":
            return {key: self.row.get(key) for key in (
                "reboot_sources", "running_kernel", "installed_kernel",
            )}
        return None
