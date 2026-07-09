"""Удаляет события аналитики (клики, пинги, просмотры страниц, сессии) старше N дней.

Таблицы analytics_* растут быстро (heartbeat раз в 20с на вкладку, пинг на каждый
апдейт бота) и не имеют автоматической очистки — Celery/cron-планировщика в проекте
нет, поэтому команда рассчитана на ручной запуск или системный cron:

    python manage.py purge_analytics --days 90
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from blog.models import BotSessionPing, ButtonClickEvent, WebPageView, WebSession


class Command(BaseCommand):
    help = 'Удаляет события аналитики (analytics_*) старше --days дней.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90, help='Хранить события за последние N дней (по умолчанию 90).')

    def handle(self, *args, **options):
        cutoff = timezone.now() - timezone.timedelta(days=options['days'])

        clicks, _ = ButtonClickEvent.objects.filter(created_at__lt=cutoff).delete()
        pings, _ = BotSessionPing.objects.filter(created_at__lt=cutoff).delete()
        page_views, _ = WebPageView.objects.filter(entered_at__lt=cutoff).delete()
        sessions, _ = WebSession.objects.filter(last_seen_at__lt=cutoff).delete()

        self.stdout.write(self.style.SUCCESS(
            f'Удалено: клики={clicks}, пинги бота={pings}, просмотры страниц={page_views}, веб-сессии={sessions} '
            f'(старше {options["days"]} дней).'
        ))
