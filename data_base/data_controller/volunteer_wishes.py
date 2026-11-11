"""Табличка желающих: тонкий CRUD строк `volunteer_wishes`.

Разбор сообщений, сопоставление с мероприятием и ACL — в
`blog/services/volunteer_wishes.py`; здесь только чтение/запись с аудитом в `vc.db`.
"""
from django.utils import timezone

from blog.models import VolunteerWish
from ._base import logger, actor


def volunteer_wishes_qs():
    """Ленивый queryset строк таблички с авторами и отметками «забрал»."""
    return VolunteerWish.objects.select_related('user', 'added_by', 'taken_by', 'taken_event_group', 'event_group',
                                                'taken_shift__event')


def get_volunteer_wish(wish_id):
    return volunteer_wishes_qs().filter(pk=wish_id).first()


def create_volunteer_wish(added_by=None, **fields):
    wish = VolunteerWish.objects.create(added_by=added_by, **fields)
    logger.info(
        'INSERT volunteer_wishes: wish=%s batch=%s source=%s subject=%s by=%s',
        wish.pk, wish.batch_id, wish.source, f'user={wish.user_id}' if wish.user_id else 'user=?', actor(added_by),
    )
    return wish


def update_volunteer_wish(wish, operator=None, **fields):
    for name, value in fields.items():
        setattr(wish, name, value)
    wish.save(update_fields=list(fields))
    logger.info('UPDATE volunteer_wishes: wish=%s fields=%s by=%s', wish.pk, sorted(fields), actor(operator))
    return wish


def set_volunteer_wish_taken(wish, taken=True, event_group=None, shift=None, operator=None):
    """Поставить (taken=True; мероприятие/смена — необязательно) или снять отметку «забрали»."""
    wish.taken_at = timezone.now() if taken else None
    wish.taken_by = operator if taken else None
    wish.taken_event_group = event_group if taken else None
    wish.taken_shift = shift if taken else None
    wish.save(update_fields=['taken_at', 'taken_by', 'taken_event_group', 'taken_shift'])
    logger.info(
        'UPDATE volunteer_wishes: wish=%s taken=%s group=%s shift=%s by=%s',
        wish.pk, taken, event_group.pk if event_group else None, shift.pk if shift else None, actor(operator),
    )
    return wish


def delete_volunteer_wishes(wishes, operator=None):
    ids = [wish.pk for wish in wishes]
    deleted, _ = VolunteerWish.objects.filter(pk__in=ids).delete()
    logger.info('DELETE volunteer_wishes: wishes=%s by=%s', ids, actor(operator))
    return deleted
