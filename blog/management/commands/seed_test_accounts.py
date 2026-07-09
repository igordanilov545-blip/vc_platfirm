"""Тестовые учётные записи и демо-мероприятия для проверки ролей и логики churn.

    python manage.py seed_test_accounts

Идемпотентна (get_or_create по telegram_id/title/login) — можно запускать повторно.
Добавляет ПОВЕРХ существующих данных, ничего не удаляя:

  - Тим-лидер Михаил Соколов — веб-логин mikhail / mikhail123 (на существующем
    demo:mikhail_tl из seed_demo_profiles, если он есть; иначе создаёт).
  - Менеджер Admin Manager — веб-логин 123 / 123.
  - Волонтёр Абрамова Виктория Евгеньевна — веб-логин viktoria / viktoria123.
  - «Пров Ненадёжный» — churn_score=10 (в блэклисте), без веб-логина.
  - Демо-мероприятия 2–4 (Уборка парка/прошло, Забег сегодня/идёт,
    Фестиваль через неделю/набор) с заявками и участиями.

Логины/пароли и назначение см. documentation/dev_credentials.md.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from blog.models import (
    Application, Event, EventShift, EventStaff, Organization,
    Organizer, Participation, TeamLeader, User,
)


class Command(BaseCommand):
    help = 'Создаёт тестовые учётки (Михаил/менеджер123/Виктория/churn) и демо-меро 2–4.'

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        today = now.date()

        # --- 1) Тим-лидер Михаил с веб-логином ------------------------------
        mikhail, _ = User.objects.get_or_create(
            telegram_id='demo:mikhail_tl',
            defaults={
                'telegram_username': 'mikhail_tl',
                'first_name': 'Михаил',
                'last_name': 'Соколов',
                'status': 'active',
                'registration_status': 'registered',
            },
        )
        self._ensure_web_login(mikhail, login='mikhail', password='mikhail123')
        if not TeamLeader.objects.filter(user=mikhail, revoked_at__isnull=True).exists():
            TeamLeader.objects.create(user=mikhail)
        self.stdout.write(self.style.SUCCESS(f'[OK] Тим-лидер Михаил: login=mikhail id={mikhail.id}'))

        # Менеджер Admin Manager (login 123/123) уже создан ранее
        # (seed_report_demo / create_manager) — здесь его не трогаем.

        # --- 3) Волонтёр Виктория с веб-логином -----------------------------
        viktoria, _ = User.objects.get_or_create(
            telegram_id='demo:viktoria_vol',
            defaults={
                'telegram_username': 'viktoria_vol',
                'first_name': 'Виктория',
                'last_name': 'Абрамова',
                'middle_name': 'Евгеньевна',
                'phone': '+7 900 222-33-44',
                'status': 'active',
                'registration_status': 'registered',
            },
        )
        self._ensure_web_login(viktoria, login='viktoria', password='viktoria123')
        self.stdout.write(self.style.SUCCESS(f'[OK] Волонтёр Виктория: login=viktoria id={viktoria.id}'))

        # --- 4) Пользователь в блэклисте (churn_score=10) -------------------
        churny, _ = User.objects.get_or_create(
            telegram_id='demo:churny_user',
            defaults={
                'first_name': 'Пров',
                'last_name': 'Ненадёжный',
                'status': 'blacklisted',
                'churn_score': 10,
                'registration_status': 'registered',
            },
        )
        if churny.churn_score != 10 or churny.status != 'blacklisted':
            churny.churn_score = 10
            churny.status = 'blacklisted'
            churny.save(update_fields=['churn_score', 'status'])
        self.stdout.write(self.style.SUCCESS(f'[OK] Churn-пользователь: id={churny.id} (blacklist, churn=10)'))

        # --- 5) Демо-мероприятия 2–4 ----------------------------------------
        organization = Organization.objects.filter(name='Беговое сообщество').first()
        organizer = Organizer.objects.filter(first_name='Анастасия', last_name='Волкова').first()

        # Событие 2 — «Уборка парка» (прошло): смена 5 дней назад, участие Виктории.
        ev2, created2 = Event.objects.get_or_create(
            title='Уборка парка (прошло)',
            defaults={
                'description': 'Демо: прошедшее мероприятие с одной approved-заявкой.',
                'organization': organization, 'organizer': organizer,
                'event_status': 'passed', 'published_at': now - timezone.timedelta(days=12),
            },
        )
        if created2:
            shift2 = EventShift.objects.create(
                event=ev2, day=today - timezone.timedelta(days=5),
                start_time=now - timezone.timedelta(days=5, hours=6),
                end_time=now - timezone.timedelta(days=5, hours=2),
                volunteer_needed=5, recruit_status='closed',
            )
            self._staff(ev2, mikhail)
            Application.objects.create(
                event=ev2, user=viktoria, first_name='Виктория', last_name='Абрамова',
                middle_name='Евгеньевна', telegram_username='viktoria_vol',
                phone='+7 900 222-33-44', status='approved',
                submitted_at=now - timezone.timedelta(days=8),
                assigned_at=now - timezone.timedelta(days=7), assigned_by=mikhail,
            )
            Participation.objects.create(
                user=viktoria, event_day=shift2, status='attended', hours=4, full_shift=True,
            )
        self.stdout.write(self.style.SUCCESS(f'[OK] Меро «Уборка парка (прошло)»: id={ev2.id}'))

        # Событие 3 — «Забег сегодня (идёт)»: смена сегодня, Михаил — тим-лидер.
        ev3, created3 = Event.objects.get_or_create(
            title='Забег сегодня (идёт)',
            defaults={
                'description': 'Демо: идущее сегодня мероприятие.',
                'organization': organization, 'organizer': organizer,
                'event_status': 'ongoing', 'published_at': now - timezone.timedelta(days=3),
            },
        )
        if created3:
            EventShift.objects.create(
                event=ev3, day=today,
                start_time=now.replace(hour=9, minute=0, second=0, microsecond=0),
                end_time=now.replace(hour=18, minute=0, second=0, microsecond=0),
                volunteer_needed=8, recruit_status='open',
            )
            self._staff(ev3, mikhail)
        self.stdout.write(self.style.SUCCESS(f'[OK] Меро «Забег сегодня (идёт)»: id={ev3.id}'))

        # Событие 4 — «Фестиваль через неделю (набор)»: 1 approved + 3 новых заявки.
        ev4, created4 = Event.objects.get_or_create(
            title='Фестиваль через неделю (набор)',
            defaults={
                'description': 'Демо: предстоящее мероприятие с открытым набором.',
                'organization': organization, 'organizer': organizer,
                'event_status': 'upcoming', 'published_at': now - timezone.timedelta(days=1),
            },
        )
        if created4:
            shift4 = EventShift.objects.create(
                event=ev4, day=today + timezone.timedelta(days=7),
                start_time=now + timezone.timedelta(days=7, hours=1),
                end_time=now + timezone.timedelta(days=7, hours=5),
                volunteer_needed=15, recruit_status='open',
            )
            self._staff(ev4, mikhail)
            approved = Application.objects.create(
                event=ev4, user=viktoria, first_name='Виктория', last_name='Абрамова',
                middle_name='Евгеньевна', telegram_username='viktoria_vol',
                phone='+7 900 222-33-44', status='approved',
                submitted_at=now - timezone.timedelta(hours=20),
                assigned_at=now - timezone.timedelta(hours=10), assigned_by=mikhail,
            )
            approved.selected_shifts.add(shift4)
            for i in range(1, 4):
                app = Application.objects.create(
                    event=ev4, first_name=f'Заявитель{i}', last_name='Тестовый',
                    telegram_username=f'applicant_{i}', phone=f'+7 900 000-00-0{i}',
                    status='new', submitted_at=now - timezone.timedelta(hours=i),
                )
                app.selected_shifts.add(shift4)
        self.stdout.write(self.style.SUCCESS(f'[OK] Меро «Фестиваль через неделю (набор)»: id={ev4.id}'))

        self.stdout.write(self.style.SUCCESS('\nГотово. Тестовые учётки и демо-меро добавлены.'))

    def _ensure_web_login(self, user, login, password):
        """Проставляет login+пароль пользователю, если ещё не задан или отличается.
        Если логин занят ДРУГИМ пользователем — не падаем с IntegrityError, а
        предупреждаем и пропускаем (команда должна оставаться идемпотентной)."""
        clash = User.objects.filter(login=login).exclude(pk=user.pk).first()
        if clash:
            self.stdout.write(self.style.WARNING(
                f'[!] login "{login}" уже занят пользователем id={clash.pk} — пропускаю выдачу веб-входа.'))
            return
        changed = False
        if user.login != login:
            user.login = login
            changed = True
        if not user.has_usable_password() or not user.check_password(password):
            user.set_password(password)
            user.web_credentials_set_at = timezone.now()
            changed = True
        if changed:
            user.save()

    def _staff(self, event, user):
        EventStaff.objects.get_or_create(event=event, user=user, staff_role='team_lead')
