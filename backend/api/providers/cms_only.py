import logging
import urllib.parse
from datetime import timedelta
from django.utils import timezone

import requests

from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)


class CMSOnlyAdapter(BaseProviderAdapter):
    def __init__(self, provider):
        super().__init__(provider)
        self.api_url = provider.api_endpoint
        self.api_key = provider.get_token()
        self.dns_domain = provider.extra_config.get('dns_domain', 'kmapp.xyz')
        self.port = provider.extra_config.get('port', 8080)
        self.timeout = provider.extra_config.get('timeout', 30)

    @property
    def capabilities(self) -> set:
        return {'create'}

    def create(self, pack_id: int, months: int, is_lifetime: bool = False) -> dict:
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
        streaming_username = ''
        password = ''
        if full_url:
            parsed = urllib.parse.urlparse(full_url)
            qs = urllib.parse.parse_qs(parsed.query)
            streaming_username = qs.get('username', [''])[0]
            password = qs.get('password', [''])[0]
        if not password:
            password = username
        if not streaming_username:
            streaming_username = username

        m3u_url = full_url or f"http://{self.dns_domain}:{self.port}/get.php?username={streaming_username}&password={password}"

        logger.info("Successfully created line: user_id=%s, streaming_username=%s, has_password=%s, has_url=%s",
                     username, streaming_username, bool(password), bool(full_url))

        expires_at = None
        if not is_lifetime:
            expires_at = timezone.now() + timedelta(days=30 * (months or 1))

        return {
            'external_id': username,
            'credentials': {
                'username': streaming_username,
                'secret_password': password,
                'm3u_url': m3u_url,
            },
            'expires_at': expires_at,
            'raw_response': data,
        }
