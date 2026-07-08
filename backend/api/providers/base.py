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

    @abstractmethod
    @abstractmethod
    def create_line(self, pack_id: int, months: int, is_lifetime: bool = False) -> dict:
        """
        Returns:
            {
                'user_id': str,
                'streaming_username': str,
                'password': str,
                'dns_domain': str,
                'm3u_url': str,
                'expires_at': datetime | None,
                'raw_response': dict
            }
        Raises:
            ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError
        """
        pass

    def activate_device(self, mac: str, pack_id: int, duration: str, extend: bool = False) -> dict:
        raise NotImplementedError(f"Manual activation not supported by {self.provider.name}")

    def check_device(self, mac: str) -> dict:
        raise NotImplementedError(f"Device check not supported by {self.provider.name}")

    def add_playlists(self, mac: str, playlists: list) -> dict:
        raise NotImplementedError(f"Playlist management not supported by {self.provider.name}")

    def delete_playlists(self, mac: str) -> dict:
        raise NotImplementedError(f"Playlist deletion not supported by {self.provider.name}")
