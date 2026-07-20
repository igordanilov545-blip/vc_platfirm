"""Доступ к данным: организации, организаторы, их связи, взаимодействия и локации."""
from typing import Optional, List

from blog.models import (
    Organization, Organizer, OrganizerOrganizationLink,
    OrganizerInteractionLog, Location, User,
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


def create_organizer_interaction(
    organizer: Organizer,
    author: Optional[User],
    contact_type: str,
    note: Optional[str] = None
) -> OrganizerInteractionLog:
    return OrganizerInteractionLog.objects.create(
        organizer=organizer, author=author, contact_type=contact_type, note=note
    )


def create_location(name: str) -> Location:
    return Location.objects.create(name=name)


def get_organizations(name_filter: Optional[str] = None) -> List[Organization]:
    qs = Organization.objects.all()
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    return list(qs)


def get_organization_by_id(organization_id: int) -> Optional[Organization]:
    return Organization.objects.filter(pk=organization_id).first()


def get_organizers(name_filter: Optional[str] = None) -> List[Organizer]:
    qs = Organizer.objects.all()
    if name_filter:
        qs = qs.filter(first_name__icontains=name_filter) | qs.filter(last_name__icontains=name_filter)
    return list(qs)


def get_organizer_links(organizer_id: Optional[int] = None, organization_id: Optional[int] = None) -> List[OrganizerOrganizationLink]:
    qs = OrganizerOrganizationLink.objects.all()
    if organizer_id:
        qs = qs.filter(organizer_id=organizer_id)
    if organization_id:
        qs = qs.filter(organization_id=organization_id)
    return list(qs)


def get_organizer_interactions(organizer_id: Optional[int] = None) -> List[OrganizerInteractionLog]:
    qs = OrganizerInteractionLog.objects.select_related('author').order_by('-created_at')
    if organizer_id:
        qs = qs.filter(organizer_id=organizer_id)
    return list(qs)


def get_locations(name_filter: Optional[str] = None) -> List[Location]:
    qs = Location.objects.all()
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    return list(qs)
