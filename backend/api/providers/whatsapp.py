from urllib.parse import quote
from .base import BaseProviderAdapter


class WhatsAppAdapter(BaseProviderAdapter):
    @property
    def capabilities(self) -> set:
        return {'create'}

    def create(self, pack_id: int, months: int, is_lifetime: bool = False, **kwargs) -> dict:
        pass