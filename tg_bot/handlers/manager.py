"""Функции менеджера: все заявки, контакты организаторов активных меро, публикация
и рассылка мероприятий (tg-bot.md §6, bot-update.md §2.4)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from tg_bot import services, keyboards as kb
from tg_bot.ui import answer_with_expiring_keyboard

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
        # Менеджер обрабатывает заявки/явку на любом меро (tg-bot.md §6, M2) — те же
        # кнопки, что у тим-лидера на своих меро (event_apps/event_apps_approve_all/event_attendance
        # проверяют права через can_process_applications, который пропускает менеджера везде).
        await answer_with_expiring_keyboard(message, '\n'.join(lines), kb.event_actions(e.id))


@router.message(Command('publish'))
@router.message(F.text == '📢 Опубликовать меро')
async def cmd_publish_menu(message: Message):
    """Список сформированных, но не опубликованных мероприятий (bot-update.md §2.4.C)."""
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    events, error = await sync_to_async(services.unpublished_events)(user.id)
    if error == 'forbidden':
        await message.answer('⛔ У тебя нет доступа к этому действию.')
        return
    if not events:
        await message.answer('📢 Сейчас нет сформированных, но не опубликованных мероприятий.')
        return

    await message.answer('📢 Сформированы, но не опубликованы:')
    for e in events:
        await answer_with_expiring_keyboard(message, f'«{e.title}»', kb.publish_button(e.id))


@router.callback_query(F.data.startswith('event_publish:'))
async def cb_event_publish(callback: CallbackQuery):
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    event, error = await sync_to_async(services.publish_event_from_bot)(user.id, event_id)
    await callback.answer()
    if error == 'forbidden':
        await callback.message.answer('⛔ У тебя нет доступа к этому действию.')
        return
    if error == 'already_published':
        await callback.message.edit_text('ℹ️ Мероприятие уже опубликовано.')
        return
    if error == 'finished':
        await callback.message.edit_text('⚠️ Мероприятие уже завершено — публиковать его больше нельзя.')
        return
    if error:
        await callback.message.answer('⚠️ Мероприятие не найдено.')
        return

    await answer_with_expiring_keyboard(
        callback.message,
        f'✅ «{event.title}» опубликовано — набор открыт.\n\nСделать рассылку по этому мероприятию?',
        kb.published_offer_broadcast(event.id),
    )


@router.message(Command('broadcast'))
@router.message(F.text == '📨 Сделать рассылку')
async def cmd_broadcast_menu(message: Message):
    """Активные (опубликованные) мероприятия — кандидаты для рассылки (bot-update.md §2.4.D)."""
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    events, error = await sync_to_async(services.broadcastable_events)(user.id)
    if error == 'forbidden':
        await message.answer('⛔ У тебя нет доступа к этому действию.')
        return
    if not events:
        await message.answer('📨 Сейчас нет активных мероприятий с открытым набором.')
        return

    await message.answer('📨 Активные мероприятия с открытым набором:')
    for e in events:
        last = f'последняя рассылка {e.broadcast_sent_at.strftime("%d.%m")}' if e.broadcast_sent_at else 'рассылка ещё не делалась'
        await answer_with_expiring_keyboard(message, f'«{e.title}» — {last}', kb.broadcast_button(e.id))


@router.callback_query(F.data.startswith('event_broadcast:'))
async def cb_event_broadcast(callback: CallbackQuery):
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    sent, was_sent_before, error = await sync_to_async(services.broadcast_event_from_bot)(user.id, event_id)
    await callback.answer()
    if error == 'forbidden':
        await callback.message.answer('⛔ У тебя нет доступа к этому действию.')
        return
    if error == 'not_published':
        await callback.message.answer('⚠️ Сначала опубликуйте мероприятие — потом можно делать рассылку.')
        return
    if error == 'finished':
        await callback.message.answer('⚠️ Мероприятие завершено — рассылка больше не нужна.')
        return
    if error:
        await callback.message.answer('⚠️ Мероприятие не найдено.')
        return

    if was_sent_before:
        await callback.message.edit_text(f'📨 «Продолжаем набирать волонтёров» — рассылка отправлена ({sent} адресатов).')
    else:
        await callback.message.edit_text(f'📨 Рассылка отправлена всем подписанным волонтёрам ({sent} адресатов).')
