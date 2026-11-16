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


class Store:
    def __init__(self, *args):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        import copy
        self.data = copy.deepcopy(data)

    async def async_remove(self):
        self.data = None


class Flow:
    def __init_subclass__(cls, **kwargs):
        pass

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_update_reload_and_abort(self, entry, **kwargs):
        self.updates = kwargs
        return {"type": "abort", "reason": "updated"}


class TextSelector:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, value):
        return str(value)


def issue_registry(hass):
    if not hasattr(hass, "issue_registry"):
        hass.issue_registry = SimpleNamespace(issues={})
    return hass.issue_registry


def create_issue(hass, domain, issue_id, **kwargs):
    issue_registry(hass).issues[(domain, issue_id)] = kwargs


def delete_issue(hass, domain, issue_id):
    issue_registry(hass).issues.pop((domain, issue_id), None)


module("homeassistant")
module("homeassistant.components")
module("homeassistant.helpers")
module("homeassistant.exceptions", HomeAssistantError=HAError)
module("homeassistant.config_entries", ConfigEntryAuthFailed=HAError, ConfigFlow=Flow, OptionsFlow=Flow)
module("homeassistant.const", CONF_API_KEY="api_key", CONF_URL="url")
module("homeassistant.core", SupportsResponse=SimpleNamespace(OPTIONAL="optional"), callback=lambda f: f)
module("homeassistant.components.repairs", RepairsFlow=Flow)
module("homeassistant.helpers.storage", Store=Store)
module(
    "homeassistant.helpers.issue_registry", async_get=issue_registry,
    async_create_issue=create_issue, async_delete_issue=delete_issue,
    IssueSeverity=SimpleNamespace(WARNING="warning"),
)
module(
    "homeassistant.helpers.selector", TextSelector=TextSelector,
    TextSelectorConfig=lambda **kwargs: kwargs,
    TextSelectorType=SimpleNamespace(PASSWORD="password"),
)
module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)
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
    SensorDeviceClass=SimpleNamespace(TIMESTAMP="timestamp", ENUM="enum"),
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
