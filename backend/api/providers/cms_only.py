import logging
import urllib.parse

import requests
from django.conf import settings

from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)


class CMSOnlyAdapter(BaseProviderAdapter):
    def __init__(self, api_url=None, api_key=None, dns_domain=None, timeout=30):
        self.api_url = api_url or settings.IPTV_API_URL
        self.api_key = api_key or settings.IPTV_API_KEY
        self.dns_domain = dns_domain or settings.IPTV_DNS
        self.timeout = timeout

    def create_line(self, pack_id, months):
        params = {
            'action': 'new',
            'type': 'm3u',
            'sub': months,
            'pack': pack_id,
            'api_key': self.api_key,
        }
        log_params = {k: v for k, v in params.items() if k != 'api_key'}

        try:
            logger.info("Calling provider API with params: %s", log_params)
            response = requests.get(
                self.api_url,
                params=params,
                timeout=self.timeout,
            )
            logger.info("Provider response status: %s, body: %s", response.status_code, response.text[:500])
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as e:
            logger.error("Provider timeout: %s", e)
            raise ProviderTimeoutError(f"Provider request timed out: {e}")
        except requests.ConnectionError as e:
            logger.error("Provider connection error: %s", e)
            raise ProviderTimeoutError(f"Connection error: {e}")
        except requests.HTTPError as e:
            logger.error("Provider HTTP %s: %s", response.status_code, response.text[:300])
            raise ProviderAPIError(f"Provider returned HTTP {response.status_code}: {e}")
        except ValueError as e:
            logger.error("Provider invalid JSON: %s", response.text[:300])
            raise ProviderInvalidResponseError(f"Invalid JSON response: {e}")

        if data.get('status') == 'error':
            error_msg = data.get('message') or data.get('result') or 'Unknown provider error'
            logger.error("Provider returned error: %s", error_msg)
            raise ProviderAPIError(f"Provider error: {error_msg}")

        username = data.get('user_id')
        if not username:
            logger.error("Provider response missing user_id: %s", data)
            raise ProviderInvalidResponseError("Missing 'user_id' in provider response")

        full_url = data.get('url', '')
        password = ''
        if full_url:
            parsed = urllib.parse.urlparse(full_url)
            qs = urllib.parse.parse_qs(parsed.query)
            password = qs.get('password', [''])[0]
        if not password:
            password = username

        logger.info("Successfully created line: username=%s, has_password=%s, has_url=%s",
                     username, bool(password), bool(full_url))

        return {
            'username': username,
            'password': password,
            'dns_domain': full_url,
            'raw_response': data,
        }
