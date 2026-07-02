from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, telegram_id, **extra_fields):
        if not telegram_id:
            raise ValueError('Users must have a telegram_id')
        user = self.model(telegram_id=telegram_id, **extra_fields)
        user.set_unusable_password()  # Так как вход через Telegram
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """
    Центральная сущность системы (volunteer).
    Наследуется от AbstractBaseUser для интеграции с системой аутентификации Django,
    но логика входа кастомная (через Telegram ID).
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('blacklisted', 'Blacklisted'),
    ]

    id = models.AutoField(primary_key=True)
    system_username = models.CharField(max_length=50, db_index=True)
    telegram_id = models.CharField(max_length=50, unique=True, db_index=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    VK_username = models.CharField(max_length=100, blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    birthday = models.DateField(blank=True, null=True)
    about = models.TextField(blank=True, null=True)
    gender = models.BooleanField()

    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    comment = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_event_at = models.DateTimeField(blank=True, null=True)
    
    # Кэшированная статистика
    total_event_count = models.IntegerField(default=0)
    season_event_count = models.IntegerField(default=0)
    total_hours = models.IntegerField(default=0)
    season_hours = models.IntegerField(default=0)

    objects = UserManager()

    USERNAME_FIELD = 'telegram_id'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'users'
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.telegram_id})"


class Manager(models.Model):
    """История выдачи и отзыва ролей менеджеров"""
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
    """История выдачи и отзыва ролей тим-лидеров"""
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
    """Юридические лица или структурные подразделения"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    events_count = models.IntegerField(default=0)
    volunteers_count = models.IntegerField(default=0)
    shifts_count = models.IntegerField(default=0)

    class Meta:
        db_table = 'organizations'
        verbose_name = 'Организация'
        verbose_name_plural = 'Организации'

    def __str__(self):
        return self.name


class Organizer(models.Model):
    """Контактные лица организаций"""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='organizer_profile')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    VK_username = models.CharField(max_length=100, blank=True, null=True)
    comments = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'organizers'
        verbose_name = 'Контактное лицо'
        verbose_name_plural = 'Контактные лица'

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class OrganizerOrganizationLink(models.Model):
    """Связь организатор-организация (Many-to-Many)"""
    id = models.AutoField(primary_key=True)
    organizer = models.ForeignKey(Organizer, on_delete=models.CASCADE, related_name='organization_links')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='organizer_links')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'organizer_organization_link'
        unique_together = ('organizer', 'organization')
        verbose_name = 'Связь организатора и организации'
        verbose_name_plural = 'Связи организаторов и организаций'


class Location(models.Model):
    """Справочник локаций"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'locations'
        verbose_name = 'Локация'
        verbose_name_plural = 'Локации'

    def __str__(self):
        return self.name


class EventCategory(models.Model):
    """Справочник категорий мероприятий"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'event_categories'
        verbose_name = 'Категория мероприятия'
        verbose_name_plural = 'Категории мероприятий'

    def __str__(self):
        return self.name


class Letters(models.Model):
    id = models.AutoField(primary_key=True)
    description = models.TextField(blank=True, null=True)
    path_to_pattern = models.TextField()


class CONST(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.TextField(blank=True, null=True)
    value = models.IntegerField()
    created_at = models.DateField()


class Event(models.Model):
    """Основная сущность события"""
    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'),
        ('ongoing', 'Ongoing'),
        ('finished', 'Finished'),
    ]
    RECRUIT_STATUS_CHOICES = [
        ('open', 'Open'),
        ('closed', 'Closed'),
    ]

    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    chat_link = models.URLField(blank=True, null=True)
    post_in_chanel_link = models.URLField(blank=True, null=True)
    dobro_ru_link = models.URLField(blank=True, null=True)
    
    event_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')
    recruit_status = models.CharField(max_length=20, choices=RECRUIT_STATUS_CHOICES, default='open')
    
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    organizer = models.ForeignKey(Organizer, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_events')
    
    created_at = models.DateTimeField(auto_now_add=True)
    people_helped = models.IntegerField(default=0)
    event_mark = models.SmallIntegerField()

    letter = models.ForeignKey(Letters, on_delete=models.SET_NULL, null=True, blank=True,)

    class Meta:
        db_table = 'events'
        verbose_name = 'Мероприятие'
        verbose_name_plural = 'Мероприятия'

    def __str__(self):
        return self.title


class EventCategoryMap(models.Model):
    """Связь мероприятий с категориями (Many-to-Many)"""
    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='category_map')
    category = models.ForeignKey(EventCategory, on_delete=models.CASCADE, related_name='event_map')

    class Meta:
        db_table = 'event_category_map'
        unique_together = ('event', 'category')
        verbose_name = 'Категория мероприятия (связь)'
        verbose_name_plural = 'Категории мероприятий (связи)'


class EventDay(models.Model):
    """Разбивка мероприятия на конкретные даты и временные слоты"""
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

    def __str__(self):
        return f"{self.event.title} - {self.day}"


class EventStaff(models.Model):
    """Назначение менеджеров и тим-лидеров на конкретные события"""
    ROLE_CHOICES = [
        ('manager', 'Manager'),
        ('team_lead', 'Team Lead'),
    ]

    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='staff')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='staff_assignments')
    staff_role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    assigned_at = models.DateTimeField(auto_now_add=True)
    churn_rate = models.SmallIntegerField(auto_created=0)

    class Meta:
        db_table = 'event_staff'
        verbose_name = 'Персонал мероприятия'
        verbose_name_plural = 'Персонал мероприятий'


class Application(models.Model):
    """Входящие запросы на участие. Могут быть от незарегистрированных пользователей."""
    
    STATUS_CHOICES = [
        ('new', 'New'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(
        Event, 
        on_delete=models.CASCADE, 
        related_name='applications'
    )
    # Связь с пользователем необязательна (null=True), так как заявка может быть от незарегистрированного человека
    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='applications'
    )
    
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    
    # Дополнительные поля из обновленного ТЗ
    functions = models.CharField(max_length=255, blank=True, null=True, help_text="Функция из формы заявки")
    shifts = models.CharField(max_length=255, blank=True, null=True, help_text="Смена из формы заявки")
    role_in_event = models.CharField(max_length=255, blank=True, null=True, help_text="Роль из формы заявки")
    user_status = models.CharField(max_length=100, blank=True, null=True, help_text="Статус обращающегося")
    
    created_in_hse_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    
    assigned_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='processed_applications',
        help_text="Кто обработал заявку"
    )

    class Meta:
        db_table = 'applications'
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'

    def __str__(self):
        return f"Application #{self.id} for {self.event.title}"



class Participation(models.Model):
    """Подтвержденные участия"""
    STATUS_CHOICES = [
        ('attended', 'Attended'),
        ('absent_excused', 'Absent Excused'),
        ('absent_unexcused', 'Absent Unexcused'),
    ]

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='participations')
    event_day = models.ForeignKey(EventDay, on_delete=models.CASCADE, related_name='participations')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='attended')
    hours = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'participations'
        verbose_name = 'Участие'
        verbose_name_plural = 'Участия'


class EventFeedback(models.Model):
    """Отзывы о мероприятии"""
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
    """Справочник требований к волонтерам"""
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
    """Связь требований с мероприятиями"""
    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='requirement_map')
    requirement = models.ForeignKey(EventRequirement, on_delete=models.CASCADE, related_name='event_map')

    class Meta:
        db_table = 'event_requirement_map'
        unique_together = ('event', 'requirement')
        verbose_name = 'Требование мероприятия (связь)'
        verbose_name_plural = 'Требования мероприятий (связи)'


class UserRequirementException(models.Model):
    """Исключения для волонтеров по требованиям"""
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


class Season(models.Model):
    """Периоды проведения ПГАС"""
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    start_season = models.DateField()
    end_season = models.DateField()

    class Meta:
        db_table = 'seasons'
        verbose_name = 'Сезон'
        verbose_name_plural = 'Сезоны'

    def __str__(self):
        return f"Season: {self.start_season} - {self.end_season}"
    

