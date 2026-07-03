import os
from .cms_only import CMSOnlyAdapter
from .mock import MockProviderAdapter


def get_provider_adapter():
    use_mock = os.getenv('USE_MOCK_PROVIDER', 'False').lower() == 'true'
    if use_mock:
        fail_rate = float(os.getenv('MOCK_FAIL_RATE', '0.2'))
        return MockProviderAdapter(fail_rate=fail_rate)
    else:
        return CMSOnlyAdapter(
            api_url=os.getenv('IPTV_API_URL'),
            api_key=os.getenv('IPTV_API_KEY'),
            dns_domain=os.getenv('IPTV_DNS', 'kmapp.xyz'),
            timeout=int(os.getenv('IPTV_TIMEOUT', '30'))
        )
