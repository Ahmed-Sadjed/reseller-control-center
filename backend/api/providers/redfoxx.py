import logging
from datetime import datetime, timezone
import requests
from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)


class RedfoxxAdapter(BaseProviderAdapter):
    def __init__(self, provider):
        super().__init__(provider)
        self.api_url = provider.api_endpoint.rstrip('/')
        self.api_key = provider.get_token()
        timeout = provider.extra_config.get('timeout', 30)
        self.timeout = (timeout / 2, timeout)

    @property
    def capabilities(self) -> set:
        return {'create'}

    def _request(self, method, path, **kwargs):
        headers = kwargs.pop('headers', {})
        headers.setdefault("Authorization", f"Bearer {self.api_key}")
        if method in ('POST', 'PUT', 'PATCH'):
            headers.setdefault("Content-Type", "application/json")

        url = f"{self.api_url}{path}"
        try:
            logger.info("Redfoxx %s %s", method.upper(), path)
            response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
            data = response.json()
        except requests.Timeout as e:
            logger.error("Redfoxx timeout: %s", e)
            raise ProviderTimeoutError(f"Provider request timed out: {e}")
        except requests.ConnectionError as e:
            logger.error("Redfoxx connection error: %s", e)
            raise ProviderTimeoutError(f"Connection error: {e}")
        except ValueError as e:
            logger.error("Redfoxx invalid JSON: %s", getattr(response, 'text', 'N/A')[:300])
            raise ProviderInvalidResponseError(f"Invalid JSON response: {e}")

        # Check for HTTP-level errors
        if not response.ok:
            error_code = data.get('error_code', '') if isinstance(data, dict) else ''
            status = response.status_code
            logger.error("Redfoxx HTTP %s: %s", status, error_code or response.text[:300])
            if status == 422 and error_code == 'insufficient_credits':
                raise ProviderAPIError(f"Insufficient credits on provider side")
            raise ProviderAPIError(f"Provider error (HTTP {status}): {error_code or response.text[:200]}")

        # Check envelope
        if isinstance(data, dict) and data.get('success') is False:
            error_msg = data.get('error_code') or data.get('message') or 'Unknown provider error'
            logger.error("Redfoxx returned error: %s", error_msg)
            raise ProviderAPIError(f"Provider error: {error_msg}")

        return data

    def get_packages(self) -> list:
        data = self._request('GET', '/packages')
        raw = data.get('data', []) if isinstance(data, dict) else data
        return raw if isinstance(raw, list) else []

    def create(self, pack_id: int, months: int, is_lifetime: bool = False, **kwargs) -> dict:
        payload = {"package_id": pack_id}

        username = kwargs.get('username')
        password = kwargs.get('password')
        if username:
            payload["username"] = username
        if password:
            payload["password"] = password

        data = self._request('POST', '/lines', json=payload)
        item = data.get('data', {}) if isinstance(data, dict) else data

        redfoxx_username = item.get('username', '')
        redfoxx_password = item.get('password', '')

        expires_at = None
        exp_date = item.get('exp_date')
        if exp_date:
            try:
                expires_at = datetime.fromtimestamp(int(exp_date), tz=timezone.utc)
            except (ValueError, OSError):
                pass

        extra_data = {}
        if item.get('max_connections') is not None:
            extra_data['max_connections'] = item['max_connections']
        if item.get('is_trial') is not None:
            extra_data['is_trial'] = item['is_trial']
        if item.get('notes'):
            extra_data['notes'] = item['notes']

        return {
            'external_id': redfoxx_username,
            'credentials': {
                'username': redfoxx_username,
                'secret_password': redfoxx_password,
                **extra_data,
            },
            'expires_at': expires_at,
            'raw_response': item,
        }
