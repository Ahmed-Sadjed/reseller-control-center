import os
from .cms_only import CMSOnlyAdapter
from .gold_panel import GoldPanelAdapter
from .hotplayer import HotPlayerAdapter
from .golden_api import GoldenAPIAdapter
from .tivipanel import TiviPanelAdapter
from .promax import PromaxAdapter
from .mock import MockProviderAdapter


ADAPTER_REGISTRY = {
    'neo4k': CMSOnlyAdapter,
    'goldpanel': GoldPanelAdapter,
    'hotplayer': HotPlayerAdapter,
    'golden_api': GoldenAPIAdapter,
    'tivipanel': TiviPanelAdapter,
    'promax': PromaxAdapter,
    'mock': MockProviderAdapter,
}

def get_adapter_for_provider(provider_instance):
    from django.conf import settings
    from django.core.cache import cache

    # DEV ONLY: frontend mock toggle checked before env vars
    if cache.get('dev_mock_enabled'):
        return MockProviderAdapter(provider=provider_instance)

    use_mock = os.getenv('USE_MOCK_PROVIDER', 'False').lower() == 'true'

    if use_mock:
        return MockProviderAdapter(provider=provider_instance)

    if settings.DEBUG and not os.getenv('ALLOW_REAL_IN_DEBUG', 'False').lower() == 'true':
        import logging
        logging.getLogger(__name__).warning(
            "DEBUG=True and ALLOW_REAL_IN_DEBUG is not set — falling back to MockProviderAdapter"
        )
        return MockProviderAdapter(provider=provider_instance)

    adapter_class = ADAPTER_REGISTRY.get(provider_instance.adapter_key)
    if not adapter_class:
        raise ValueError(f"No adapter found for key: {provider_instance.adapter_key}")

    return adapter_class(provider=provider_instance)
