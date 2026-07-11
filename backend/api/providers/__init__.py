import os
from .cms_only import CMSOnlyAdapter
from .gold_panel import GoldPanelAdapter
from .hotplayer import HotPlayerAdapter
from .golden_api import GoldenAPIAdapter
from .mock import MockProviderAdapter


ADAPTER_REGISTRY = {
    'neo4k': CMSOnlyAdapter,
    'goldpanel': GoldPanelAdapter,
    'hotplayer': HotPlayerAdapter,
    'golden_api': GoldenAPIAdapter,
    'mock': MockProviderAdapter,
}

def get_adapter_for_provider(provider_instance):
    if os.getenv('USE_MOCK_PROVIDER', 'False').lower() == 'true':
        return MockProviderAdapter(provider=provider_instance)
    
    adapter_class = ADAPTER_REGISTRY.get(provider_instance.adapter_key)
    if not adapter_class:
        raise ValueError(f"No adapter found for key: {provider_instance.adapter_key}")
    
    return adapter_class(provider=provider_instance)
