"""Доступ к данным: техническая аналитика (телеметрия техадмин-дашборда).

Веб-сессии, просмотры страниц, клики, периоды простоя. Это не бизнес-данные ВЦ, но
единый слой доступа держим и для них — чтобы весь ORM был в одном месте.
Тяжёлая агрегация для дашборда — в `blog/services/analytics.py` поверх `*_qs()`.
"""
from typing import Optional, List

from blog.models import WebSession, WebPageView, ButtonClickEvent, SystemDowntime


# --- Веб-сессии и просмотры (заполняет ActivityTrackingMiddleware + analytics.js) ---
def touch_web_session(session_key: str, seen_at) -> None:
    WebSession.objects.filter(session_key=session_key).update(last_seen_at=seen_at)


def get_web_session(session_key: str) -> Optional[WebSession]:
    return WebSession.objects.filter(session_key=session_key).first()


def set_page_view_duration(page_view_id, session_key: str, duration_ms: int) -> None:
    WebPageView.objects.filter(pk=page_view_id, session__session_key=session_key).update(
        duration_ms=duration_ms
    )


def create_button_click(*, source: str, user, web_session, role_snapshot: str,
                        action_key: str, label: str) -> ButtonClickEvent:
    return ButtonClickEvent.objects.create(
        source=source, user=user, web_session=web_session,
        role_snapshot=role_snapshot, action_key=action_key, label=label,
    )


# --- Периоды простоя системы (красные/жёлтые зоны на графиках онлайна) ---
def downtimes_since(since) -> List[SystemDowntime]:
    return list(SystemDowntime.objects.filter(ended_at__gte=since).order_by('started_at'))


def create_downtime(kind: str, started_at, ended_at, comment: str = '') -> SystemDowntime:
    return SystemDowntime.objects.create(
        kind=kind, started_at=started_at, ended_at=ended_at, comment=comment,
    )


def delete_downtime(downtime_id: int) -> None:
    SystemDowntime.objects.filter(pk=downtime_id).delete()
