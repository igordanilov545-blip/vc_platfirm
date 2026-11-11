import uuid
import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.utils import timezone
from blog.appearance import APPEARANCE_CHOICES, COLOR_THEME_CHOICES


CONTACT_METHOD_CHOICES = [
    ('any', 'Не принципиально'), ('telegram', 'Телеграм'), ('vk', 'ВК'),
    ('phone', 'Звонок'), ('max', 'Макс'), ('email', 'Почта'),
    ('sms', 'СМС'), ('whatsapp', 'Ватсап'), ('viber', 'Вайбер'),
]


def validate_contact_methods(value):
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in dict(CONTACT_METHOD_CHOICES) for item in value):
        raise ValidationError('Выберите способы связи из списка.')


def new_qr_token():
    """32 ASCII-байта (192 бита случайности), помещающиеся в QR version 2-L."""
    return secrets.token_urlsafe(24)


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
    CONTACT_METHOD_CHOICES = CONTACT_METHOD_CHOICES
    TSHIRT_SIZE_CHOICES = [(size, size) for size in ('XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL')]
    YES_NO_CHOICES = [(True, 'Да'), (False, 'Нет')]

    id = models.AutoField(primary_key=True)
    system_username = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    telegram_id = models.CharField(max_length=50, unique=True, db_index=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    VK_username = models.CharField(max_length=100, blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    birthday = models.DateField(blank=True, null=True)
    about = models.TextField(blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    instagram_url = models.CharField(max_length=255, blank=True, default='', verbose_name='Ссылка на вашу страницу в Инстаграме')
    preferred_contact_methods = models.JSONField(default=list, blank=True, validators=[validate_contact_methods], verbose_name='Наиболее удобный способ связи')
    weekday_daytime_available = models.BooleanField(null=True, blank=True, choices=YES_NO_CHOICES, verbose_name='Вы могли бы помогать нам в дневное время в будни?')
    volunteer_experience = models.CharField(max_length=255, blank=True, default='', verbose_name='Опыт волонтёрства')
    motivation = models.CharField(max_length=255, blank=True, default='', verbose_name='Мотивация быть волонтёром')
    familiar_positions = models.CharField(max_length=255, blank=True, default='', verbose_name='Знакомые позиции')
    performed_tasks = models.CharField(max_length=255, blank=True, default='', verbose_name='Выполняемые задачи')
    wants_team_lead = models.BooleanField(null=True, blank=True, choices=YES_NO_CHOICES, verbose_name='Желание стать тим-лидером')
    tshirt_size = models.CharField(max_length=4, blank=True, default='', choices=TSHIRT_SIZE_CHOICES, verbose_name='Размер футболки')

    @property
    def preferred_contacts_display(self):
        labels = dict(self.CONTACT_METHOD_CHOICES)
        return ', '.join(labels[item] for item in self.preferred_contact_methods if item in labels)

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
    total_event_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    season_event_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    season_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    churn_score = models.FloatField(default=0)

    # Веб-аутентификация (доп. канал входа).
    # Хеш пароля хранится в унаследованном от AbstractBaseUser поле `password`.
    login = models.CharField(max_length=50, unique=True, blank=True, null=True)
    web_credentials_set_at = models.DateTimeField(blank=True, null=True)

    # Подписка на уведомления бота о новых мероприятиях (Этап 8).
    notify_new_events = models.BooleanField(default=True)

    # Подписка ТЛ/менеджера на уведомления о новых заявках (db.md, правило 7c).
    # При false карточка новой заявки не приходит, но заявка остаётся видна в разделах меро/«Все заявки».
    notify_applications = models.BooleanField(default=True)

    appearance = models.CharField(max_length=32, choices=APPEARANCE_CHOICES, default='nexus')
    color_theme = models.CharField(max_length=10, choices=COLOR_THEME_CHOICES, default='system')

    # Флаг «Telegram подтверждён»: пользователь из личного кабинета нажал «Подтвердить
    # телеграм», открыл бота по deep-link и подтвердил «да, это мой аккаунт». Это
    # доказывает, что человек действительно владеет привязанным Telegram (в отличие от
    # ФИО/юзернейма, подтянутых из Excel-заявок). Ставится в blog.services.telegram_verify.
    telegram_verified = models.BooleanField(default=False)

    # Токен для публичной ссылки «Скопировать опыт» — открывает read-only блок
    # волонтёрского опыта без входа (раздел «Мой опыт»). Не угадывается перебором id.
    experience_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)

    # Верификация вручную менеджером ВЦ (НЕ то же самое, что telegram_verified —
    # там подтверждение владения Telegram через бота; здесь менеджер лично
    # удостоверяется в личности/данных человека, это условие для справки ПГАС).
    verified_by_manager_at = models.DateTimeField(blank=True, null=True)
    verified_by_manager_by = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    # Снимок верифицированных менеджером полей (ФИО/ОП/факультет/год/TG) на момент
    # верификации. Нужен, чтобы точно понять, изменил ли пользователь ИМЕННО
    # верифицируемые данные (а не просто пересохранил профиль): если текущие
    # значения разошлись со снимком — верификацию снимаем и просим менеджера
    # подтвердить заново (перевёлся на другую ОП и т.п.). См.
    # blog.services.pgas_certificate.VERIFIED_FIELDS / revoke_verification_if_changed.
    verified_snapshot = models.JSONField(blank=True, null=True)

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
        parts = [self.first_name or '', self.middle_name or '', self.last_name or '']
        joined = ' '.join(p for p in parts if p).strip()
        return joined or self.telegram_username or self.telegram_id

    @property
    def vk_profile_url(self):
        from blog.services.social_profiles import social_url
        return social_url(self.VK_username, 'vk')

    @property
    def instagram_profile_url(self):
        from blog.services.social_profiles import social_url
        return social_url(self.instagram_url, 'instagram')

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

    total_events = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    season_events = models.IntegerField(default=0, validators=[MinValueValidator(0)])

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

    total_events = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    season_events = models.IntegerField(default=0, validators=[MinValueValidator(0)])

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

    events_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    volunteers_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    shifts_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    internal_rating = models.SmallIntegerField(
        blank=True, null=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
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
    map_link = models.URLField(blank=True, null=True, verbose_name='Ссылка на карту')
    description = models.TextField(blank=True, null=True, verbose_name='Описание')

    class Meta:
        db_table = 'locations'
        verbose_name = 'Локация'
        verbose_name_plural = 'Локации'

    def __str__(self):
        return self.name


class EventCategory(models.Model):
    """Функция из общего пула («Дистанция», «Выдача стартовых пакетов»…).

    Таблица и связь с позициями прежние (event_categories / event_category_map);
    после решения 2026-11-11 «категории» — это переиспользуемые функции забегов,
    к которым в пуле привязаны типовые позиции (PositionTemplate)."""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'event_categories'
        verbose_name = 'Функция'
        verbose_name_plural = 'Функции'

    def __str__(self):
        return self.name


class PositionTemplate(models.Model):
    """Типовая позиция пула внутри функции — подсказка названия при создании позиции."""
    name = models.CharField(max_length=255)
    category = models.ForeignKey(EventCategory, on_delete=models.CASCADE, related_name='position_templates')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'position_templates'
        ordering = ['name', 'pk']
        constraints = [models.UniqueConstraint(fields=['category', 'name'], name='unique_position_template')]
        verbose_name = 'Позиция пула'
        verbose_name_plural = 'Позиции пула'

    def __str__(self):
        return self.name


class EventPerk(models.Model):
    """Справочник «плюшек» мероприятий — бонусов, которые получает волонтёр за участие
    (напр. «Мерч», «Питание», «Сертификат»). Полный аналог EventCategory: справочник в
    настройках + M2M-привязка к меро через EventPerkMap."""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'event_perks'
        verbose_name = 'Плюшка мероприятия'
        verbose_name_plural = 'Плюшки мероприятий'

    def __str__(self):
        return self.name


class DobroRuSharedLink(models.Model):
    """Общая ссылка на Добро.ру для нескольких мелких мероприятий сразу
    (db.md §dobro_ru_shared_links) — чтобы не заводить отдельную ссылку на каждое."""
    LINK_TYPE_CHOICES = [
        ('event', 'Мероприятие'),
        ('organization', 'Организация'),
        ('project', 'Проект'),
    ]

    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    url = models.URLField()
    link_type = models.CharField(max_length=20, choices=LINK_TYPE_CHOICES)
    period_hint = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dobro_ru_shared_links'
        verbose_name = 'Общая ссылка Добро.ру'
        verbose_name_plural = 'Общие ссылки Добро.ру'

    def __str__(self):
        return self.title


class LetterFont(models.Model):
    """Шрифт для конструктора благодарственных писем (letter-templates.md).

    Байты .ttf/.otf храним прямо в БД (BinaryField), как у PgasCertificateTemplate:
    в проекте нет MEDIA-хранилища/тома, а строка в Postgres переживает пересборку
    контейнера. Ключевой момент кросс-платформенности: PDF штампуется PyMuPDF с ЭТИМ
    файлом шрифта (fontfile из БД), а НЕ системным шрифтом ОС — поэтому вывод одинаков
    на Windows (локально) и Linux (прод), без установки шрифтов в систему.

    `is_builtin` — предустановленные шрифты (досоздаются лениво из static, см.
    blog.services.letter_render.ensure_builtin_fonts); их нельзя удалить из UI."""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    font_file = models.BinaryField()
    filename = models.CharField(max_length=255, blank=True, default='')
    is_builtin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'letter_fonts'
        verbose_name = 'Шрифт письма'
        verbose_name_plural = 'Шрифты писем'
        ordering = ['name']

    def __str__(self):
        return self.name


class ThankYouLetterTemplate(models.Model):
    """Шаблон благодарственного письма.

    Два режима (letter-templates.md):
    1. Конструктор поверх PDF (основной): менеджер загружает оформленный PDF-фон
       (`background_pdf`) и в браузере расставляет поверх него поля-заглушки (ФИО,
       мероприятие+дата, часы, организатор, свободный текст) — их конфигурация (позиция
       в % от страницы, размер рамки, шрифт, кегль, цвет, выравнивание) хранится в
       `fields_json`. При выдаче письма PyMuPDF штампует реальные значения в эти
       координаты поверх фона (blog.services.letter_render).
    2. Legacy-HTML (fallback): если фон не загружен — рендерится старый шаблон
       letter.html по title/description (обратная совместимость со старыми шаблонами).

    PDF-байты фона храним в БД (BinaryField) по той же причине, что и шрифты/справку
    ПГАС — нет MEDIA-тома, строка в Postgres переживает пересборку контейнера."""
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    pattern_link = models.TextField(blank=True, null=True)

    # Конструктор поверх PDF.
    background_pdf = models.BinaryField(null=True, blank=True)
    background_filename = models.CharField(max_length=255, blank=True, default='')
    # Размеры страницы фона в PDF-пунктах (1/72") — эталон для пересчёта относительных
    # координат полей (проценты) в абсолютные при штамповке.
    page_width_pt = models.FloatField(null=True, blank=True)
    page_height_pt = models.FloatField(null=True, blank=True)
    # Список полей: [{key, x, y, w, h, font_id, size, color, align}], координаты x/y/w/h —
    # в ДОЛЯХ [0..1] от ширины/высоты страницы (устойчивы к масштабу редактора).
    fields_json = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'thank_you_letter_templates'
        verbose_name = 'Шаблон благодарственного письма'
        verbose_name_plural = 'Шаблоны благодарственных писем'

    def __str__(self):
        return self.title

    @property
    def has_background(self) -> bool:
        return bool(self.background_pdf)


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


class PgasCertificateTemplate(models.Model):
    """Редактируемый менеджером шаблон справки ВЦ для ПГАС (по нему рендерятся все
    справки). Синглтон: значимо только `pk=1` (см.
    blog.services.pgas_certificate.get_template).

    Шаблон — это загруженный менеджером **Word-файл (.docx)**: так сохраняется
    конкретное оформление (шапка ВШЭ, шрифты, отступы). Внутри файла — плейсхолдеры
    `{full_name}`, `{faculty}`, гендерные `{student}`/`{participated}` и т.п., а
    также блок перечисления мероприятий между строками `### START EVENTS ###` и
    `### END EVENTS ###` (по нему идёт цикл). Байты docx храним прямо в БД
    (BinaryField): в проекте нет MEDIA-хранилища/тома, а singleton-строка в
    Postgres переживает пересборку контейнера — надёжнее FileField."""
    id = models.AutoField(primary_key=True)
    docx_file = models.BinaryField(null=True)
    filename = models.CharField(max_length=255, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        db_table = 'pgas_certificate_template'
        verbose_name = 'Шаблон справки ПГАС'
        verbose_name_plural = 'Шаблон справки ПГАС'

    def __str__(self):
        return f'Шаблон справки ПГАС (обновлён {self.updated_at:%d.%m.%Y})'


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


class RoleInvitation(models.Model):
    ROLE_CHOICES = [('team_lead', 'Тим-лидер'), ('manager', 'Менеджер')]
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_role_invitations')
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'role_invitations'
        ordering = ['-created_at', '-pk']


class RoleInvitationUse(models.Model):
    invitation = models.ForeignKey(RoleInvitation, on_delete=models.CASCADE, related_name='uses')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='role_invitation_uses')
    used_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'role_invitation_uses'
        constraints = [models.UniqueConstraint(fields=['invitation', 'user'], name='unique_role_invitation_user')]


class EventGroup(models.Model):
    """Мероприятие верхнего уровня: объединяет позиции, не меняя их заявки и смены."""
    title = models.CharField(max_length=255)
    # Ссылка Добро.ру — на мероприятии (решение 2026-11-11): все смены всех позиций
    # мероприятия учитываются по ней; при сохранении копируется в позиции.
    dobro_ru_link = models.URLField(blank=True, null=True)
    managers = models.ManyToManyField(User, blank=True, related_name='managed_event_groups')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_groups'
        verbose_name = 'Мероприятие'
        verbose_name_plural = 'Мероприятия'

    def __str__(self):
        return self.title


class Event(models.Model):
    """Основная сущность события.

    Набор заявок (recruit_status) и нужное количество волонтёров (volunteer_needed)
    живут на уровне смены (EventShift), а не мероприятия — у мероприятия из нескольких
    смен каждая смена сама решает, открыт у неё набор или нет. На Event остаётся только
    общий event_status жизненного цикла (upcoming/ongoing/passed/finished)."""
    # Имя Event и таблица events сохранены: заявки, бот и отчёты работают с позициями.
    event_group = models.ForeignKey(
        EventGroup, on_delete=models.PROTECT, null=True, blank=True,
        related_name='positions', verbose_name='Мероприятие',
    )
    STATUS_CHOICES = [
        ('upcoming', 'Предстоит'),
        ('ongoing', 'Идёт'),
        ('passed', 'Прошло'),
        ('finished', 'Завершено'),
    ]
    DOBRO_LINK_KIND_CHOICES = [
        ('none', 'Нет ссылки'),
        ('shared', 'Общая ссылка'),
        ('unique', 'Уникальная ссылка'),
    ]
    SCALE_CHOICES = [
        ('university', 'Университетское'),
        ('city', 'Городское'),
        ('russia', 'Всероссийское'),
        ('international', 'Международное'),
    ]

    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    chat_link = models.URLField(blank=True, null=True)
    post_in_chanel_link = models.URLField(blank=True, null=True)
    # Масштаб мероприятия — используется, среди прочего, для условий выдачи справки
    # ВЦ для ПГАС (какие мероприятия считаются "весомыми" для подтверждения).
    scale = models.CharField(max_length=20, choices=SCALE_CHOICES, blank=True, null=True)

    # Учёт часов на Добро.ру (db.md, правило 7e): none — не ведётся, unique — своя ссылка,
    # shared — общая ссылка на несколько мелких меро (DobroRuSharedLink).
    dobro_ru_link_kind = models.CharField(max_length=20, choices=DOBRO_LINK_KIND_CHOICES, default='none')
    dobro_ru_link = models.URLField(blank=True, null=True)
    dobro_ru_shared_link = models.ForeignKey(
        DobroRuSharedLink, on_delete=models.SET_NULL, null=True, blank=True, related_name='events'
    )
    dobro_ru_hours_logged = models.BooleanField(default=False)
    dobro_ru_logged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='dobro_ru_logged_events')

    event_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')

    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    organizer = models.ForeignKey(Organizer, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_events')

    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(blank=True, null=True)
    # Момент публикации поста в Telegram-канале — отдельно от published_at (анонс на
    # платформе), для графика тайминга заявок с двумя отсечками (db.md, reports.md).
    post_published_at = models.DateTimeField(blank=True, null=True)
    # Момент отправки рассылки-оповещения подписанным волонтёрам (кнопка «Сделать
    # рассылку» — отдельно от «Опубликовать»: публикация открывает подачу заявок,
    # рассылка лишь шлёт уведомления и может быть выполнена позже/повторно).
    broadcast_sent_at = models.DateTimeField(blank=True, null=True)
    # Токен для публичной («поделиться») ссылки на мероприятие — доступной без входа.
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    people_helped = models.IntegerField(blank=True, null=True, validators=[MinValueValidator(0)])
    internal_comment = models.TextField(blank=True, null=True)

    letter = models.ForeignKey(ThankYouLetterTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')

    class Meta:
        db_table = 'events'
        verbose_name = 'Позиция'
        verbose_name_plural = 'Позиции'

    def __str__(self):
        return self.title

    def compute_status(self):
        """Статус мероприятия по датам смен (`shifts`), а не по хранимому полю:

        - «Завершено» — только если мероприятие явно закрыто менеджером кнопкой «Завершить»
          (event_status='finished', см. views.event_close). Это единственное ручное
          состояние — автоматика по датам его не выставляет и не может отменить.
        - «Идёт» — хотя бы одна смена мероприятия приходится на сегодняшнюю дату.
        - «Прошло» — последняя смена раньше сегодняшней даты, но менеджер ещё не закрыл
          мероприятие явно (даты кончились, а чеклист закрытия не пройден).
        - «Предстоит» — первая смена позже сегодняшней даты.
        - Если у мероприятия ещё нет смен — используем хранимое `event_status` как есть
          (обычно 'upcoming' сразу после создания).
        """
        if self.event_status == 'finished':
            return 'finished'

        shifts = list(self.shifts.all()) if self.pk else []
        if not shifts:
            return self.event_status

        today = timezone.localdate()
        shift_dates = [s.day for s in shifts]
        first_day, last_day = min(shift_dates), max(shift_dates)

        if today in shift_dates:
            return 'ongoing'
        if last_day < today:
            return 'passed'
        if first_day > today:
            return 'upcoming'
        # Между первой и последней сменой, но сегодняшней даты среди смен нет
        # (напр. многодневное меро с "окном" без активности сегодня) — считаем идущим.
        return 'ongoing'

    def compute_status_display(self):
        return dict(self.STATUS_CHOICES).get(self.compute_status(), self.compute_status())

    def close_recruit_if_passed(self):
        """Автоматически закрывает набор на все ещё открытые смены, если мероприятие уже
        прошло/завершено — подать заявку на прошедшее меро бессмысленно. Вызывается лениво
        в местах просмотра/выбора мероприятия (нет отдельного планировщика задач).
        Возвращает True, если хотя бы одна смена была закрыта."""
        if self.compute_status() not in ('passed', 'finished'):
            return False
        updated = self.shifts.filter(recruit_status='open').update(recruit_status='closed')
        return updated > 0


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


class EventPerkMap(models.Model):
    """Связь мероприятий с плюшками (Many-to-Many). Полный аналог EventCategoryMap."""
    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='perk_map')
    perk = models.ForeignKey(EventPerk, on_delete=models.CASCADE, related_name='event_map')

    class Meta:
        db_table = 'event_perk_map'
        unique_together = ('event', 'perk')
        verbose_name = 'Плюшка мероприятия (связь)'
        verbose_name_plural = 'Плюшки мероприятий (связи)'


class EventShift(models.Model):
    """Смена мероприятия: конкретная дата и временной слот со своим набором заявок.

    Мероприятие может состоять из нескольких смен (в один день или в разные дни) —
    у каждой смены свой recruit_status/volunteer_needed, но тим-лидеры, менеджеры,
    организаторы и т.д. полностью наследуются от мероприятия целиком."""
    RECRUIT_STATUS_CHOICES = [
        ('open', 'Открыт'),
        ('closed', 'Закрыт'),
    ]

    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='shifts')
    day = models.DateField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    volunteer_needed = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    recruit_status = models.CharField(max_length=20, choices=RECRUIT_STATUS_CHOICES, default='open')
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='event_shifts')
    # План ролей смены (2026-11-11): [[роль, сколько], …] — уточнение «сколько людей
    # куда», подсказка без ограничений. По умолчанию 1 тим-лидер + остальные волонтёры.
    role_plan = models.JSONField(default=list, blank=True)

    # Отметка «можно забирать» (визуальный индикатор для менеджера, db.md/reports.md):
    # тим-лидер/менеджер этого меро подтверждает, что явка и часы по смене актуализированы
    # и данные можно забирать (напр. для отчётности). Доступна только для прошедших смен —
    # до этого момента актуализировать явку ещё нечего.
    attendance_confirmed = models.BooleanField(default=False)
    attendance_confirmed_at = models.DateTimeField(blank=True, null=True)
    attendance_confirmed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_shifts'
    )

    class Meta:
        db_table = 'event_shifts'
        verbose_name = 'Смена мероприятия'
        verbose_name_plural = 'Смены мероприятий'
        indexes = [
            models.Index(fields=['event']),
        ]

    def __str__(self):
        return f"{self.event.title} - {self.day}"

    @property
    def time_unknown(self):
        return self.start_time == self.end_time

    @property
    def date_unknown(self):
        if self.day.isoformat() != '2026-01-01':
            return False
        from blog.services.legacy_workbook import column_day
        source = getattr(self, 'legacy_source', None)
        return bool(source and column_day(source.source_header) is None)

    def compute_status(self):
        """Статус смены по датам (независимо от общего статуса мероприятия):
        idёт/предстоит/прошла — используется для подсветки строк в таблицах смен."""
        today = timezone.localdate()
        if self.day == today:
            return 'ongoing'
        if self.day < today:
            return 'passed'
        return 'upcoming'


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


class EventDirection(models.Model):
    """Направление FaP внутри мероприятия; не новая бизнес-роль."""
    event_group = models.ForeignKey(EventGroup, on_delete=models.CASCADE, related_name='directions')
    source_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=500)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'event_directions'
        ordering = ['sort_order', 'pk']


class SheetPosition(models.Model):
    """Привязка позиции к направлению и стабильному ID таблицы."""
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name='sheet_position')
    direction = models.ForeignKey(EventDirection, on_delete=models.PROTECT, related_name='positions')
    source_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sort_order = models.PositiveIntegerField(default=0)
    is_team_lead_role = models.BooleanField(default=False)

    class Meta:
        db_table = 'sheet_positions'
        ordering = ['sort_order', 'pk']


class SheetPositionDay(models.Model):
    """Исходный план дня, включая нули, пустоты и пока нераспознанные интервалы."""
    position = models.ForeignKey(SheetPosition, on_delete=models.CASCADE, related_name='days')
    day = models.DateField()
    raw_work_time = models.TextField(null=True, blank=True)
    raw_checkin_out = models.TextField(null=True, blank=True)
    quantities = models.JSONField(default=list)

    class Meta:
        db_table = 'sheet_position_days'
        constraints = [models.UniqueConstraint(fields=['position', 'day'], name='unique_sheet_position_day')]
        ordering = ['day', 'pk']


class SheetShift(models.Model):
    """Плановые check-in/out отделены от фактических отметок ShiftAttendance."""
    shift = models.OneToOneField(EventShift, on_delete=models.CASCADE, related_name='sheet_shift')
    position_day = models.ForeignKey(SheetPositionDay, on_delete=models.CASCADE, related_name='shifts')
    source_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    label = models.CharField(max_length=100, blank=True)
    planned_count = models.PositiveIntegerField(null=True, blank=True)
    checkin = models.DateTimeField(null=True, blank=True)
    checkout = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'sheet_shifts'
        ordering = ['sort_order', 'pk']


class SheetTeamLeader(models.Model):
    direction = models.ForeignKey(EventDirection, on_delete=models.CASCADE, related_name='team_leaders')
    position = models.ForeignKey(SheetPosition, on_delete=models.CASCADE, null=True, blank=True, related_name='team_leaders')
    display_name = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sheet_lead_assignments')
    sort_order = models.PositiveIntegerField(default=0)
    staff_links = models.ManyToManyField(EventStaff, blank=True, related_name='sheet_sources')

    class Meta:
        db_table = 'sheet_team_leaders'
        ordering = ['sort_order', 'pk']


class ZoneResponsible(models.Model):
    """Ответственный за зону из колонки D; не Manager платформы и не ACL."""
    direction = models.ForeignKey(EventDirection, on_delete=models.CASCADE, related_name='responsibles')
    position = models.ForeignKey(SheetPosition, on_delete=models.CASCADE, null=True, blank=True, related_name='responsibles')
    display_name = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='zone_assignments')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'zone_responsibles'
        ordering = ['sort_order', 'pk']


class EventSheetLink(models.Model):
    event_group = models.OneToOneField(EventGroup, on_delete=models.CASCADE, related_name='sheet_link')
    spreadsheet_id = models.CharField(max_length=128, blank=True)
    sheet_id = models.PositiveIntegerField(null=True, blank=True)
    source_name = models.CharField(max_length=255, blank=True)
    template = models.BinaryField(blank=True, default=bytes)
    source_hash = models.CharField(max_length=64, blank=True)
    baseline = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'event_sheet_links'

    @property
    def google_url(self):
        if not self.spreadsheet_id:
            return ''
        return f'https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit' + (f'#gid={self.sheet_id}' if self.sheet_id is not None else '')


class GoogleSheetsConnection(models.Model):
    """Один ключ интеграции, зашифрованный отдельным назначением SECRET_KEY."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    credentials_encrypted = models.TextField(editable=False)
    client_email = models.EmailField()
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'google_sheets_connection'


class Application(models.Model):
    """Входящие запросы на участие. Могут быть от незарегистрированных пользователей."""

    STATUS_CHOICES = [
        ('new', 'Новая'),
        ('approved', 'Одобрена'),
        ('rejected', 'Отклонена/резерв'),
        ('cancelled', 'Отменена волонтёром'),
    ]

    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='applications')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='applications')

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)

    functions = models.CharField(max_length=255, blank=True, null=True)
    # Человекочитаемая сводка смен — как раньше, для совместимости с Excel-импортом
    # (db.md: колонка "Смена"), заполняется автоматически из selected_shifts при подаче с сайта.
    shifts = models.CharField(max_length=255, blank=True, null=True)
    # Реальная связь с конкретными сменами меро (выбор чипами на веб-форме подачи заявки) —
    # используется при approve, чтобы создать participations только по выбранным сменам,
    # а не по всем сменам меро. Пусто у заявок из Excel-импорта (там только текст в `shifts`).
    selected_shifts = models.ManyToManyField(EventShift, blank=True, related_name='applications')
    role_in_event = models.CharField(max_length=255, blank=True, null=True)
    user_status = models.CharField(max_length=100, blank=True, null=True)

    submitted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')

    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_applications')

    # Отмена заявки самим волонтёром (веб) — доступна только пока до мероприятия
    # осталось больше const.late_cancel_hours; причина обязательна.
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancel_reason = models.TextField(blank=True, null=True)

    # Если заявка при подаче автоматически ушла в резерв из-за несоответствия
    # требованиям меро (blog.services.requirements) — здесь человекочитаемая причина
    # (для менеджера/ТЛ на странице меро); пусто, если решение было обычным ручным.
    auto_reject_reason = models.TextField(blank=True, null=True)

    # «Что делал» в колонке единой таблицы «Опыт и заявки» профиля (profile_detail.html) —
    # свободный текст, который менеджер вписывает постфактум; НЕ то же самое, что
    # `functions` (роль/функция, указанная волонтёром при подаче заявки).
    profile_note = models.CharField(max_length=255, blank=True, null=True, verbose_name='Что делал')

    # Когда одобренному волонтёру уже отправлены ссылка на чат меро и ссылка на Добро.ру
    # (в отбивке об одобрении). Отслеживаем раздельно, потому что менеджер часто
    # заполняет их не сразу: при одобрении шлём те ссылки, что уже заданы, и ставим
    # соответствующую отметку; недостающие досылаются позже — при сохранении меро, как
    # только менеджер их впишет (blog.services.notifications.send_pending_approval_links).
    # Так волонтёр не получает одну и ту же ссылку дважды.
    chat_link_sent_at = models.DateTimeField(blank=True, null=True)
    dobro_link_sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'applications'
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'
        indexes = [
            models.Index(fields=['event', 'status']),
        ]

    def __str__(self):
        return f"Application #{self.id} for {self.event.title}"


class ApplicationShiftDecision(models.Model):
    """Решение (одобрить/резерв) по заявке — ОТДЕЛЬНО на каждую смену, если заявка
    подана сразу на несколько (`Application.selected_shifts`). Нужно, чтобы принять/
    отклонить заявку на одну смену не затрагивало статус той же заявки на другие
    смены — раньше был единственный общий `Application.status` на все смены сразу."""
    STATUS_CHOICES = [
        ('new', 'Новая'),
        ('approved', 'Одобрена'),
        ('rejected', 'Отклонена/резерв'),
    ]

    id = models.AutoField(primary_key=True)
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='shift_decisions')
    shift = models.ForeignKey(EventShift, on_delete=models.CASCADE, related_name='application_decisions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    assigned_at = models.DateTimeField(blank=True, null=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_shift_decisions')
    # Роль человека в смене (2026-11-11): подсказка для планирования, без ограничений —
    # ключевое по-прежнему количество людей. Тим-лидеры получают её автоматически.
    role = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'application_shift_decisions'
        unique_together = ('application', 'shift')
        verbose_name = 'Решение по смене заявки'
        verbose_name_plural = 'Решения по сменам заявок'


class ApplicationChangeLog(models.Model):
    """Лента изменений заявок мероприятия — заполняется при повторном Excel-импорте:
    заявка идентифицируется как (человек, мероприятие), повторная загрузка не создаёт
    дубль, а ОБНОВЛЯЕТ существующую запись, и здесь фиксируется, что именно изменилось
    ('этот изменил заявку с такого-то наполнения на такое', 'этот отказался', 'эти
    появились'). Тим-лидер/менеджер отмечает ленту прочитанной кнопкой — очищается
    целиком. После завершения мероприятия лента больше не показывается (не очищается
    физически, просто скрыта в UI — see event_detail context: is_finished)."""
    KIND_CHOICES = [
        ('changed', 'Изменена'),
        ('withdrawn', 'Отозвана'),
        ('new', 'Новая'),
    ]

    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='application_change_logs')
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='change_logs', null=True, blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'application_change_logs'
        verbose_name = 'Запись об изменении заявки'
        verbose_name_plural = 'Записи об изменениях заявок'
        ordering = ['-created_at']


class Participation(models.Model):
    """Подтвержденные участия."""
    STATUS_CHOICES = [
        ('pending', 'Не отмечен'),
        ('attended', 'Присутствовал'),
        ('absent_excused', 'Отсутствовал (уважительно)'),
        ('absent_unexcused', 'Отсутствовал (без предупреждения)'),
    ]

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='participations')
    event_day = models.ForeignKey(EventShift, on_delete=models.CASCADE, related_name='participations')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    # Отработал ли волонтёр полную смену (db.md, правило 7a) — не влияет на часы,
    # отдельная отметка добросовестного участия, проставляется тим-лидером вместе со статусом.
    full_shift = models.BooleanField(default=False)
    hours = models.DecimalField(max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    # Часы проставлены/изменены вручную тим-лидером (а не автоматически из длительности
    # смены). Если True — автоматический пересчёт часов при изменении времени смены их
    # НЕ перезаписывает (ручная корректировка приоритетнее).
    hours_overridden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Отметка, что запрос "оцени мероприятие" уже отправлен (tg-bot.md §4.6) —
    # чтобы фоновая задача не слала его повторно при каждом проходе.
    feedback_requested_at = models.DateTimeField(blank=True, null=True)

    # Ручная простановка часов на Добро.ру менеджером (db.md, правило 7e) — построчно по волонтёру.
    dobro_ru_logged = models.BooleanField(default=False)
    dobro_ru_logged_at = models.DateTimeField(blank=True, null=True)
    dobro_ru_logged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='dobro_ru_logged_participations'
    )

    class Meta:
        db_table = 'participations'
        verbose_name = 'Участие'
        verbose_name_plural = 'Участия'
        indexes = [
            models.Index(fields=['user', 'event_day']),
        ]


class UserQRCode(models.Model):
    """Постоянный личный QR; токен загружается только при запросе самого QR/сканировании."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='personal_qr')
    token = models.CharField(max_length=32, unique=True, default=new_qr_token, editable=False)

    class Meta:
        db_table = 'user_qr_codes'


class ScannerGrant(models.Model):
    """Отдельное право отмечать вход/выход на мероприятии, без выдачи роли ТЛ."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scanner_grants')
    event_group = models.ForeignKey(EventGroup, on_delete=models.CASCADE, related_name='scanner_grants')
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    assigned_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'qr_scanner_grants'
        constraints = [models.UniqueConstraint(fields=['user', 'event_group'], condition=models.Q(revoked_at__isnull=True), name='one_active_scanner_grant')]


class ShiftAttendance(models.Model):
    """Вход/выход; после снятия входа остаётся строка с пустыми отметками."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shift_attendance')
    shift = models.ForeignKey(EventShift, on_delete=models.CASCADE, related_name='qr_attendance')
    entered_at = models.DateTimeField(default=timezone.now, null=True, blank=True)
    exited_at = models.DateTimeField(null=True, blank=True)
    entered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    exited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        db_table = 'shift_attendance'
        constraints = [
            models.UniqueConstraint(fields=['user', 'shift'], name='one_attendance_per_user_shift'),
            models.CheckConstraint(condition=models.Q(exited_at__isnull=True) | (models.Q(entered_at__isnull=False) & models.Q(exited_at__gte=models.F('entered_at'))), name='attendance_exit_after_entry'),
        ]


class ShiftMeal(models.Model):
    """Один выданный обед на человека и смену."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shift_meals')
    shift = models.ForeignKey(EventShift, on_delete=models.CASCADE, related_name='meal_issues')
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        db_table = 'shift_meals'
        constraints = [models.UniqueConstraint(fields=['user', 'shift'], name='one_meal_per_user_shift')]


class EventBadge(models.Model):
    """Один значок на мероприятие, независимо от позиций и смен человека."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_badges')
    event_group = models.ForeignKey(EventGroup, on_delete=models.CASCADE, related_name='badge_issues')
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        db_table = 'event_badges'
        constraints = [models.UniqueConstraint(fields=['user', 'event_group'], name='one_badge_per_user_group')]


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


class ChurnLog(models.Model):
    """Журнал КАЖДОГО изменения churn_score пользователя (в отличие от ChurnHistory —
    снимка на конец сезона). Пишется во всех точках, где меняется churn: неявка без
    предупреждения (штраф), списание за активность, сброс/carryover по сезону, ручная
    блокировка/разблокировка менеджером. Показывается в профиле менеджеру как
    «История чарна»."""
    REASON_CHOICES = [
        ('no_show', 'Неявка без предупреждения'),
        ('activity_decay', 'Списание за активность'),
        ('season_reset', 'Сброс по завершении сезона'),
        ('blacklist', 'Блокировка менеджером'),
        ('unblacklist', 'Вывод из чёрного списка'),
        ('manual', 'Ручная корректировка'),
    ]

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='churn_log')
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    delta = models.FloatField(help_text='Изменение churn_score (может быть отрицательным)')
    new_value = models.FloatField(help_text='Значение churn_score после изменения')
    # Кто инициировал (для ручных действий менеджера); авто-события — без actor.
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='caused_churn_changes')
    # Опциональный контекст (напр. мероприятие, из-за которого неявка).
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='churn_log_entries')
    note = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'churn_log'
        verbose_name = 'Изменение чарна'
        verbose_name_plural = 'История изменений чарна'
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f'ChurnLog user={self.user_id} {self.reason} {self.delta:+.2f}→{self.new_value:.2f}'


class EventComment(models.Model):
    """Внутренние комментарии к мероприятию от менеджеров/тим-лидеров (не путать
    с Event.internal_comment — то одно поле для заметок, а это лента реплик от
    разных авторов). В UI показываются без подписи автора — только текст и дата."""
    id = models.AutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='authored_event_comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_comments'
        verbose_name = 'Комментарий к мероприятию'
        verbose_name_plural = 'Комментарии к мероприятиям'
        ordering = ['created_at']


class UserComment(models.Model):
    """Внутренние комментарии к волонтёрам от менеджеров/тим-лидеров."""
    id = models.AutoField(primary_key=True)
    target_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_comments')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='authored_comments')
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_comments')
    text = models.TextField()
    source = models.CharField(max_length=32, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def source_label(self):
        return {'legacy_coordinator': 'Комментарий координатора (старая база)',
                'legacy_team_lead': 'Комментарий тим-лидера (старая база)',
                'legacy_changes': 'Изменения данных по старым базам'}.get(self.source, '')

    class Meta:
        db_table = 'user_comments'
        verbose_name = 'Комментарий к волонтёру'
        verbose_name_plural = 'Комментарии к волонтёрам'


class LegacyImportIdentity(models.Model):
    """Отпечаток контактов/ФИО для повторного импорта; VOLUNTEER_ID не используется."""
    key = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='legacy_identities')
    reported_age = models.PositiveSmallIntegerField(null=True, blank=True)
    imported_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'legacy_import_identities'


class LegacyImportShift(models.Model):
    """Источник исторической смены; неизвестное время — равные границы, ноль часов."""
    key = models.CharField(max_length=64, unique=True)
    shift = models.OneToOneField(EventShift, on_delete=models.CASCADE, related_name='legacy_source')
    source_header = models.TextField()

    class Meta:
        db_table = 'legacy_import_shifts'


class LegacyBase(models.Model):
    """Файл старой базы (одна база = один год). Хранится целиком: MEDIA-тома нет."""
    year = models.PositiveSmallIntegerField()
    file_name = models.CharField(max_length=255)
    content = models.BinaryField()
    content_hash = models.CharField(max_length=64, unique=True)
    parsed = models.JSONField(default=dict)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    people_loaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'legacy_bases'
        ordering = ['-year', '-pk']


class LegacyBaseColumn(models.Model):
    """Колонка «мероприятие + день» базы; дату и мероприятие задаёт человек."""
    base = models.ForeignKey(LegacyBase, on_delete=models.CASCADE, related_name='columns')
    index = models.PositiveIntegerField()
    header = models.TextField()
    title_hint = models.CharField(max_length=255, blank=True)
    day = models.DateField(null=True, blank=True)
    event_group = models.ForeignKey(EventGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='legacy_columns')
    skipped = models.BooleanField(default=False)
    loaded_at = models.DateTimeField(null=True, blank=True)
    value_counts = models.JSONField(default=dict)
    fap_document = models.ForeignKey('FapDocument', on_delete=models.SET_NULL, null=True, blank=True, related_name='columns')

    @property
    def header_line(self):
        """Заголовок колонки в одну строку — для сводок и подсказок."""
        return ' '.join(self.header.split())

    class Meta:
        db_table = 'legacy_base_columns'
        ordering = ['base', 'index']
        constraints = [models.UniqueConstraint(fields=['base', 'index'], name='unique_legacy_base_column')]


class LegacyBasePerson(models.Model):
    """Строка базы → аккаунт; из этого видно, в каких годах человек встречался."""
    base = models.ForeignKey(LegacyBase, on_delete=models.CASCADE, related_name='people')
    row_number = models.PositiveIntegerField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='legacy_base_rows')

    class Meta:
        db_table = 'legacy_base_people'
        constraints = [models.UniqueConstraint(fields=['base', 'row_number'], name='unique_legacy_base_person')]


class FapDocument(models.Model):
    """Загруженный файл ФиП. Пока не привязан к мероприятию — лежит в библиотеке
    (event_group пуст, version 0); при привязке получает номер версии в мероприятии."""
    event_group = models.ForeignKey(EventGroup, on_delete=models.CASCADE, null=True, blank=True, related_name='fap_documents')
    version = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255, blank=True)
    plan = models.JSONField(default=dict)
    file_name = models.CharField(max_length=255)
    content = models.BinaryField()
    content_hash = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    warnings = models.JSONField(default=list)

    class Meta:
        db_table = 'fap_documents'
        ordering = ['event_group', '-version']
        constraints = [models.UniqueConstraint(fields=['event_group', 'version'], name='unique_fap_document_version')]


class LegacyValueMapping(models.Model):
    """Уникальное значение ячеек мероприятия → позиция и роль, либо «пропустить»."""
    ROLE_CHOICES = [('volunteer', 'Волонтёр'), ('team_lead', 'Тим-лидер')]
    event_group = models.ForeignKey(EventGroup, on_delete=models.CASCADE, related_name='legacy_value_mappings')
    value_key = models.CharField(max_length=255)
    raw_value = models.CharField(max_length=500)
    position = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='legacy_value_mappings')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='volunteer')
    skip = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'legacy_value_mappings'
        constraints = [models.UniqueConstraint(fields=['event_group', 'value_key'], name='unique_legacy_value_mapping')]


class LegacyLoadedCell(models.Model):
    """Происхождение записей из ячейки базы: повтор без дублей, перенос и откат."""
    column = models.ForeignKey(LegacyBaseColumn, on_delete=models.CASCADE, related_name='loaded_cells')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='legacy_loaded_cells')
    value_key = models.CharField(max_length=255)
    position = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    shift = models.ForeignKey(EventShift, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    application = models.ForeignKey(Application, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    participation = models.ForeignKey(Participation, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    staff = models.ForeignKey(EventStaff, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'legacy_loaded_cells'
        constraints = [models.UniqueConstraint(fields=['column', 'user'], name='unique_legacy_loaded_cell')]


class MigrationJob(models.Model):
    """Фоновая загрузка миграции (люди базы или колонки) с прогрессом и отменой.

    Celery нет: задача идёт в отдельном потоке веб-процесса, состояние — в БД,
    чтобы страница могла показывать процент, а пользователь — уходить на другие."""
    KIND_CHOICES = [('people', 'Люди базы'), ('columns', 'Колонки')]
    STATUS_CHOICES = [('running', 'Идёт'), ('done', 'Готово'), ('cancelled', 'Отменено'), ('failed', 'Ошибка')]
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    base = models.ForeignKey(LegacyBase, on_delete=models.CASCADE, null=True, blank=True, related_name='jobs')
    event_group = models.ForeignKey(EventGroup, on_delete=models.CASCADE, null=True, blank=True, related_name='migration_jobs')
    column_ids = models.JSONField(default=list)
    total = models.PositiveIntegerField(default=0)
    done = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)
    result = models.JSONField(default=dict)
    cancel_requested = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'migration_jobs'
        ordering = ['-pk']


class ProfileConflict(models.Model):
    """Расхождение анкеты, заполненной человеком, с загруженной базой.

    Профиль не перезаписывается молча: при входе пользователь выбирает актуальное
    значение (своё, из базы или вводит новое)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_conflicts')
    field = models.CharField(max_length=50)
    current_value = models.TextField(blank=True)
    proposed_value = models.TextField()
    source = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    chosen_value = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'profile_conflicts'
        ordering = ['pk']


class Incident(models.Model):
    """Пункт раздела «Главное» менеджера — что-то, требующее внимания или решения
    (коллизия Telegram-аккаунтов, идущее/скоро начинающееся мероприятие, запрос
    верификации для справки ПГАС и т.п.). Список работает как чек-лист: менеджер
    отмечает пункт решённым (resolved_at), и он пропадает из списка активных."""
    KIND_CHOICES = [
        ('tg_collision', 'Коллизия Telegram-аккаунта'),
        ('event_ongoing', 'Мероприятие идёт/скоро начнётся'),
        ('pgas_verification', 'Требуется верификация для справки ПГАС'),
    ]

    id = models.AutoField(primary_key=True)
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    text = models.TextField()
    related_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    related_event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'incidents'
        verbose_name = 'Инцидент'
        verbose_name_plural = 'Инциденты'
        indexes = [
            models.Index(fields=['kind', 'resolved_at']),
        ]

    def __str__(self):
        return f'{self.get_kind_display()}: {self.text[:50]}'


class EventFeedback(models.Model):
    """Отзывы о мероприятии."""
    id = models.AutoField(primary_key=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feedbacks')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='feedbacks')
    rating = models.SmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(10)])  # 0-10
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_feedbacks'
        verbose_name = 'Отзыв'
        verbose_name_plural = 'Отзывы'


class EventRequirement(models.Model):
    """Справочник требований к волонтерам (напр. «18+», «Уверенное владение русским
    языком»). Исходим из того, что ВСЕ волонтёры по умолчанию соответствуют ВСЕМ
    требованиям — несоответствие фиксируется явно, точечно (см. UserRequirementException),
    белым списком «кто НЕ соответствует», а не наоборот.

    CHECK_TYPE_CHOICES:
    - 'manual' — соответствие/несоответствие проставляет менеджер вручную в профиле
      волонтёра (UserRequirementException). Так для большинства требований.
    - 'age' — проверяется автоматически по `users.birthday` при подаче заявки (см.
      blog.services.requirements.check_application_requirements). Ровно одно требование
      в системе должно иметь этот тип — «18+»; проверка не завязана на конкретный title,
      чтобы менеджер мог переименовать требование, не ломая логику."""
    CHECK_TYPE_CHOICES = [
        ('manual', 'Вручную (менеджер отмечает исключения)'),
        ('age', 'Автоматически по дате рождения (18+)'),
    ]

    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    check_type = models.CharField(max_length=20, choices=CHECK_TYPE_CHOICES, default='manual')

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
    # Если задано — к сообщению прикрепляется inline-кнопка «Подать заявку» на это меро
    # (используется рассылкой о новом мероприятии, чтобы сразу предложить откликнуться).
    apply_event = models.ForeignKey(
        Event, on_delete=models.CASCADE, null=True, blank=True, related_name='outbox_messages'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'bot_outbox'
        verbose_name = 'Исходящее сообщение бота'
        verbose_name_plural = 'Исходящие сообщения бота'
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]


class SystemDowntime(models.Model):
    """Ручная отметка периода простоя (техадмин заполняет через админку/команду) —
    рисуется как красная («сбой») или жёлтая («плановое отключение») зона на графиках
    онлайна дашборда аналитики. Нет автоматического мониторинга аптайма — источник
    правды здесь исключительно человек, который знает, что реально произошло."""
    KIND_CHOICES = [('crash', 'Сбой'), ('planned', 'Плановое отключение')]

    id = models.AutoField(primary_key=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='crash')
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(db_index=True)
    comment = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'analytics_system_downtimes'
        verbose_name = 'Простой системы'
        verbose_name_plural = 'Простои системы'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['started_at', 'ended_at']),
        ]

    def __str__(self):
        return f'{self.get_kind_display()}: {self.started_at:%d.%m %H:%M} — {self.ended_at:%d.%m %H:%M}'


class WebSession(models.Model):
    """Одна вкладка/сессия веб-пользователя — источник для графика «онлайн по минутам»
    и для расчёта времени, проведённого на страницах (см. documentation по аналитике).
    Обновляется middleware `ActivityTrackingMiddleware` и heartbeat-запросами с фронта.
    """
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='web_sessions')
    session_key = models.CharField(max_length=100, db_index=True)
    role_snapshot = models.CharField(max_length=20, default='volunteer')
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_seen_at = models.DateTimeField(db_index=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'analytics_web_sessions'
        verbose_name = 'Веб-сессия'
        verbose_name_plural = 'Веб-сессии'
        indexes = [
            models.Index(fields=['last_seen_at']),
            models.Index(fields=['session_key']),
        ]


class WebPageView(models.Model):
    """Один просмотр страницы: время ответа сервера (`load_ms`) и время, проведённое
    пользователем на странице (`duration_ms`, обновляется heartbeat/beacon с фронта)."""
    id = models.AutoField(primary_key=True)
    session = models.ForeignKey(WebSession, on_delete=models.CASCADE, related_name='page_views')
    path = models.CharField(max_length=255, db_index=True)
    view_name = models.CharField(max_length=100, blank=True, db_index=True)
    load_ms = models.IntegerField(null=True, blank=True)
    entered_at = models.DateTimeField(auto_now_add=True, db_index=True)
    duration_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'analytics_web_page_views'
        verbose_name = 'Просмотр страницы'
        verbose_name_plural = 'Просмотры страниц'
        indexes = [
            models.Index(fields=['entered_at']),
            models.Index(fields=['view_name']),
        ]


class ButtonClickEvent(models.Model):
    """Клик по кнопке/команде — общий журнал для веба и Telegram-бота (различаются
    полем `source`). `action_key` — машиночитаемый идентификатор для группировки на
    графике, `label` — человекочитаемая подпись для легенды."""
    SOURCE_CHOICES = [('web', 'Веб'), ('bot', 'Telegram-бот')]

    id = models.AutoField(primary_key=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    web_session = models.ForeignKey(
        'WebSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='click_events'
    )
    role_snapshot = models.CharField(max_length=20, default='volunteer', db_index=True)
    action_key = models.CharField(max_length=150, db_index=True)
    label = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'analytics_button_clicks'
        verbose_name = 'Клик по кнопке'
        verbose_name_plural = 'Клики по кнопкам'
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['source', 'role_snapshot', 'created_at']),
        ]


class BotSessionPing(models.Model):
    """Heartbeat активности в Telegram-боте — создаётся на каждый апдейт (сообщение
    или callback) от пользователя, источник для графика «онлайн по минутам» бота."""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'analytics_bot_pings'
        verbose_name = 'Пинг активности бота'
        verbose_name_plural = 'Пинги активности бота'
        indexes = [
            models.Index(fields=['created_at']),
        ]


class PendingButtonRemoval(models.Model):
    """Очередь на снятие inline-клавиатуры у отправленных ботом сообщений.

    Любое сообщение бота с inline-кнопками (подать заявку, одобрить/резерв, оценка
    и т.д.) должно "остывать" — кнопки не должны быть нажимаемы бесконечно (пользователь
    иначе может нажать на кнопку многомесячной давности с уже неактуальным состоянием).
    При отправке такого сообщения хендлер создаёт здесь запись с `remove_at = now + N`;
    периодический обходчик в `tg_bot/notifier.py` (тот же цикл, что и `bot_outbox`/feedback)
    снимает разметку (`edit_message_reply_markup(reply_markup=None)`) и удаляет запись.
    Переживает рестарт бота — расписание живёт в БД, а не в памяти процесса.
    """
    id = models.AutoField(primary_key=True)
    chat_id = models.CharField(max_length=50, db_index=True)
    message_id = models.BigIntegerField()
    remove_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pending_button_removals'
        verbose_name = 'Отложенное снятие кнопок'
        verbose_name_plural = 'Отложенные снятия кнопок'
        indexes = [
            models.Index(fields=['remove_at']),
        ]


class ExternalExperience(models.Model):
    """Внешнее волонтёрское мероприятие, не учтённое в системе центра (раздел «Мой опыт»).

    Хранится как простой текст в личном профиле волонтёра и НЕ участвует в статистике
    (никаких Participation/часов/пересчётов) — это самозаявленный опыт «извне»."""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='external_experiences')
    title = models.CharField(max_length=255, verbose_name='Название')
    date = models.DateField(blank=True, null=True, verbose_name='Дата начала')
    # Конец диапазона — опционально; если пусто, мероприятие однодневное (date == date_to
    # для отображения). Старые записи (до этого поля) остаются однодневными.
    date_to = models.DateField(blank=True, null=True, verbose_name='Дата окончания')
    # Что волонтёр делал на этом внешнем мероприятии — свободный текст, отдельно от
    # title (название события) — profile_detail.html показывает это отдельной колонкой.
    description = models.CharField(max_length=255, blank=True, null=True, verbose_name='Что делал')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'external_experiences'
        verbose_name = 'Внешний опыт'
        verbose_name_plural = 'Внешний опыт'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f'{self.title} ({self.user_id})'


class TelegramAuthToken(models.Model):
    """Одноразовая ссылка для входа/авто-регистрации через Telegram-бота (браузерный
    вход вне Mini App): пользователь открывает бота по deep-link `?start=weblogin`,
    бот создаёт эту запись и присылает ссылку `/auth/tg/<token>/`, действующую 5 минут.
    Переход по ссылке логинит пользователя в веб-сессию и помечает токен использованным."""
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auth_tokens')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'telegram_auth_tokens'
        verbose_name = 'Токен входа через Telegram'
        verbose_name_plural = 'Токены входа через Telegram'

    def is_valid(self) -> bool:
        return self.used_at is None and timezone.now() < self.expires_at


class TelegramVerifyToken(models.Model):
    """Одноразовый токен подтверждения владения Telegram («Подтвердить телеграм» в ЛК).

    Пользователь в личном кабинете нажимает кнопку → создаётся эта запись → его
    переносит в бота по deep-link `?start=verify_<token>`. Бот показывает «<ФИО> сейчас
    пытается подтвердить телеграм — да/нет». При «да» токен потребляется: реальный
    `telegram_id` того, кто открыл бота, привязывается к аккаунту и ставится
    `telegram_verified=True`. При «нет» токен гасится, а веб-сессии запросившего
    пользователя завершаются (разлогин). См. blog.services.telegram_verify."""
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='verify_tokens')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'telegram_verify_tokens'
        verbose_name = 'Токен подтверждения Telegram'
        verbose_name_plural = 'Токены подтверждения Telegram'

    def is_valid(self) -> bool:
        return self.used_at is None and timezone.now() < self.expires_at


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


# ======================================================================
# Система достижений (achievements.md). Три параллельные таблицы вместо
# полной матрицы пользователь×достижение (см. док §«Хранение в БД»):
#   • AchievementDefinition — справочник шаблонов достижений;
#   • UserAchievement       — факт получения (строка на выданное);
#   • AchievementStat        — агрегат-кэш «сколько человек имеют».
# ======================================================================
class AchievementDefinition(models.Model):
    """Шаблон достижения (не выданный экземпляр). Единый список всех достижений —
    и «общих» series/single (считаются авто по агрегатам), и «скрытых» точечных,
    и ручных курсов (source_type='manual_grant', заводятся менеджером с платформы)."""
    KIND_CHOICES = [
        ('series', 'Ряд (со ступенями)'),
        ('single', 'Факт (есть/нет)'),
    ]
    VISIBILITY_CHOICES = [
        ('common', 'Общее (всегда видно как цель)'),
        ('hidden', 'Скрытое (появляется по факту)'),
    ]
    SOURCE_CHOICES = [
        ('auto', 'Авто (по агрегатам)'),
        ('manual_grant', 'Ручная выдача менеджером'),
    ]

    id = models.AutoField(primary_key=True)
    # Машинный код: у auto-достижений по нему движок знает, как считать прогресс
    # (см. blog.services.achievements.EVALUATORS); у ручных — просто уникальный ключ.
    code = models.CharField(max_length=100, unique=True, db_index=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='common')
    # Смысловая группа для UI-раскладки (часы, регулярность, категории, курсы…).
    group = models.CharField(max_length=50, blank=True, default='')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    # Иконка — на этом этапе строка с эмодзи (⏱️🏅🌟…); позже можно заменить на файл.
    icon = models.CharField(max_length=50, blank=True, default='🏅')
    # Уровень сложности/редкости для оформления рамки (см. achievements.TIERS):
    # '1'..'6' — обычная шкала (бронза…фиолетовый), 'event'/'course' — уникальные
    # обводки точечных достижений. У series ЯВНЫЙ tier не используется — там уровень
    # каждой карточки-ступени = её порядковый номер (1-я ступень=1 …). Хранится строкой,
    # чтобы вместить и числа, и текстовые уникальные уровни. Пусто → нейтральная рамка.
    tier = models.CharField(max_length=20, blank=True, default='')
    # Для series — список ступеней [{"value": n, "label": "..."}], по возрастанию value.
    # Для single — null/пусто.
    series_steps = models.JSONField(blank=True, null=True)
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='auto')
    is_active = models.BooleanField(default=True)
    # Порядок вывода внутри группы (меньше — выше). Ровняем группы стабильно.
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        db_table = 'achievement_definitions'
        verbose_name = 'Достижение (шаблон)'
        verbose_name_plural = 'Достижения (шаблоны)'
        ordering = ['group', 'sort_order', 'id']

    def __str__(self):
        return f'{self.title} ({self.code})'

    def steps(self):
        """Нормализованный список ступеней series: [(value:int, label:str), …] по
        возрастанию. Для single — пустой список."""
        raw = self.series_steps or []
        out = []
        for s in raw:
            try:
                out.append((int(s['value']), str(s.get('label') or s['value'])))
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda t: t[0])
        return out


class UserAchievement(models.Model):
    """Факт получения достижения пользователем. Для series по решению этапа реализации —
    СТРОКА НА КАЖДУЮ взятую ступень (у каждой свой granted_at → точная лента «моментов»);
    для single — одна строка. Точечные скрытые достижения несут context (event_id и т.п.)."""
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='achievements')
    achievement = models.ForeignKey(
        AchievementDefinition, on_delete=models.CASCADE, related_name='grants'
    )
    # Для series — значение ступени (n), на которой выдано. Для single — null.
    series_value = models.IntegerField(blank=True, null=True)
    # Контекст точечных скрытых достижений: {"event_id": 123} и т.п. Заменяет отдельную
    # колонку/таблицу на каждый частный случай (achievements.md §user_achievements).
    context = models.JSONField(blank=True, null=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        db_table = 'user_achievements'
        verbose_name = 'Полученное достижение'
        verbose_name_plural = 'Полученные достижения'
        # Идемпотентность выдачи: одна строка на (user, achievement, series_value).
        # У single series_value=NULL — пара (user, achievement) уникальна де-факто
        # (NULL в UNIQUE у SQLite/PG не конфликтует сам с собой, поэтому дополнительно
        # проверяем существование в сервисе перед выдачей).
        unique_together = ('user', 'achievement', 'series_value')
        indexes = [
            models.Index(fields=['user', 'achievement']),
        ]


class AchievementStat(models.Model):
    """Агрегат-кэш «сколько человек имеют достижение» — чтобы не гонять COUNT(*) по
    user_achievements на каждый рендер. Источник истины всегда user_achievements."""
    achievement = models.OneToOneField(
        AchievementDefinition, on_delete=models.CASCADE, primary_key=True, related_name='stat'
    )
    holders_count = models.IntegerField(default=0)
    first_granted_at = models.DateTimeField(blank=True, null=True)
    last_granted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'achievement_stats'
        verbose_name = 'Статистика достижения'
        verbose_name_plural = 'Статистика достижений'
