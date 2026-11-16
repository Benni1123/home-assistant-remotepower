"""Minimal HA test doubles; never pretend these are a full HA runtime."""

import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


def module(name, **attrs):
    result = ModuleType(name)
    result.__dict__.update(attrs)
    sys.modules[name] = result
    return result


package = module("rp_test")
package.__path__ = [
    str(Path(__file__).resolve().parents[1] / "custom_components" / "remotepower")
]


class HAError(Exception):
    pass


class Entity:
    pass


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


class DataUpdateCoordinator:
    def __init__(self, hass, *args, **kwargs):
        self.hass = hass
        self.data = {}
        self.last_update_success = True
        self.listeners = []

    def async_add_listener(self, listener):
        self.listeners.append(listener)
        return lambda: None

    async def async_request_refresh(self):
        pass


module("homeassistant")
module("homeassistant.components")
module("homeassistant.helpers")
module("homeassistant.exceptions", HomeAssistantError=HAError)
module("homeassistant.config_entries", ConfigEntryAuthFailed=HAError)
module("homeassistant.core", SupportsResponse=SimpleNamespace(OPTIONAL="optional"))
module(
    "homeassistant.helpers.update_coordinator",
    CoordinatorEntity=CoordinatorEntity,
    DataUpdateCoordinator=DataUpdateCoordinator,
    UpdateFailed=HAError,
)
module("homeassistant.helpers.device_registry", DeviceInfo=lambda **kw: kw)
module(
    "homeassistant.components.sensor",
    SensorEntity=Entity,
    SensorDeviceClass=SimpleNamespace(TIMESTAMP="timestamp"),
    SensorStateClass=SimpleNamespace(MEASUREMENT="measurement"),
)
module(
    "homeassistant.components.binary_sensor",
    BinarySensorEntity=Entity,
    BinarySensorDeviceClass=SimpleNamespace(CONNECTIVITY="connectivity", PROBLEM="problem"),
)
module("homeassistant.components.button", ButtonEntity=Entity)
module("homeassistant.components.select", SelectEntity=Entity)


def load(name):
    return importlib.import_module(f"rp_test.{name}")
