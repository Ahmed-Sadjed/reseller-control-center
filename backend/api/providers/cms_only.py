import requests
from django.conf import settings
from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError


class CMSOnlyAdapter(BaseProviderAdapter):
    def __init__(self, api_url=None, api_key=None, dns_domain=None, timeout=30):
        self.api_url = api_url or settings.IPTV_API_URL
        self.api_key = api_key or settings.IPTV_API_KEY
        self.dns_domain = dns_domain or settings.IPTV_DNS
        self.timeout = timeout

    def create_line(self, pack_id, months):
        try:
            response = requests.get(
                self.api_url,
                params={
                    'action': 'new',
                    'type': 'm3u',
                    'sub': months,
                    'pack': pack_id,
                    'api_key': self.api_key,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as e:
            raise ProviderTimeoutError(f"Provider request timed out: {e}")
        except requests.ConnectionError as e:
            raise ProviderTimeoutError(f"Connection error: {e}")
        except requests.HTTPError as e:
            raise ProviderAPIError(f"Provider returned HTTP {response.status_code}: {e}")
        except ValueError as e:
            raise ProviderInvalidResponseError(f"Invalid JSON response: {e}")

        username = data.get('user_id')
        if not username:
            raise ProviderInvalidResponseError("Missing 'user_id' in provider response")

        password = data.get('password', username)
        return {
            'username': username,
            'password': password,
            'raw_response': data,
        }
