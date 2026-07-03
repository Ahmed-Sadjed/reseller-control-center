from abc import ABC, abstractmethod


class ProviderAPIError(Exception):
    pass


class ProviderTimeoutError(ProviderAPIError):
    pass


class ProviderInvalidResponseError(ProviderAPIError):
    pass


class BaseProviderAdapter(ABC):
    @abstractmethod
    def create_line(self, pack_id: int, months: int) -> dict:
        """
        Returns:
            {
                'username': str,
                'password': str,
                'raw_response': dict
            }
        Raises:
            ProviderAPIError, ProviderTimeoutError, ProviderInvalidResponseError
        """
        pass
