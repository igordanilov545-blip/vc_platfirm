from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, telegram_id, **extra_fields):
        if not telegram_id:
            raise ValueError('Users must have a telegram_id')
        user = self.model(telegram_id=telegram_id, **extra_fields)
        user.set_unusable_password()  # вход через Telegram по умолчанию
        user.save(using=self._db)
        return user

    def create_web_manager(self, login, password, first_name, last_name, **extra_fields):
        """Служебный путь создания менеджера с веб-входом (management command)."""
        if not login:
            raise ValueError('Manager must have a login')
        telegram_id = extra_fields.pop('telegram_id', None) or f'web:{login}'
        user = self.model(
            telegram_id=telegram_id,
            login=login,
            first_name=first_name,
            last_name=last_name,
            **extra_fields,
        )
        user.set_password(password)
        user.web_credentials_set_at = timezone.now()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """Центральная сущность системы (волонтёр/тим-лидер/менеджер)."""

    GENDER_CHOICES = [
        ('male', 'Мужской'),
        ('female', 'Женский'),
    ]
    STATUS_CHOICES = [
        ('active', 'Активен'),
        ('inactive', 'Неактивен'),
        ('blacklisted', 'В блэклисте'),
    ]
    REGISTRATION_STATUS_CHOICES = [
        ('guest', 'Гость (первое касание)'),
        ('registered', 'Зарегистрирован'),
    ]

    id = models.AutoField(primary_key=True)
    system_username = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    telegram_id = models.CharField(max_length=50, unique=True, db_index=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    VK_username = models.CharField(max_length=100, blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    birthday = models.DateField(blank=True, null=True)
    about = models.TextField(blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    comment = models.TextField(blank=True, null=True)

    # Прогресс онбординга в TG-боте (tg-bot.md §3.4). Не путать с `status` выше:
    # это про заполненность анкеты, а не про допуск к участию.
    registration_status = models.CharField(
        max_length=20, choices=REGISTRATION_STATUS_CHOICES, default='guest'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    last_event_at = models.DateTimeField(blank=True, null=True)

    # Кэшированная статистика
    total_event_count = models.IntegerField(default=0)
    season_event_count = models.IntegerField(default=0)
    total_hours = models.IntegerField(default=0)
    season_hours = models.IntegerField(default=0)
    churn_score = models.FloatField(default=0)

    # Веб-аутентификация (доп. канал входа).
    # Хеш пароля хранится в унаследованном от AbstractBaseUser поле `password`.
    login = models.CharField(max_length=50, unique=True, blank=True, null=True)
    web_credentials_set_at = models.DateTimeField(blank=True, null=True)

    # Подписка на уведомления бота о новых мероприятиях (Этап 8).
    notify_new_events = models.BooleanField(default=True)

    objects = UserManager()

    USERNAME_FIELD = 'telegram_id'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'users'
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.telegram_id})"

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.telegram_username or self.telegram_id

    @property
    def is_active(self):
        return self.status != 'blacklisted'

    def is_active_manager(self):
        return self.manager_roles.filter(revoked_at__isnull=True).exists()

    def is_active_team_leader(self):
        return self.team_leader_roles.filter(revoked_at__isnull=True).exists()

    def is_registered(self):
        return self.registration_status == 'registered'


class Manager(models.Model):
    """История выдачи и отзыва ролей менеджеров."""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='manager_roles')
    assigned_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_managers')

    total_events = models.IntegerField(default=0)
    season_events = models.IntegerField(default=0)

    class Meta:
        db_table = 'managers'
        verbose_name = 'Менеджер'
        verbose_name_plural = 'Менеджеры'


class TeamLeader(models.Model):
    """История выдачи и отзыва ролей тим-лидеров."""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_leader_roles')
    assigned_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_team_leaders')

    total_events = models.IntegerField(default=0)
    season_events = models.IntegerField(default=0)

    class Meta:
        db_table = 'team_leaders'
        verbose_name = 'Тим-лидер'
        verbose_name_plural = 'Тим-лидеры'


class Organization(models.Model):
    """Юридические лица или структурные подразделения."""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    events_count = models.IntegerField(default=0)
    volunteers_count = models.IntegerField(default=0)
    shifts_count = models.IntegerField(default=0)
    internal_rating = models.SmallIntegerField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'organizations'
        verbose_name = 'Организация'
        verbose_name_plural = 'Организации'

    def __str__(self):
        return self.name


class Organizer(models.Model):
    """Контактные лица организаций."""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='organizer_profile')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    VK_username = models.CharField(max_length=100, blank=True, null=True)
    whatsapp = models.CharField(max_length=50, blank=True, null=True)
    comments = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'organizers'
        verbose_name = 'Контактное лицо'
        verbose_name_plural = 'Контактные лица'

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class OrganizerOrganizationLink(models.Model):
    """Связь организатор-организация (Many-to-Many)."""
    id = models.AutoField(primary_key=True)
    organizer = models.ForeignKey(Organizer, on_delete=models.CASCADE, related_name='organization_links')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='organizer_links')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'organizer_organization_link'
        unique_together = ('organizer', 'organization')
        verbose_name = 'Связь организатора и организации'
        verbose_name_plural = 'Связи организаторов и организаций'


class OrganizerInteractionLog(models.Model):
    """История контактов менеджеров с организатором."""
    CONTACT_CHOICES = [
        ('call', 'Звонок'),
        ('message', 'Сообщение'),
        ('meeting', 'Встреча'),
    ]

    id = models.AutoField(primary_key=True)
    organizer = models.ForeignKey(Organizer, on_delete=models.CASCADE, related_name='interaction_log')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='organizer_interactions')
    contact_type = models.CharField(max_length=20, choices=CONTACT_CHOICES)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'organizer_interaction_log'
        verbose_name = 'Лог взаимодействия с организатором'
        verbose_name_plural = 'Логи взаимодействия с организаторами'


class Location(models.Model):
    """Справочник локаций."""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'locations'
        verbose_name = 'Локация'
        verbose_name_plural = 'Локации'

    def __str__(self):
        return self.name


class EventCategory(models.Model):
    """Справочник категорий мероприятий."""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'event_categories'
        verbose_name = 'Категория мероприятия'
        verbose_name_plural = 'Категории мероприятий'

    def __str__(self):
        return self.name


class ThankYouLetterTemplate(models.Model):
    """Шаблоны благодарственных писем."""
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    pattern_link = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'thank_you_letter_templates'
        verbose_name = 'Шаблон благодарственного письма'
        verbose_name_plural = 'Шаблоны благодарственных писем'

    def __str__(self):
        return self.title


class Const(models.Model):
    """Key-value справочник настраиваемых бизнес-параметров."""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    value = models.FloatField()
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'const'
        verbose_name = 'Константа'
        verbose_name_plural = 'Константы'

    def __str__(self):
        return f"{self.name} = {self.value}"


class Season(models.Model):
    """Периоды проведения ПГАС."""
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    start_season = models.DateField()
    end_season = models.DateField(blank=True, null=True)

    class Meta:
        db_table = 'seasons'
        verbose_name = 'Сезон'
        verbose_name_plural = 'Сезоны'

    def __str__(self):
        return f"Season: {self.start_season} - {self.end_season or '...'}"


class Event(models.Model):
    """Основная сущность события."""
    STATUS_CHOICES = [
        ('upcoming', 'Предстоит'),
        ('ongoing', 'Идёт'),
        ('finished', 'Завершено'),
    ]
    RECRUIT_STATUS_CHOICES = [
        ('open', 'Открыт'),
        ('closed', 'Закрыт'),
    ]
    DOBRO_LINK_TYPE_CHOICES = [
        ('event', 'Мероприятие'),
        ('organization', 'Организация'),
        ('project', 'Проект'),
    ]

    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    chat_link = models.URLField(blank=True, null=True)
    post_in_chanel_link = models.URLField(blank=True, null=True)
    dobro_ru_link = models.URLField(blank=True, null=True)
    dobro_ru_link_type = models.CharField(max_length=20, choices=DOBRO_LINK_TYPE_CHOICES, blank=True, null=True)
    dobro_ru_hours_logged = models.BooleanField(default=False)
    dobro_ru_logged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='dobro_ru_logged_events')

    event_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')
    recruit_status = models.CharField(max_length=20, choices=RECRUIT_STATUS_CHOICES, default='open')

    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    organizer = models.ForeignKey(Organizer, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_events')

    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(blank=True, null=True)
    people_helped = models.IntegerField(blank=True, null=True)
    internal_comment = models.TextField(blank=True, null=True)

    letter = models.ForeignKey(ThankYouLetterTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')

    class Meta:
        db_table = 'events'
        verbose_name = 'Мероприятие'
        verbose_name_plural = 'Мероприятия'

    def __str__(self):
        return self.title


class EventCategoryMap(models.Model):
    """Связь мероприятий с категориями (Many-to-Many)."""
    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='category_map')
    category = models.ForeignKey(EventCategory, on_delete=models.CASCADE, related_name='event_map')

    class Meta:
        db_table = 'event_category_map'
        unique_together = ('event', 'category')
        verbose_name = 'Категория мероприятия (связь)'
        verbose_name_plural = 'Категории мероприятий (связи)'


class EventDay(models.Model):
    """Разбивка мероприятия на конкретные даты и временные слоты."""
    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='days')
    day = models.DateField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    volunteer_needed = models.IntegerField(default=0)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='event_days')

    class Meta:
        db_table = 'event_days'
        verbose_name = 'День мероприятия'
        verbose_name_plural = 'Дни мероприятий'
        indexes = [
            models.Index(fields=['event']),
        ]

    def __str__(self):
        return f"{self.event.title} - {self.day}"


class EventStaff(models.Model):
    """Назначение менеджеров и тим-лидеров на конкретные события."""
    ROLE_CHOICES = [
        ('manager', 'Менеджер'),
        ('team_lead', 'Тим-лидер'),
    ]

    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='staff')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='staff_assignments')
    staff_role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_staff'
        verbose_name = 'Персонал мероприятия'
        verbose_name_plural = 'Персонал мероприятий'
        indexes = [
            models.Index(fields=['event', 'staff_role']),
        ]


class Application(models.Model):
    """Входящие запросы на участие. Могут быть от незарегистрированных пользователей."""

    STATUS_CHOICES = [
        ('new', 'Новая'),
        ('approved', 'Одобрена'),
        ('rejected', 'Отклонена/резерв'),
    ]

    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='applications')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='applications')

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)

    functions = models.CharField(max_length=255, blank=True, null=True)
    shifts = models.CharField(max_length=255, blank=True, null=True)
    role_in_event = models.CharField(max_length=255, blank=True, null=True)
    user_status = models.CharField(max_length=100, blank=True, null=True)

    submitted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')

    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_applications')

    class Meta:
        db_table = 'applications'
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'
        indexes = [
            models.Index(fields=['event', 'status']),
        ]

    def __str__(self):
        return f"Application #{self.id} for {self.event.title}"


class Participation(models.Model):
    """Подтвержденные участия."""
    STATUS_CHOICES = [
        ('attended', 'Присутствовал'),
        ('absent_excused', 'Отсутствовал (уважительно)'),
        ('absent_unexcused', 'Отсутствовал (без предупреждения)'),
    ]

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='participations')
    event_day = models.ForeignKey(EventDay, on_delete=models.CASCADE, related_name='participations')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='attended')
    hours = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # Отметка, что запрос "оцени мероприятие" уже отправлен (tg-bot.md §4.6) —
    # чтобы фоновая задача не слала его повторно при каждом проходе.
    feedback_requested_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'participations'
        verbose_name = 'Участие'
        verbose_name_plural = 'Участия'
        indexes = [
            models.Index(fields=['user', 'event_day']),
        ]


class ChurnHistory(models.Model):
    """Снимок churn_score на момент завершения сезона."""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='churn_history')
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='churn_history')
    churn_score = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'churn_history'
        verbose_name = 'История чарна'
        verbose_name_plural = 'История чарна'
        indexes = [
            models.Index(fields=['user', 'season']),
        ]


class UserComment(models.Model):
    """Внутренние комментарии к волонтёрам от менеджеров/тим-лидеров."""
    id = models.AutoField(primary_key=True)
    target_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_comments')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='authored_comments')
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_comments'
        verbose_name = 'Комментарий к волонтёру'
        verbose_name_plural = 'Комментарии к волонтёрам'


class EventFeedback(models.Model):
    """Отзывы о мероприятии."""
    id = models.AutoField(primary_key=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feedbacks')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='feedbacks')
    rating = models.SmallIntegerField()  # 0-10
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_feedbacks'
        verbose_name = 'Отзыв'
        verbose_name_plural = 'Отзывы'


class EventRequirement(models.Model):
    """Справочник требований к волонтерам."""
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'event_requirements'
        verbose_name = 'Требование'
        verbose_name_plural = 'Требования'

    def __str__(self):
        return self.title


class EventRequirementMap(models.Model):
    """Связь требований с мероприятиями."""
    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='requirement_map')
    requirement = models.ForeignKey(EventRequirement, on_delete=models.CASCADE, related_name='event_map')

    class Meta:
        db_table = 'event_requirement_map'
        unique_together = ('event', 'requirement')
        verbose_name = 'Требование мероприятия (связь)'
        verbose_name_plural = 'Требования мероприятий (связи)'


class BotOutbox(models.Model):
    """Очередь исходящих сообщений в Telegram (диспетчер уведомлений, Этап 8).

    Сообщения кладутся сюда из веб-приложения/сервисов и отправляются процессом
    бота (management command `run_bot`) с ретраями при сбоях Telegram API.
    """
    STATUS_CHOICES = [
        ('pending', 'Ожидает отправки'),
        ('sent', 'Отправлено'),
        ('failed', 'Ошибка (исчерпаны попытки)'),
    ]

    id = models.AutoField(primary_key=True)
    chat_id = models.CharField(max_length=50, db_index=True)
    text = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'bot_outbox'
        verbose_name = 'Исходящее сообщение бота'
        verbose_name_plural = 'Исходящие сообщения бота'
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]


class UserRequirementException(models.Model):
    """Исключения для волонтеров по требованиям."""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='requirement_exceptions')
    requirement = models.ForeignKey(EventRequirement, on_delete=models.CASCADE, related_name='user_exceptions')
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_requirement_exceptions'
        unique_together = ('user', 'requirement')
        verbose_name = 'Исключение пользователя'
        verbose_name_plural = 'Исключения пользователей'
