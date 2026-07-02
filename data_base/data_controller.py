from typing import Optional, List, Dict, Any
from django.db.models import Q
from blog.models import (
    User, Manager, TeamLeader, Organization, Organizer, 
    OrganizerOrganizationLink, Location, EventCategory, Event, 
    EventCategoryMap, EventDay, EventStaff, Application, 
    Participation, EventFeedback, EventRequirement, 
    EventRequirementMap, UserRequirementException, Season
)

__all__ = [
    'create_user', 'get_users',
    'create_manager', 'get_managers',
    'create_team_leader', 'get_team_leaders',
    'create_organization', 'get_organizations',
    'create_organizer', 'get_organizers',
    'link_organizer_to_organization', 'get_organizer_links',
    'create_location', 'get_locations',
    'create_event_category', 'get_event_categories',
    'create_event', 'get_events',
    'add_category_to_event', 'get_event_categories_map',
    'create_event_day', 'get_event_days',
    'assign_staff_to_event', 'get_event_staff',
    'create_application', 'get_applications',
    'create_participation', 'get_participations',
    'create_feedback', 'get_feedbacks',
    'create_requirement', 'get_requirements',
    'add_requirement_to_event', 'get_event_requirements_map',
    'create_user_exception', 'get_user_exceptions',
    'create_season', 'get_seasons',
    'get_full_table', 'create_record_generic'
]

# ==============================================================================
# ЧАСТЬ 1: СОЗДАНИЕ ЗАПИСЕЙ (WRITE)
# ==============================================================================

def create_user(
    telegram_id: str,
    telegram_username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    vk_username: Optional[str] = None,
    birthday: Optional[str] = None,
    about: Optional[str] = None,
    status: str = 'active',
    comment: Optional[str] = None
) -> User:
    """Создает пользователя через кастомный менеджер."""
    return User.objects.create_user(
        telegram_id=telegram_id,
        telegram_username=telegram_username,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        VK_username=vk_username,
        birthday=birthday,
        about=about,
        status=status,
        comment=comment
    )

def create_manager(
    user: User,
    assigned_by: Optional[User] = None,
    total_events: int = 0,
    season_events: int = 0
) -> Manager:
    """Выдает роль менеджера."""
    return Manager.objects.create(
        user=user,
        assigned_by=assigned_by,
        total_events=total_events,
        season_events=season_events
    )

def create_team_leader(
    user: User,
    assigned_by: Optional[User] = None,
    total_events: int = 0,
    season_events: int = 0
) -> TeamLeader:
    """Выдает роль тим-лидера."""
    return TeamLeader.objects.create(
        user=user,
        assigned_by=assigned_by,
        total_events=total_events,
        season_events=season_events
    )

def create_organization(name: str, description: Optional[str] = None) -> Organization:
    return Organization.objects.create(name=name, description=description)

def create_organizer(
    first_name: str,
    last_name: str,
    user: Optional[User] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    telegram_username: Optional[str] = None,
    vk_username: Optional[str] = None,
    comments: Optional[str] = None
) -> Organizer:
    return Organizer.objects.create(
        user=user,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        telegram_username=telegram_username,
        VK_username=vk_username,
        comments=comments
    )

def link_organizer_to_organization(organizer: Organizer, organization: Organization) -> OrganizerOrganizationLink:
    return OrganizerOrganizationLink.objects.create(organizer=organizer, organization=organization)

def create_location(name: str) -> Location:
    return Location.objects.create(name=name)

def create_event_category(name: str) -> EventCategory:
    return EventCategory.objects.create(name=name)

def create_event(
    title: str,
    location: Optional[Location] = None,
    organization: Optional[Organization] = None,
    organizer: Optional[Organizer] = None,
    description: Optional[str] = None,
    chat_link: Optional[str] = None,
    post_in_chanel_link: Optional[str] = None,
    event_status: str = 'upcoming',
    recruit_status: str = 'open',
    people_helped: int = 0
) -> Event:
    return Event.objects.create(
        title=title,
        location=location,
        organization=organization,
        organizer=organizer,
        description=description,
        chat_link=chat_link,
        post_in_chanel_link=post_in_chanel_link,
        event_status=event_status,
        recruit_status=recruit_status,
        people_helped=people_helped
    )

def add_category_to_event(event: Event, category: EventCategory) -> EventCategoryMap:
    return EventCategoryMap.objects.create(event=event, category=category)

def create_event_day(
    event: Event,
    day: str,
    start_time: str,
    end_time: str,
    volunteer_needed: int = 0,
    location: Optional[Location] = None
) -> EventDay:
    return EventDay.objects.create(
        event=event,
        day=day,
        start_time=start_time,
        end_time=end_time,
        volunteer_needed=volunteer_needed,
        location=location
    )

def assign_staff_to_event(event: Event, user: User, role: str) -> EventStaff:
    return EventStaff.objects.create(event=event, user=user, staff_role=role)

def create_application(
    event: Event,
    first_name: str,
    last_name: str,
    user: Optional[User] = None,
    telegram_username: Optional[str] = None,
    phone: Optional[str] = None,
    functions: Optional[str] = None,
    shifts: Optional[str] = None,
    role_in_event: Optional[str] = None,
    user_status: Optional[str] = None,
    status: str = 'new'
) -> Application:
    return Application.objects.create(
        event=event,
        user=user,
        first_name=first_name,
        last_name=last_name,
        telegram_username=telegram_username,
        phone=phone,
        functions=functions,
        shifts=shifts,
        role_in_event=role_in_event,
        user_status=user_status,
        status=status
    )

def create_participation(
    user: User,
    event_day: EventDay,
    status: str = 'attended',
    hours: int = 0
) -> Participation:
    return Participation.objects.create(user=user, event_day=event_day, status=status, hours=hours)

def create_feedback(author: User, event: Event, rating: int, comment: Optional[str] = None) -> EventFeedback:
    return EventFeedback.objects.create(author=author, event=event, rating=rating, comment=comment)

def create_requirement(title: str, description: Optional[str] = None) -> EventRequirement:
    return EventRequirement.objects.create(title=title, description=description)

def add_requirement_to_event(event: Event, requirement: EventRequirement) -> EventRequirementMap:
    return EventRequirementMap.objects.create(event=event, requirement=requirement)

def create_user_exception(user: User, requirement: EventRequirement, reason: Optional[str] = None) -> UserRequirementException:
    return UserRequirementException.objects.create(user=user, requirement=requirement, reason=reason)

def create_season(start_date: str, end_date: str) -> Season:
    return Season.objects.create(start_season=start_date, end_season=end_date)


# ==============================================================================
# ЧАСТЬ 2: ЧТЕНИЕ ДАННЫХ (READ / FILTERS)
# ==============================================================================

# --- USERS ---
def get_users(
    name: Optional[str] = None,
    telegram_username: Optional[str] = None,
    telegram_id: Optional[str] = None,
    phone: Optional[str] = None
) -> List[User]:
    filters = Q()
    if name:
        filters &= Q(first_name__icontains=name) | Q(last_name__icontains=name)
    if telegram_username:
        filters &= Q(telegram_username__iexact=telegram_username)
    if telegram_id:
        filters &= Q(telegram_id=telegram_id)
    if phone:
        filters &= Q(phone__icontains=phone)
    return list(User.objects.filter(filters))

# --- MANAGERS ---
def get_managers(user_id: Optional[int] = None, is_active_only: bool = True) -> List[Manager]:
    qs = Manager.objects.select_related('user')
    if user_id:
        qs = qs.filter(user_id=user_id)
    if is_active_only:
        qs = qs.filter(revoked_at__isnull=True)
    return list(qs)

# --- TEAM LEADERS ---
def get_team_leaders(user_id: Optional[int] = None, is_active_only: bool = True) -> List[TeamLeader]:
    qs = TeamLeader.objects.select_related('user')
    if user_id:
        qs = qs.filter(user_id=user_id)
    if is_active_only:
        qs = qs.filter(revoked_at__isnull=True)
    return list(qs)

# --- ORGANIZATIONS ---
def get_organizations(name_filter: Optional[str] = None) -> List[Organization]:
    qs = Organization.objects.all()
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    return list(qs)

# --- ORGANIZERS ---
def get_organizers(name_filter: Optional[str] = None) -> List[Organizer]:
    qs = Organizer.objects.all()
    if name_filter:
        qs = qs.filter(first_name__icontains=name_filter) | qs.filter(last_name__icontains=name_filter)
    return list(qs)

# --- LINKS ---
def get_organizer_links(organizer_id: Optional[int] = None, organization_id: Optional[int] = None) -> List[OrganizerOrganizationLink]:
    qs = OrganizerOrganizationLink.objects.all()
    if organizer_id:
        qs = qs.filter(organizer_id=organizer_id)
    if organization_id:
        qs = qs.filter(organization_id=organization_id)
    return list(qs)

# --- LOCATIONS ---
def get_locations(name_filter: Optional[str] = None) -> List[Location]:
    qs = Location.objects.all()
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    return list(qs)

# --- CATEGORIES ---
def get_event_categories(name_filter: Optional[str] = None) -> List[EventCategory]:
    qs = EventCategory.objects.all()
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    return list(qs)

# --- EVENTS ---
def get_events(title_filter: Optional[str] = None) -> List[Event]:
    qs = Event.objects.all()
    if title_filter:
        qs = qs.filter(title__icontains=title_filter)
    return list(qs)

# --- CATEGORY MAP ---
def get_event_categories_map(event_id: Optional[int] = None) -> List[EventCategoryMap]:
    qs = EventCategoryMap.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    return list(qs)

# --- EVENT DAYS ---
def get_event_days(event_id: Optional[int] = None) -> List[EventDay]:
    qs = EventDay.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    return list(qs)

# --- STAFF ---
def get_event_staff(event_id: Optional[int] = None, user_id: Optional[int] = None) -> List[EventStaff]:
    qs = EventStaff.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    if user_id:
        qs = qs.filter(user_id=user_id)
    return list(qs)

# --- APPLICATIONS ---
def get_applications(status_filter: Optional[str] = None, applicant_name: Optional[str] = None) -> List[Application]:
    qs = Application.objects.all()
    if status_filter:
        qs = qs.filter(status=status_filter)
    if applicant_name:
        qs = qs.filter(first_name__icontains=applicant_name) | qs.filter(last_name__icontains=applicant_name)
    return list(qs)

# --- PARTICIPATIONS ---
def get_participations(status_filter: Optional[str] = None, volunteer_name: Optional[str] = None) -> List[Participation]:
    qs = Participation.objects.select_related('user', 'event_day')
    if status_filter:
        qs = qs.filter(status=status_filter)
    if volunteer_name:
        qs = qs.filter(Q(user__first_name__icontains=volunteer_name) | Q(user__last_name__icontains=volunteer_name))
    return list(qs)

# --- FEEDBACKS ---
def get_feedbacks(event_id: Optional[int] = None, author_id: Optional[int] = None) -> List[EventFeedback]:
    qs = EventFeedback.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    if author_id:
        qs = qs.filter(author_id=author_id)
    return list(qs)

# --- REQUIREMENTS ---
def get_requirements(title_filter: Optional[str] = None) -> List[EventRequirement]:
    qs = EventRequirement.objects.all()
    if title_filter:
        qs = qs.filter(title__icontains=title_filter)
    return list(qs)

def get_event_requirements_map(event_id: Optional[int] = None) -> List[EventRequirementMap]:
    qs = EventRequirementMap.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    return list(qs)

# --- EXCEPTIONS ---
def get_user_exceptions(user_id: Optional[int] = None) -> List[UserRequirementException]:
    qs = UserRequirementException.objects.all()
    if user_id:
        qs = qs.filter(user_id=user_id)
    return list(qs)

# --- SEASONS ---
def get_seasons() -> List[Season]:
    return list(Season.objects.all().order_by('-start_season'))


# ==============================================================================
# ЧАСТЬ 3: ОБЩИЕ ФУНКЦИИ (GENERIC)
# ==============================================================================

TABLE_MODEL_MAP: Dict[str, Any] = {
    'users': User,
    'managers': Manager,
    'team_leaders': TeamLeader,
    'organizations': Organization,
    'organizers': Organizer,
    'organizer_organization_link': OrganizerOrganizationLink,
    'locations': Location,
    'event_categories': EventCategory,
    'events': Event,
    'event_category_map': EventCategoryMap,
    'event_days': EventDay,
    'event_staff': EventStaff,
    'applications': Application,
    'participations': Participation,
    'event_feedbacks': EventFeedback,
    'event_requirements': EventRequirement,
    'event_requirement_map': EventRequirementMap,
    'user_requirement_exceptions': UserRequirementException,
    'seasons': Season,
}

def get_full_table(table_name: str) -> List[Dict[str, Any]]:
    """Возвращает все записи таблицы в виде списка словарей."""
    model = TABLE_MODEL_MAP.get(table_name.lower())
    if not model:
        raise ValueError(f"Неизвестная таблица: '{table_name}'. Доступные: {list(TABLE_MODEL_MAP.keys())}")
    return list(model.objects.all().values())

def create_record_generic(table_name: str, **data) -> Any:
    """Универсальное создание записи (использовать с осторожностью)."""
    model = TABLE_MODEL_MAP.get(table_name.lower())
    if not model:
        raise ValueError(f"Неизвестная таблица: '{table_name}'")
    
    if model == User:
        if 'telegram_id' not in data:
            raise ValueError("Для создания пользователя обязательно поле telegram_id")
        return User.objects.create_user(**data)
        
    return model.objects.create(**data)


