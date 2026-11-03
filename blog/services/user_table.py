"""Read model for the user table, including a revision for private browser caching."""
import hashlib
import json

from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from data_base import data_controller as dc
from blog.services.requirements import _age_on


def user_table_context(*, full=False, page_number=None, owner_id):
    last_event = (
        dc.participations_qs().filter(user=OuterRef('pk'), status='attended', hours__gt=0)
        .order_by('-event_day__day').values('event_day__day')[:1]
    )
    # Only table columns: no passwords, questionnaire, contacts or QR tokens in this read.
    users = dc.users_qs().only(
        'id', 'first_name', 'last_name', 'middle_name', 'telegram_username', 'telegram_id',
        'birthday', 'status', 'season_hours', 'total_hours',
        'season_event_count', 'total_event_count',
    ).annotate(last_attended_day=Subquery(last_event)).order_by('-created_at', '-pk')
    if full:
        users = list(users)
    paginator = Paginator(users, max(len(users), 1) if full else 40)
    page = paginator.get_page(1 if full else page_number)
    manager_ids = set(dc.managers_qs().filter(revoked_at__isnull=True).values_list('user_id', flat=True))
    team_leader_ids = set(dc.team_leaders_qs().filter(revoked_at__isnull=True).values_list('user_id', flat=True))
    today = timezone.localdate()
    revision = []
    for user in page:
        user.table_age = _age_on(user.birthday, today) if user.birthday and user.birthday <= today else None
        user.table_role = ('manager' if user.pk in manager_ids else
                           'team_lead' if user.pk in team_leader_ids else 'volunteer')
        if full:
            revision.append([
                user.pk, user.first_name, user.last_name, user.middle_name,
                user.telegram_username, user.telegram_id, user.status, user.table_age,
                user.table_role, user.last_attended_day, user.season_hours, user.total_hours,
                user.season_event_count, user.total_event_count,
            ])
    # Version changes whenever the row markup changes. Local day also refreshes ages.
    digest = hashlib.sha256(json.dumps(
        ['user-table-v1', owner_id, today, revision], default=str, ensure_ascii=False,
    ).encode()).hexdigest() if full else None
    return {'page_obj': page, 'manager_ids': manager_ids, 'team_leader_ids': team_leader_ids,
            'table_etag': '"' + digest + '"' if digest else None}
