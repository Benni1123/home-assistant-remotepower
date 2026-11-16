"""UI setup and options."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    RemotePowerAuthError,
    RemotePowerClient,
    RemotePowerConnectionError,
    RemotePowerError,
    normalize_url,
)
from .const import (
    CONF_ENABLE_APT,
    CONF_ENABLE_CONTROL,
    CONF_ALLOW_PROXMOX,
    CONF_REPAIRS,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


class RemotePowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
                client = RemotePowerClient(
                    async_get_clientsession(self.hass),
                    url,
                    user_input[CONF_API_KEY],
                    user_input[CONF_VERIFY_SSL],
                )
                await client.patch_report()
            except ValueError:
                errors["base"] = "invalid_url"
            except RemotePowerAuthError:
                errors["base"] = "invalid_auth"
            except RemotePowerConnectionError:
                errors["base"] = "cannot_connect"
            except RemotePowerError:
                errors["base"] = "invalid_response"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"RemotePower ({urlsplit_host(url)})",
                    data={**user_input, CONF_URL: url},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default="https://10.0.0.109:8443"): str,
                vol.Required(CONF_API_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_VERIFY_SSL, default=True): bool,
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RemotePowerOptionsFlow()

    async def async_step_reconfigure(self, user_input=None):
        return await self._async_connection_edit("reconfigure", self._get_reconfigure_entry(), user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._async_connection_edit("reauth_confirm", self._get_reauth_entry(), user_input)

    async def _async_connection_edit(self, step_id, entry, user_input):
        errors = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
                if any(
                    other.entry_id != entry.entry_id and other.data.get(CONF_URL) == url
                    for other in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")
                key = user_input.get(CONF_API_KEY, "").strip() or entry.data[CONF_API_KEY]
                client = RemotePowerClient(
                    async_get_clientsession(self.hass), url, key, user_input[CONF_VERIFY_SSL]
                )
                await client.patch_report()
                await client.host_details()
                await client.maintenance()
            except ValueError:
                errors["base"] = "invalid_url"
            except RemotePowerAuthError:
                errors["base"] = "invalid_auth"
            except RemotePowerConnectionError:
                errors["base"] = "cannot_connect"
            except RemotePowerError:
                errors["base"] = "invalid_response"
            else:
                options = dict(entry.options)
                options.pop(CONF_VERIFY_SSL, None)
                return self.async_update_reload_and_abort(
                    entry, unique_id=url, title=f"RemotePower ({urlsplit_host(url)})",
                    options=options, data_updates={
                        CONF_URL: url, CONF_API_KEY: key,
                        CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                    },
                )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default=entry.data[CONF_URL]): str,
                vol.Optional(CONF_API_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_VERIFY_SSL, default=entry.options.get(
                    CONF_VERIFY_SSL, entry.data.get(CONF_VERIFY_SSL, True)
                )): bool,
            }),
            errors=errors,
        )


def urlsplit_host(url):
    from urllib.parse import urlsplit
    return urlsplit(url).netloc


class RemotePowerOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_VERIFY_SSL,
                    default=self.config_entry.options.get(
                        CONF_VERIFY_SSL, self.config_entry.data.get(CONF_VERIFY_SSL, True)
                    ),
                ): bool,
                vol.Required(
                    CONF_ENABLE_APT,
                    default=self.config_entry.options.get(CONF_ENABLE_APT, False),
                ): bool,
                vol.Required(
                    CONF_ENABLE_CONTROL,
                    default=self.config_entry.options.get(CONF_ENABLE_CONTROL, False),
                ): bool,
                vol.Required(
                    CONF_ALLOW_PROXMOX,
                    default=self.config_entry.options.get(CONF_ALLOW_PROXMOX, False),
                ): bool,
                vol.Required(
                    CONF_REPAIRS,
                    default=self.config_entry.options.get(CONF_REPAIRS, True),
                ): bool,
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
            }),
        )
