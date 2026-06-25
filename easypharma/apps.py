from django.apps import AppConfig


class EasypharmaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'easypharma'

    def ready(self):
        # Signals register karo — server start hone pe ek baar
        from easypharma.signals import register_signals
        register_signals()