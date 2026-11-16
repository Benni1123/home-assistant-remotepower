"""Update counts and host metadata."""

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity import RemotePowerEntity, discover_hosts

HOST_KEYS = ("upgradable", "security_updates", "os", "last_seen", "pkg_manager", "version")


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        RemotePowerFleetSensor(coordinator, key)
        for key in ("hosts_online", "total_updates", "hosts_without_data")
    ])
    discover_hosts(
        coordinator, entry, async_add_entities,
        lambda device_id: [
            RemotePowerSensor(coordinator, device_id, key) for key in HOST_KEYS
        ],
    )


class RemotePowerSensor(RemotePowerEntity, SensorEntity):
    def __init__(self, coordinator, device_id, key):
        super().__init__(coordinator, device_id, key)
        self.key = key
        self._attr_translation_key = key
        if key in ("upgradable", "security_updates"):
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:package-up"
        elif key == "last_seen":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        value = self.row.get(self.key)
        if self.key in ("upgradable", "security_updates"):
            return value if self.row.get("online") and type(value) is int and value >= 0 else None
        if self.key == "last_seen":
            return datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) and value > 0 else None
        return value


class RemotePowerFleetSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self.key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="RemotePower",
            manufacturer="RemotePower",
            model="Fleet",
            configuration_url=coordinator.client.url,
        )

    @property
    def native_value(self):
        rows = list((self.coordinator.data or {}).values())
        known = [
            row for row in rows
            if row.get("online") and type(row.get("upgradable")) is int
            and row["upgradable"] >= 0
        ]
        if self.key == "hosts_online":
            return sum(bool(row.get("online")) for row in rows)
        if self.key == "hosts_without_data":
            return len(rows) - len(known)
        # Never report "0 updates" while any host has unknown/stale data.
        return sum(row["upgradable"] for row in known) if len(known) == len(rows) else None
