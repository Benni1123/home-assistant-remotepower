"""Shared host entities and dynamic discovery."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


def discover_hosts(coordinator, entry, async_add_entities, factory):
    """Discover new hosts on every report; do not delete unavailable hosts."""
    known = set()

    def discover():
        entities = []
        for device_id in coordinator.data or {}:
            if device_id not in known:
                known.add(device_id)
                entities.extend(factory(device_id))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(discover))
    discover()


class RemotePowerEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, device_id, key):
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_id}_{key}"

    @property
    def row(self):
        return self.coordinator.data.get(self.device_id, {})

    @property
    def available(self):
        return super().available and self.device_id in self.coordinator.data

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.entry.entry_id}_{self.device_id}")},
            name=self.row.get("name") or self.device_id,
            manufacturer="RemotePower",
            model=self.row.get("os") or "Managed host",
            sw_version=self.row.get("version"),
            configuration_url=self.coordinator.client.url,
        )
