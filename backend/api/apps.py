from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        import api.signals
        self.check_required_settings()

    def check_required_settings(self):
        from django.conf import settings
        required = ['FERNET_KEY']
        for key in required:
            value = getattr(settings, key, '')
            if not value:
                raise ImproperlyConfigured(
                    f'{key} environment variable must be set.'
                )
