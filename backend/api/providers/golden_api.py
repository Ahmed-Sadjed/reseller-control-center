import logging
import uuid
import requests
from datetime import datetime, timezone

from .base import BaseProviderAdapter, ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)


class GoldenAPIAdapter(BaseProviderAdapter):
    def __init__(self, provider):
        super().__init__(provider)
        self.api_url = provider.api_endpoint.rstrip('/')
        self.api_key = provider.get_token()
        self.timeout = provider.extra_config.get('timeout', 30)

    @property
    def capabilities(self) -> set:
        return {'create', 'renew', 'check', 'refund'}

    def _request(self, method, path, **kwargs):
        headers = kwargs.pop('headers', {})
        headers.setdefault("X-API-Key", self.api_key)
        if method in ('POST', 'PUT', 'PATCH'):
            headers.setdefault("Content-Type", "application/json")

        url = f"{self.api_url}{path}"
        try:
            logger.info("GoldenAPI %s %s", method.upper(), path)
            response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
            
            if response.status_code == 422:
                try:
                    err_data = response.json()
                    err_msg = err_data.get('message', '')
                    errors_detail = err_data.get('errors') or err_data.get('details') or ''
                    full_msg = f"Validation Error (422): {err_msg}"
                    if errors_detail:
                        full_msg += f" | Details: {errors_detail}"
                    logger.error("GoldenAPI 422 full response: %s", err_data)
                    logger.error("GoldenAPI 422 request payload: %s", kwargs.get('json', {}))
                except ValueError:
                    err_data = response.text
                    full_msg = f"Validation Error (422): {err_data}"
                    logger.error("GoldenAPI 422 raw response: %s", response.text)
                
                error = ProviderAPIError(full_msg)
                error.code = 422
                raise error

            response.raise_for_status()
            return response.json()

        except requests.Timeout as e:
            logger.error("GoldenAPI timeout: %s", e)
            raise ProviderTimeoutError(f"Provider request timed out: {e}")
        except requests.ConnectionError as e:
            logger.error("GoldenAPI connection error: %s", e)
            raise ProviderTimeoutError(f"Connection error: {e}")
        except requests.HTTPError as e:
            logger.error("GoldenAPI HTTP %s: %s", response.status_code, response.text[:300])
            try:
                err_data = response.json()
                err_msg = err_data.get('message', response.text[:500])
            except (ValueError, AttributeError):
                err_msg = response.text[:500]
            raise ProviderAPIError(err_msg)
        except ValueError as e:
            logger.error("GoldenAPI invalid JSON: %s", response.text[:300])
            raise ProviderInvalidResponseError(f"Invalid JSON response: {e}")

    def create(self, pack_id: int, months: int, is_lifetime: bool = False, username='', password='', note='', template_id=None, dns_domain_id=None, **kwargs) -> dict:
        base_username = username or f"g{uuid.uuid4().hex[:7]}"
        final_password = password or uuid.uuid4().hex[:7].upper()

        payload = {
            "package_id": pack_id,
            "max_connections": 1,
            "password": final_password,
            "is_adult": False,
        }
        if template_id:
            payload["template_id"] = int(template_id)
        if dns_domain_id:
            payload["dns_domain_id"] = int(dns_domain_id)
        if note:
            payload["notes"] = note

        max_attempts = 3
        data = None
        current_username = base_username

        for attempt in range(max_attempts):
            if attempt > 0:
                current_username = f"g{uuid.uuid4().hex[:7]}"
            
            payload["username"] = current_username
            try:
                logger.info("GoldenAPI attempt %d to create line with username %s", attempt + 1, current_username)
                data = self._request('POST', '/lines', json=payload)
                break
            except ProviderAPIError as e:
                if attempt < max_attempts - 1 and getattr(e, 'code', None) == 422:
                    logger.warning("GoldenAPI Validation error (likely username %s taken), retrying...", current_username)
                    continue
                raise

        if not data:
            raise ProviderAPIError("Failed to create GoldenAPI line after retries.")

        data_list = data.get('data', [])
        line_data = data_list[0] if data_list else {}

        expires_at = None
        exp_date_str = line_data.get('exp_date') or data.get('exp_date')
        if exp_date_str:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(exp_date_str, fmt).replace(tzinfo=timezone.utc)
                    expires_at = dt.replace(hour=23, minute=59, second=59)
                    break
                except ValueError:
                    continue

        return {
            'external_id': current_username,
            'credentials': {
                'username': line_data.get('username', current_username),
                'secret_password': final_password,
                'line_id': line_data.get('id'),
                'package': (data.get('package') or {}).get('name', ''),
                'template_name': (data.get('template') or {}).get('name', ''),
                'dns_link_samsung': line_data.get('dns_link_for_samsung_lg', ''),
                'qr_url': (data.get('qr') or {}).get('url', ''),
                'max_connections': line_data.get('max_connections'),
                'is_trial': line_data.get('is_trial', False),
                'created_at': line_data.get('created_at', ''),
                'exp_date': line_data.get('exp_date', ''),
            },
            'expires_at': expires_at,
            'raw_response': data,
        }

    def check_device(self, mac: str, credential=None) -> dict:
        if not credential:
            raise ProviderAPIError("Credential is required for GoldenAPI check_device.")
        
        line_id = credential.data.get('line_id')
        if not line_id:
            raise ProviderAPIError("Credential is required for GoldenAPI check_device.")
        
        logger.info("GoldenAPI check_device for line_id=%s", line_id)
        data = self._request('GET', f'/lines/{line_id}')
        return data

    def activate_device(self, mac: str, pack_id: int, duration: str, extend: bool = False, credential=None) -> dict:
        if not extend:
            raise ProviderAPIError("GoldenAPI only supports extend for activate_device.")
        if not credential:
            raise ProviderAPIError("Credential is required for GoldenAPI extend.")
        
        line_id = credential.data.get('line_id')
        if not line_id:
            raise ProviderAPIError("Missing line_id in credential data.")

        payload = {
            "package_id": pack_id
        }
        logger.info("GoldenAPI extend: line_id=%s, package_id=%s", line_id, pack_id)
        data = self._request('POST', f'/lines/{line_id}/extend', json=payload)
        return data

    def refund(self, credential) -> dict:
        line_id = credential.data.get('line_id')
        if not line_id:
            raise ProviderAPIError("Missing line_id in credential data.")

        logger.info("GoldenAPI refund: line_id=%s", line_id)
        data = self._request('POST', f'/lines/{line_id}/refund', json={"mass_refund": False})
        return data

    def get_templates(self) -> list:
        """Fetch available bouquet templates from Golden OTT."""
        logger.info("GoldenAPI fetching templates")
        data = self._request('GET', '/account/templates')
        return data.get('data', {}).get('global', [])

    def get_domains(self) -> list:
        """Fetch available DNS domains from Golden OTT."""
        logger.info("GoldenAPI fetching domains")
        data = self._request('GET', '/account/domains')
        return data.get('data', [])
