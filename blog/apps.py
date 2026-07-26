from django.apps import AppConfig


class BlogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'blog'

    def ready(self):
        # Подключаем сигналы динамических достижений (категория/организация/меро →
        # своё достижение). Импорт внутри ready — до готовности приложений нельзя.
        from blog import signals  # noqa: F401
