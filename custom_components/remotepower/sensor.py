"""Update counts and host metadata."""

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity import RemotePowerEntity, discover_hosts

HOST_KEYS = (
    "upgradable", "security_updates", "os", "last_seen", "pkg_manager", "version",
    "last_scan", "last_boot", "operation_status", "last_update_status",
)


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
        elif key in ("last_seen", "last_scan", "last_boot"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif key in ("operation_status", "last_update_status"):
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = (
                ["idle", "submitting", "queued", "approval_required", "awaiting_result",
                 "waiting_for_return", "success", "failed", "unknown", "applied"]
                if key == "operation_status" else ["success", "failed"]
            )

    @property
    def update_history(self):
        local = list(self.coordinator.history.get(self.device_id, []))
        local.append(self.coordinator.operations.get(self.device_id, {}))
        history = list(self.row.get("update_history", []))
        history.extend(
            {key: item.get(key) for key in ("status", "finished_at", "exit_code")}
            for item in local
            if item.get("action") in ("upgrade", "upgrade_no_cleanup")
            and item.get("status") in ("success", "failed")
        )
        return sorted(history, key=lambda item: item.get("finished_at") or 0)[-10:]

    @property
    def native_value(self):
        value = self.row.get(self.key)
        if self.key == "operation_status":
            return self.coordinator.operations.get(self.device_id, {}).get("status", "idle")
        if self.key == "last_update_status":
            history = self.update_history
            return history[-1]["status"] if history else None
        if self.key in ("upgradable", "security_updates"):
            return value if self.row.get("online") and type(value) is int and value >= 0 else None
        if self.key in ("last_seen", "last_scan", "last_boot"):
            return datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) and value > 0 else None
        return value

    @property
    def extra_state_attributes(self):
        if self.key == "upgradable":
            return {
                "packages": self.row.get("upgradable_names", []),
                "kept_back": self.row.get("kept_back", []),
                "kept_back_hint": (
                    "APT kept these packages back; new dependencies, holds or phasing may apply. "
                    "Extended mode can install new dependencies but does not override holds."
                    if self.row.get("kept_back") else None
                ),
                "last_scan": self.row.get("last_scan"),
                "is_proxmox": self.row.get("is_proxmox", False),
            }
        if self.key == "operation_status":
            operation = self.coordinator.operations.get(self.device_id, {})
            return {
                **{key: operation.get(key) for key in (
                    "action", "requested_at", "finished_at", "exit_code", "rescan_status",
                )},
                "history": self.coordinator.history.get(self.device_id, []),
            }
        if self.key == "last_update_status":
            return {"history": self.update_history}
        return None


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
