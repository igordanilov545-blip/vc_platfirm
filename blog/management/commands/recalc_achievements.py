"""Пересчёт auto-достижений всех пользователей (после смены набора достижений).

    python manage.py recalc_achievements

Идемпотентно: выдаёт только недостающее. Нужен после миграции 0055 (забеги вместо
позиций, категории забегов, новые ряды) — иначе новое появится у человека только
при следующем изменении его данных.
"""
from django.core.management.base import BaseCommand

from data_base import data_controller as dc
from blog.services.achievements import recalc_user_achievements


class Command(BaseCommand):
    help = 'Пересчитывает и доначисляет auto-достижения всем пользователям.'

    def handle(self, *args, **options):
        users = dc.get_users()
        granted = 0
        for user in users:
            granted += len(recalc_user_achievements(user))
        self.stdout.write(self.style.SUCCESS(f'Пользователей: {len(users)}, выдано достижений: {granted}.'))
