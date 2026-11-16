"""RemotePower integration."""

from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RemotePowerClient
from .const import CONF_VERIFY_SSL, PLATFORMS
from .coordinator import RemotePowerCoordinator
from .services import async_register_services


async def async_setup_entry(hass, entry):
    client = RemotePowerClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_API_KEY],
        entry.options.get(CONF_VERIFY_SSL, entry.data.get(CONF_VERIFY_SSL, True)),
    )
    coordinator = RemotePowerCoordinator(hass, entry, client)
    await coordinator.async_restore()
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault("remotepower", {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        from .issues import clear_issues
        clear_issues(hass, entry.entry_id)
        hass.data["remotepower"].pop(entry.entry_id)
        if not hass.data["remotepower"]:
            hass.services.async_remove("remotepower", "bulk_action")
        return True
    return False


async def async_remove_entry(hass, entry):
    from homeassistant.helpers.storage import Store
    from .issues import clear_issues
    clear_issues(hass, entry.entry_id)
    await Store(hass, 1, f"remotepower.{entry.entry_id}.operations").async_remove()
