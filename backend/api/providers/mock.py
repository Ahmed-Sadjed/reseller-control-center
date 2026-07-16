import uuid
import random
import os
from datetime import timedelta
from django.utils import timezone
from .base import BaseProviderAdapter


class MockProviderAdapter(BaseProviderAdapter):
    def __init__(self, provider=None, fail_rate=None):
        super().__init__(provider)
        if fail_rate is None:
            fail_rate = float(os.getenv('MOCK_FAIL_RATE', '0.0'))
        self.fail_rate = fail_rate

    @property
    def capabilities(self) -> set:
        return {'create', 'renew', 'suspend', 'balance_check'}

    def create(self, pack_id: int, months: int, is_lifetime: bool = False, **kwargs) -> dict:
        if random.random() < self.fail_rate:
            raise Exception(f"Simulated provider failure (pack_id={pack_id}, months={months})")

        mac_prefix = self.provider.extra_config.get("mac_prefix", "00:1A:79") if self.provider else "00:1A:79"
        mac = f"{mac_prefix}:{uuid.uuid4().hex[:2].upper()}:{uuid.uuid4().hex[:2].upper()}:{uuid.uuid4().hex[:2].upper()}"
        user_id = f"mock_{uuid.uuid4().hex[:8]}"
        streaming_username = uuid.uuid4().hex[:10]
        password = f"pass_{uuid.uuid4().hex[:6]}"

        dns_domain = self.provider.extra_config.get("dns_domain", "mock-provider.tv") if self.provider else "mock-provider.tv"
        port = self.provider.extra_config.get("port", 8080) if self.provider else 8080
        m3u_url = f"https://{dns_domain}:{port}/get.php?username={streaming_username}&password={password}"
        panel_url = self.provider.extra_config.get("panel_url", "https://api.tivipanel.net") if self.provider else "https://api.tivipanel.net"

        expires_at = None
        if not is_lifetime:
            expires_at = timezone.now() + timedelta(days=30 * (months or 1))

        return {
            'external_id': user_id,
            'credentials': {
                'action': 'create_m3u',
                'mac': mac,
                'username': streaming_username,
                'secret_password': password,
                'dns_domain': dns_domain,
                'm3u_url': m3u_url,
                'panel_url': panel_url,
            },
            'expires_at': expires_at,
            'raw_response': {
                'user_id': user_id,
                'status': 'mock_success',
                'pack': pack_id,
                'months': months,
                'mac': mac,
            },
        }

    def activate_device(self, mac: str, pack_id: int, duration: str, extend: bool = False) -> dict:
        if random.random() < self.fail_rate:
            raise Exception(f"Simulated provider failure: activate_device mac={mac}")
        return {
            'status': 'success',
            'mac': mac,
            'pack_id': pack_id,
            'duration': duration,
            'extend': extend,
            'mock': True,
        }

    def check_device(self, mac: str) -> dict:
        if random.random() < self.fail_rate:
            raise Exception(f"Simulated provider failure: check_device mac={mac}")
        from datetime import timedelta
        from django.utils import timezone
        return {
            'status': 'active',
            'mac': mac,
            'plan': 'MONTHS_6',
            'expiration': (timezone.now() + timedelta(days=180)).isoformat(),
            'playlists': [{'name': 'Mock Playlist', 'url': 'http://mock.example.com/get.php'}],
            'mock': True,
        }

    def get_templates(self) -> list:
        return []
