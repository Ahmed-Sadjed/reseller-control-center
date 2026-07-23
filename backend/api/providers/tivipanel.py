import logging
import requests
from datetime import timedelta
from django.utils import timezone
from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)

DURATION_MAP = {
    100: timedelta(hours=6),
    101: timedelta(hours=12),
    102: timedelta(hours=24),
    103: timedelta(hours=72),
    1: timedelta(days=30),
    3: timedelta(days=90),
    6: timedelta(days=180),
    12: timedelta(days=365),
    24: timedelta(days=730),
    36: timedelta(days=1095),
}

class TiviPanelAdapter(BaseProviderAdapter):
    def __init__(self, provider):
        super().__init__(provider)
        self.api_url = provider.api_endpoint
        self.api_key = provider.get_token()
        self.dns_domain = provider.extra_config.get('dns_domain', 'tivipanel.net')
        self.port = provider.extra_config.get('port', 8080)
        timeout = provider.extra_config.get('timeout', 30)
        self.timeout = (timeout / 2, timeout)

    @property
    def capabilities(self) -> set:
        return {'create'}

    def create(self, pack_id: int, months: int, is_lifetime: bool = False, **kwargs) -> dict:
        if is_lifetime:
            raise ValueError("TiviPanel does not support lifetime subscriptions")

        package = pack_id

        params = {
            'action': 'new',
            'type': 'm3u',
            'package': package,
            'api_key': self.api_key,
        }

        if kwargs.get('template'):
            params['template'] = kwargs['template']
        if kwargs.get('notes'):
            params['notes'] = kwargs['notes']
        params['country'] = kwargs.get('country', 'ALL')

        log_params = {k: v for k, v in params.items() if k != 'api_key'}

        try:
            logger.info("TiviPanel create with params: %s", log_params)
            response = requests.get(self.api_url, params=params, timeout=self.timeout)
            logger.info("TiviPanel response: %s %s", response.status_code, response.text[:500])
            data = response.json()
            if isinstance(data, list):
                data = data[0] if data else {}
        except requests.Timeout as e:
            raise ProviderTimeoutError(f"TiviPanel timeout: {e}")
        except requests.ConnectionError as e:
            raise ProviderTimeoutError(f"TiviPanel connection error: {e}")
        except ValueError as e:
            raise ProviderInvalidResponseError(f"TiviPanel invalid JSON: {e}")

        if str(data.get('status')).lower() != 'true':
            error_msg = data.get('message') or 'Unknown provider error'
            raise ProviderAPIError(f"TiviPanel error: {error_msg}")

        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            raise ProviderInvalidResponseError("Missing username/password in TiviPanel response")

        m3u_url = f"https://{self.dns_domain}:{self.port}/get.php?username={username}&password={password}"

        expires_at = None
        if months in DURATION_MAP:
            expires_at = timezone.now() + DURATION_MAP[months]
        elif months == 24:
            expires_at = timezone.now() + timedelta(days=730)
        elif months == 36:
            expires_at = timezone.now() + timedelta(days=1095)

        return {
            'external_id': username,
            'credentials': {
                'username': username,
                'secret_password': password,
                'dns_domain': self.dns_domain,
                'm3u_url': m3u_url,
            },
            'expires_at': expires_at,
            'raw_response': data,
        }
