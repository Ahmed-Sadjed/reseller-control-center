from abc import ABC, abstractmethod


class ProviderAPIError(Exception):
    pass


class ProviderTimeoutError(ProviderAPIError):
    pass


class ProviderInvalidResponseError(ProviderAPIError):
    pass


class BaseProviderAdapter(ABC):
    def __init__(self, provider):
        """
        Initializes the adapter with the Provider model instance,
        from which it should read endpoint, token, and extra_config.
        """
        self.provider = provider

    @property
    def capabilities(self) -> set:
        """Declare what this adapter supports. Subclasses should override."""
        return {'create'}

    @abstractmethod
    def create(self, pack_id: int, months: int, is_lifetime: bool = False, **kwargs) -> dict:
        """
        New Standard Format contract.

        Accepts additional kwargs for provider-specific params
        (e.g. mac, note for HotPlayer).

        Returns:
            {
                'external_id': str,
                'credentials': {
                    # non-secret and secret fields
                    # keys prefixed with 'secret_' are treated as secrets
                },
                'expires_at': datetime | None,
                'raw_response': dict,
            }
        Raises:
            ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError
        """
        pass

    def create_line(self, pack_id: int, months: int, is_lifetime: bool = False, **kwargs) -> dict:
        """
        Legacy alias — translates new Standard Format back to old format
        so tasks.py and any legacy callers do not break.

        Old format:
            {
                'user_id': str,
                'streaming_username': str,
                'password': str,
                'dns_domain': str,
                'm3u_url': str,
                'expires_at': datetime | None,
                'raw_response': dict,
            }
        """
        result = self.create(pack_id=pack_id, months=months, is_lifetime=is_lifetime, **kwargs)
        creds = result.get('credentials', {})
        return {
            'user_id': result.get('external_id', ''),
            'streaming_username': creds.get('username', creds.get('mac', result.get('external_id', ''))),
            'password': creds.get('secret_password', ''),
            'dns_domain': creds.get('dns_domain', ''),
            'm3u_url': creds.get('m3u_url', ''),
            'expires_at': result.get('expires_at'),
            'raw_response': result.get('raw_response', {}),
        }

    # --- Optional capability methods (subclasses opt-in) ---

    def renew(self, external_id: str, months: int) -> dict:
        raise NotImplementedError(f"Renew not supported by {self.provider.name}")

    def suspend(self, external_id: str) -> dict:
        raise NotImplementedError(f"Suspend not supported by {self.provider.name}")

    def get_balance(self) -> dict:
        raise NotImplementedError(f"Balance check not supported by {self.provider.name}")

    def health_check(self) -> dict:
        raise NotImplementedError(f"Health check not supported by {self.provider.name}")

    # --- Existing device management methods ---

    def activate_device(self, mac: str, pack_id: int, duration: str, extend: bool = False) -> dict:
        raise NotImplementedError(f"Manual activation not supported by {self.provider.name}")

    def check_device(self, mac: str) -> dict:
        raise NotImplementedError(f"Device check not supported by {self.provider.name}")

    def add_playlists(self, mac: str, playlists: list) -> dict:
        raise NotImplementedError(f"Playlist management not supported by {self.provider.name}")

    def delete_playlists(self, mac: str) -> dict:
        raise NotImplementedError(f"Playlist deletion not supported by {self.provider.name}")
