import logging
import urllib.parse
from datetime import timedelta
from django.utils import timezone
import requests
from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)


class GoldPanelAdapter(BaseProviderAdapter):
    def __init__(self, provider):
        super().__init__(provider)
        self.api_url = provider.api_endpoint
        self.api_key = provider.get_token()
        self.dns_domain = provider.extra_config.get('dns_domain', '8k.cms-only.ru')
        self.port = provider.extra_config.get('port', 8080)
        timeout = provider.extra_config.get('timeout', 30)
        self.timeout = (timeout / 2, timeout)

    @property
    def capabilities(self) -> set:
        return {'create'}

    def create(self, pack_id: int, months: int, is_lifetime: bool = False, **kwargs) -> dict:
        params = {
            'action': 'new',
            'type': 'm3u',
            'sub': months,
            'pack': pack_id,
            'api_key': self.api_key,
        }

        country = kwargs.get('country')
        if country:
            params['country'] = country

        notes = kwargs.get('notes')
        if notes:
            params['notes'] = notes

        log_params = {k: v for k, v in params.items() if k != 'api_key'}

        try:
            logger.info("Gold Panel create with params: %s", log_params)
            response = requests.get(self.api_url, params=params, timeout=self.timeout)
            logger.info("Gold Panel response: %s %s", response.status_code, response.text[:500])
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as e:
            raise ProviderTimeoutError(f"Gold Panel timeout: {e}")
        except requests.ConnectionError as e:
            raise ProviderTimeoutError(f"Gold Panel connection error: {e}")
        except requests.HTTPError as e:
            raise ProviderAPIError(f"Gold Panel HTTP {response.status_code}: {e}")
        except ValueError as e:
            raise ProviderInvalidResponseError(f"Gold Panel invalid JSON: {e}")

        if isinstance(data, list) and len(data) > 0:
            result = data[0]
        else:
            result = data

        if result.get('status') != 'true':
            error_msg = result.get('message') or 'Unknown provider error'
            raise ProviderAPIError(f"Gold Panel error: {error_msg}")

        user_id = result.get('user_id')
        if not user_id:
            raise ProviderInvalidResponseError("Missing 'user_id' in Gold Panel response")

        full_url = result.get('url', '')
        streaming_username = ''
        password = ''
        if full_url:
            parsed = urllib.parse.urlparse(full_url)
            qs = urllib.parse.parse_qs(parsed.query)
            streaming_username = qs.get('username', [''])[0]
            password = qs.get('password', [''])[0]
        if not password:
            password = user_id
        if not streaming_username:
            streaming_username = user_id

        m3u_url = full_url or f"https://{self.dns_domain}:{self.port}/get.php?username={streaming_username}&password={password}"

        expires_at = None
        if not is_lifetime:
            expires_at = timezone.now() + timedelta(days=30 * (months or 1))

        return {
            'external_id': user_id,
            'credentials': {
                'username': streaming_username,
                'secret_password': password,
                'dns_domain': self.dns_domain,
                'm3u_url': m3u_url,
            },
            'expires_at': expires_at,
            'raw_response': data,
        }
