import uuid
import random
from .base import BaseProviderAdapter


class MockProviderAdapter(BaseProviderAdapter):
    def __init__(self, fail_rate=0.0):
        self.fail_rate = fail_rate

    def create_line(self, pack_id: int, months: int) -> dict:
        if random.random() < self.fail_rate:
            raise Exception(f"Simulated provider failure (pack_id={pack_id}, months={months})")

        username = f"mock_{uuid.uuid4().hex[:8]}"
        password = f"pass_{uuid.uuid4().hex[:6]}"

        return {
            'username': username,
            'password': password,
            'raw_response': {
                'user_id': username,
                'password': password,
                'status': 'mock_success',
                'pack': pack_id,
                'months': months
            }
        }
