"""Функции менеджера: все заявки, контакты организаторов активных меро (tg-bot.md §6)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from tg_bot import services

router = Router(name='manager')

STATUS_ICON = {
    'new': '🕓 На рассмотрении',
    'approved': '✅ Одобрена',
    'rejected': '💤 Резерв',
}


@router.message(Command('allapplications'))
@router.message(F.text == '⚙️ Управление')
async def cmd_allapplications(message: Message):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    apps, error = await sync_to_async(services.all_applications)(user.id)
    if error == 'forbidden':
        await message.answer('⛔ У тебя нет доступа к этому действию.')
        return

    if not apps:
        await message.answer('📋 Заявок пока нет.')
        return

    lines = [f'📋 Все заявки (последние {len(apps)}):\n']
    for a in apps:
        applicant = f'{a.first_name} {a.last_name or ""}'.strip()
        icon = STATUS_ICON.get(a.status, a.get_status_display())
        lines.append(f'• «{a.event.title}» — {applicant} — {icon}')
    await message.answer('\n'.join(lines))

    await _send_active_events_with_organizers(message, user.id)


async def _send_active_events_with_organizers(message: Message, user_id: int):
    events, error = await sync_to_async(services.active_events_with_organizers)(user_id)
    if error or not events:
        return

    for e in events:
        lines = [f'👥 «{e.title}»']
        if e.organization:
            rating = f' (рейтинг: {e.organization.internal_rating}/10)' if e.organization.internal_rating else ''
            lines.append(f'🏢 Организация: {e.organization.name}{rating}')
        if e.organizer:
            org = e.organizer
            lines.append(f'👤 Организатор: {org.first_name} {org.last_name}'.strip())
            if org.phone:
                lines.append(f'☎ {org.phone}')
            if org.email:
                lines.append(f'✉ {org.email}')
            if org.telegram_username:
                lines.append(f'✈ @{org.telegram_username.lstrip("@")}')
        if len(lines) > 1:
            await message.answer('\n'.join(lines))
