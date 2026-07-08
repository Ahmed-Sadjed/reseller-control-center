import logging
import uuid
import requests
from django.utils import timezone
from datetime import timedelta

from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)


class HotPlayerAdapter(BaseProviderAdapter):
    def __init__(self, provider):
        super().__init__(provider)
        self.api_url = provider.api_endpoint
        self.api_key = provider.get_token()
        self.mac_prefix = provider.extra_config.get('mac_prefix', '00:1A:79')
        self.timeout = provider.extra_config.get('timeout', 30)

    @property
    def api_root(self):
        return self.api_url.replace('/activate', '').rstrip('/')

    def _request(self, method, path, **kwargs):
        headers = kwargs.pop('headers', {})
        headers.setdefault("ApiKey", self.api_key)
        if method in ('POST', 'PUT', 'PATCH'):
            headers.setdefault("Content-Type", "application/json")

        url = f"{self.api_root}{path}"
        try:
            logger.info("HotPlayer %s %s", method.upper(), path)
            response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as e:
            logger.error("HotPlayer timeout: %s", e)
            raise ProviderTimeoutError(f"Provider request timed out: {e}")
        except requests.ConnectionError as e:
            logger.error("HotPlayer connection error: %s", e)
            raise ProviderTimeoutError(f"Connection error: {e}")
        except requests.HTTPError as e:
            logger.error("HotPlayer HTTP %s: %s", response.status_code, response.text[:300])
            raise ProviderAPIError(f"Provider returned HTTP {response.status_code}: {e}")
        except ValueError as e:
            logger.error("HotPlayer invalid JSON: %s", response.text[:300])
            raise ProviderInvalidResponseError(f"Invalid JSON response: {e}")

        if isinstance(data, dict) and data.get('status') == 'error':
            error_msg = data.get('message') or 'Unknown provider error'
            logger.error("HotPlayer returned error: %s", error_msg)
            raise ProviderAPIError(f"Provider error: {error_msg}")

        return data

    def generate_mac(self):
        # Generate random MAC matching the prefix
        suffix = ":".join([f"{uuid.uuid4().hex[:2].upper()}" for _ in range(3)])
        return f"{self.mac_prefix}:{suffix}"

    def create_line(self, pack_id: int, months: int, is_lifetime: bool = False) -> dict:
        mac = self.generate_mac()

        if is_lifetime:
            duration_val = "FOREVER"
        elif months == 12:
            duration_val = "YEAR_1"
        else:
            duration_val = f"MONTHS_{months}"

        payload = {
            "mac": mac,
            "pack_id": pack_id,
            "duration": duration_val
        }

        logger.info("Calling HotPlayer API with mac=%s, duration=%s", mac, duration_val)
        data = self._request('POST', '/activate', json=payload)

        expires_at = None
        if not is_lifetime:
            expires_at = timezone.now() + timedelta(days=30 * (months or 1))
            
        dns_domain = self.provider.extra_config.get("dns_domain", "hotplayer.net")

        return {
            'user_id': mac,
            'streaming_username': mac,
            'password': '',
            'dns_domain': dns_domain,
            'm3u_url': '',  # MAC devices usually don't use M3U URLs
            'expires_at': expires_at,
            'raw_response': data,
        }

    def activate_device(self, mac: str, pack_id: int, duration: str, extend: bool = False) -> dict:
        payload = {
            "mac": mac,
            "pack_id": pack_id,
            "duration": duration,
            "extend": extend,
        }
        logger.info("HotPlayer activate: mac=%s, pack_id=%s, duration=%s, extend=%s", mac, pack_id, duration, extend)
        data = self._request('POST', '/activate', json=payload)
        return data

    def check_device(self, mac: str) -> dict:
        logger.info("HotPlayer check_device: mac=%s", mac)
        return self._request('GET', f'/check-device/{mac}')

    def add_playlists(self, mac: str, playlists: list) -> dict:
        logger.info("HotPlayer add_playlists: mac=%s, count=%s", mac, len(playlists))
        return self._request('POST', f'/add-playlists/{mac}', json={"playlists": playlists})

    def delete_playlists(self, mac: str) -> dict:
        logger.info("HotPlayer delete_playlists: mac=%s", mac)
        return self._request('DELETE', f'/delete-playlists/{mac}')
