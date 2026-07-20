import logging
import urllib.parse
from datetime import timedelta
from django.utils import timezone
import requests
from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)

SUB_MAP = {
    100: 0,
    101: 0,
    102: 0,
    103: 0,
    1: 1,
    3: 3,
    6: 6,
    12: 12,
    24: 12,
    36: 12,
}

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

class PromaxAdapter(BaseProviderAdapter):
    def __init__(self, provider):
        super().__init__(provider)
        self.api_url = provider.api_endpoint
        raw_key = provider.get_token()
        self.api_key = urllib.parse.unquote(raw_key)
        timeout = provider.extra_config.get('timeout', 30)
        self.timeout = (timeout / 2, timeout)

    @property
    def capabilities(self) -> set:
        return {'create'}

    def create(self, pack_id: int, months: int, is_lifetime: bool = False, **kwargs) -> dict:
        mapped_sub = SUB_MAP.get(months, months)
        params = {
            'action': 'new',
            'type': 'm3u',
            'sub': mapped_sub,
            'pack': int(kwargs.get('template_id', pack_id)),
        }

        if kwargs.get('note'):
            params['notes'] = kwargs['note']
        params['country'] = kwargs.get('country', 'ALL')
        params['adult'] = 1 if kwargs.get('adult') else 0
        params['api_key'] = self.api_key

        log_params = {k: v for k, v in params.items() if k != 'api_key'}

        try:
            logger.info("Promax create with params: %s", log_params)
            response = requests.get(self.api_url, params=params, timeout=self.timeout)
            logger.info("Promax response: %s %s", response.status_code, response.text[:600])
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                data = data[0] if data else {}
        except requests.Timeout as e:
            raise ProviderTimeoutError(f"Promax timeout: {e}")
        except requests.ConnectionError as e:
            raise ProviderTimeoutError(f"Promax connection error: {e}")
        except requests.HTTPError as e:
            raise ProviderAPIError(f"Promax HTTP {response.status_code}: {response.text[:500]}")
        except ValueError as e:
            raise ProviderInvalidResponseError(f"Promax invalid JSON: {e}")

        if str(data.get('status')).lower() != 'true':
            error_msg = data.get('message') or 'Unknown provider error'
            raise ProviderAPIError(f"Promax error: {error_msg}")

        full_url = data.get('url', '')
        streaming_username = data.get('user_id', '')
        password = ''
        if full_url:
            parsed = urllib.parse.urlparse(full_url)
            qs = urllib.parse.parse_qs(parsed.query)
            streaming_username = qs.get('username', [streaming_username])[0]
            password = qs.get('password', [''])[0]

        m3u_url = full_url
        external_id = data.get('user_id', streaming_username)

        expires_at = None
        if not is_lifetime and months in DURATION_MAP:
            expires_at = timezone.now() + DURATION_MAP[months]
        elif not is_lifetime and mapped_sub == 0:
            expires_at = timezone.now() + timedelta(hours=72)

        return {
            'external_id': external_id,
            'credentials': {
                'username': streaming_username,
                'secret_password': password,
                'm3u_url': m3u_url,
                'panel_url': 'https://api.promax-dash.com',
            },
            'expires_at': expires_at,
            'raw_response': data,
        }

    def get_bouquets(self) -> list:
        params = {
            'action': 'bouquet',
            'public': 1,
        }
        params['api_key'] = self.api_key

        log_params = {k: v for k, v in params.items() if k != 'api_key'}
        request_url = f"{self.api_url}?action=bouquet&public=1&api_key=<REDACTED>"

        try:    
            logger.info("Promax fetching bouquets from: %s", request_url)
            response = requests.get(self.api_url, params=params, timeout=self.timeout)
            logger.info("Promax bouquets response: status=%s body=%s", response.status_code, response.text[:600])
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if 'error' in data or 'message' in data:
                    err_msg = data.get('error') or data.get('message') or 'Unknown error'
                    logger.error("Promax bouquets API error: %s", err_msg)
                    raise ProviderAPIError(f"Promax bouquets error: {err_msg}")
                return data.get('data', [])
            return []
        except requests.Timeout as e:
            logger.error("Promax bouquets timeout: %s", e)
            raise ProviderTimeoutError(f"Promax bouquets timeout: {e}")
        except requests.ConnectionError as e:
            logger.error("Promax bouquets connection error: %s", e)
            raise ProviderTimeoutError(f"Promax bouquets connection error: {e}")
        except requests.HTTPError as e:
            logger.error("Promax bouquets HTTP error: %s - %s", e, response.text[:600] if 'response' in dir() else '')
            raise ProviderAPIError(f"Promax bouquets HTTP error: {e}")
        except ValueError as e:
            logger.error("Promax bouquets invalid JSON: %s", e)
            raise ProviderInvalidResponseError(f"Promax bouquets invalid JSON: {e}")
