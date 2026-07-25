"""Технический демо-аккаунт витрины достижений.

    python manage.py create_all_achievements_account

Создаёт (идемпотентно) волонтёра `all_achivments` (веб-логин all_achivments /
пароль all_achivments) и выдаёт ему ВСЕ существующие достижения: каждую ступень
каждого series + каждое single/hidden/manual, включая тим-лидерские и уникальные.

Повторный запуск ДОНАЧИСЛЯЕТ новые достижения (после добавления новых определений
через миграции/UI) — так витрина всегда полная. Это обычный волонтёр (без ролей ТЛ/
менеджера), достижения выданы напрямую, не через реальную активность — сугубо
техническая учётка (см. blog.services.achievements.ALL_ACHIEVEMENTS_LOGIN).
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from blog.models import User
from blog.services.achievements import ALL_ACHIEVEMENTS_LOGIN, grant_all_achievements


class Command(BaseCommand):
    help = 'Создаёт/синхронизирует техаккаунт-витрину all_achivments со всеми достижениями.'

    @transaction.atomic
    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            telegram_id='demo:all_achivments',
            defaults={
                'telegram_username': 'all_achivments',
                'first_name': 'Все',
                'last_name': 'Достижения',
                'phone': '+7 900 000-00-00',
                'status': 'active',
                'registration_status': 'registered',
            },
        )
        # Веб-вход all_achivments / all_achivments (идемпотентно).
        if user.login != ALL_ACHIEVEMENTS_LOGIN:
            user.login = ALL_ACHIEVEMENTS_LOGIN
        if not user.has_usable_password() or not user.check_password(ALL_ACHIEVEMENTS_LOGIN):
            user.set_password(ALL_ACHIEVEMENTS_LOGIN)
            user.web_credentials_set_at = timezone.now()
        user.save()

        granted = grant_all_achievements(user)
        state = 'создан' if created else 'обновлён'
        self.stdout.write(self.style.SUCCESS(
            f'[OK] Техаккаунт all_achivments {state}: id={user.id}, доначислено достижений={granted}'
        ))
