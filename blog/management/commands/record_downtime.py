"""Ручная запись периода простоя системы для графиков онлайна на дашборде аналитики
(/analytics/) — красная зона при --kind crash, жёлтая при --kind planned. Даты в
локальном времени проекта (Europe/Moscow), формат `ГГГГ-ММ-ДД ЧЧ:ММ`.

    python manage.py record_downtime --kind crash --start "2026-07-09 14:00" --end "2026-07-09 14:20" --comment "упал gunicorn"
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from blog.models import SystemDowntime


class Command(BaseCommand):
    help = 'Записывает период простоя системы (для красных/жёлтых зон на дашборде аналитики).'

    def add_arguments(self, parser):
        parser.add_argument('--kind', choices=['crash', 'planned'], default='crash')
        parser.add_argument('--start', required=True, help='ГГГГ-ММ-ДД ЧЧ:ММ')
        parser.add_argument('--end', required=True, help='ГГГГ-ММ-ДД ЧЧ:ММ')
        parser.add_argument('--comment', default='')

    def handle(self, *args, **options):
        started = parse_datetime(options['start'])
        ended = parse_datetime(options['end'])
        if not started or not ended:
            raise CommandError('Не удалось разобрать дату — используйте формат ГГГГ-ММ-ДД ЧЧ:ММ.')
        if timezone.is_naive(started):
            started = timezone.make_aware(started)
        if timezone.is_naive(ended):
            ended = timezone.make_aware(ended)
        if ended <= started:
            raise CommandError('Окончание простоя должно быть позже начала.')

        downtime = SystemDowntime.objects.create(
            kind=options['kind'], started_at=started, ended_at=ended, comment=options['comment'],
        )
        self.stdout.write(self.style.SUCCESS(f'Записано: {downtime}'))
