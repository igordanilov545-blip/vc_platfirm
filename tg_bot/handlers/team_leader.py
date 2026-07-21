"""Функции тим-лидера: мои мероприятия, обработка заявок, явка, комментарии (tg-bot.md §5)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from tg_bot import services, keyboards as kb
from tg_bot.states import Comment
from tg_bot.ui import answer_with_expiring_keyboard
from blog.services import roles as roles_service
from data_base import data_controller as dc

router = Router(name='team_leader')


@router.message(Command('myevents'))
@router.message(F.text == '👥 Мои мероприятия (ТЛ)')
async def cmd_myevents(message: Message):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    events = await sync_to_async(services.team_leader_events)(user.id)
    if not events:
        await message.answer('👥 У тебя пока нет мероприятий как тим-лидера.')
        return

    lines = ['👥 Твои мероприятия (тим-лидер):\n']
    for e in events:
        note = f"{e['new_applications']} новых заявки" if e['new_applications'] else 'нет новых заявок'
        lines.append(f"«{e['title']}» — {note}")
    await message.answer('\n'.join(lines))

    for e in events:
        await answer_with_expiring_keyboard(message, f"«{e['title']}»", kb.event_actions(e['id']))
        if e['new_applications']:
            await _send_pending_applications(message, user.id, e['id'])


async def _send_pending_applications(message: Message, user_id: int, event_id: int):
    apps, error = await sync_to_async(services.event_pending_applications)(user_id, event_id)
    if error or not apps:
        return
    for a in apps:
        contact = f' (@{a.telegram_username.lstrip("@")})' if a.telegram_username else ''
        phone = f'\n☎ {a.phone}' if a.phone else ''
        shifts = await sync_to_async(services.application_shifts_for_decision)(a.id)
        shifts_line = f"\nГотов на смены: {', '.join(s.day.strftime('%d.%m') for s in shifts)}" if len(shifts) > 1 else ''
        text = (
            f'📥 Заявка на «{a.event.title}»\n'
            f'👤 {a.first_name} {a.last_name or ""}'.strip() + contact + phone + shifts_line
        )
        # Несколько смен → решение по каждой отдельно (bot-update.md §2.3.C); одна смена
        # (или заявка ещё без выбора смен) → как раньше, одобрить/резерв целиком.
        markup = kb.application_shift_decision(a.id, shifts) if len(shifts) > 1 else kb.application_decision(a.id)
        await answer_with_expiring_keyboard(message, text, markup)


@router.callback_query(F.data.startswith('app_approve:'))
async def cb_approve(callback: CallbackQuery):
    await _decide(callback, approve=True)


@router.callback_query(F.data.startswith('app_reject:'))
async def cb_reject(callback: CallbackQuery):
    await _decide(callback, approve=False)


async def _decide(callback: CallbackQuery, approve: bool):
    application_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    application, error = await sync_to_async(services.process_application_decision)(
        user.id, application_id, approve
    )
    await callback.answer()
    if error == 'forbidden':
        await callback.message.answer('⛔ Ты не тим-лидер этого мероприятия.')
        return
    if error:
        await callback.message.answer('⚠️ Заявка не найдена.')
        return

    await sync_to_async(services.notify_manager_processed_application)(user.id, application)

    await callback.message.edit_reply_markup(reply_markup=None)
    if approve:
        name = f'{application.first_name} {application.last_name or ""}'.strip()
        await callback.message.answer(f'✅ Заявка {name} одобрена. Волонтёр получил уведомление.')
        if not application.event.shifts.filter(recruit_status='open').exists():
            await callback.message.answer(
                f'ℹ️ Набор на «{application.event.title}» закрыт — одобренных заявок достаточно.'
            )
    else:
        await callback.message.answer('💤 Заявка переведена в резерв.')


@router.callback_query(F.data.startswith('app_shift_approve:'))
async def cb_shift_approve(callback: CallbackQuery):
    """Одобрение заявки НА КОНКРЕТНУЮ СМЕНУ (bot-update.md §2.3.C) — остальные смены той
    же заявки (если их несколько) не затрагиваются."""
    _, application_id_s, shift_id_s = callback.data.split(':')
    application_id, shift_id = int(application_id_s), int(shift_id_s)
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    application, error = await sync_to_async(services.process_application_shift_decision)(
        user.id, application_id, shift_id, approve=True
    )
    await callback.answer()
    if error == 'forbidden':
        await callback.message.answer('⛔ Ты не тим-лидер этого мероприятия.')
        return
    if error:
        await callback.message.answer('⚠️ Заявка или смена не найдена.')
        return

    await sync_to_async(services.notify_manager_processed_application)(user.id, application)

    name = f'{application.first_name} {application.last_name or ""}'.strip()
    await callback.message.answer(f'✅ Заявка {name} одобрена на выбранную смену. Волонтёр получил уведомление.')


@router.callback_query(F.data.startswith('app_profile:'))
async def cb_profile(callback: CallbackQuery):
    application_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )

    application = await sync_to_async(dc.get_application_by_id)(
        application_id, with_event=True, with_user=True
    )
    await callback.answer()
    if not application or not application.user:
        await callback.message.answer('⚠️ Профиль волонтёра недоступен.')
        return

    has_access = await sync_to_async(roles_service.has_extended_access_to_profile)(
        user, application.user
    )
    if not has_access:
        await callback.message.answer(
            '🔒 Доступ к расширенному профилю закрыт: мероприятие завершено.'
        )
        return

    target = application.user
    lines = [
        f'👤 {target.first_name} {target.last_name or ""}'.strip(),
        f'☎ {target.phone}' if target.phone else '',
        f'✉ {target.email}' if target.email else '',
        f'@{target.telegram_username}' if target.telegram_username else '',
    ]
    await answer_with_expiring_keyboard(
        callback.message, '\n'.join(line for line in lines if line),
        kb.profile_comment_button(target.id),
    )


@router.callback_query(F.data.startswith('event_apps_approve_all:'))
async def cb_approve_all(callback: CallbackQuery):
    """Одобрить все заявки на рассмотрении по меро одним действием (tg-bot.md §5.2, TL4)."""
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    approved, error = await sync_to_async(services.process_all_applications)(user.id, event_id)
    await callback.answer()
    if error == 'forbidden':
        await callback.message.answer('⛔ Ты не тим-лидер этого мероприятия.')
        return
    if not approved:
        await callback.message.answer('📋 Заявок на рассмотрении нет.')
        return
    await callback.message.answer(f'✅ Одобрено заявок: {len(approved)}. Волонтёры получили уведомления.')


@router.callback_query(F.data.startswith('event_apps:'))
async def cb_event_apps(callback: CallbackQuery):
    """Показать все заявки на рассмотрении по меро (tg-bot.md §5.2, TL4)."""
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    await callback.answer()
    apps, error = await sync_to_async(services.event_pending_applications)(user.id, event_id)
    if error == 'forbidden':
        await callback.message.answer('⛔ Ты не тим-лидер этого мероприятия.')
        return
    if not apps:
        await callback.message.answer('📋 Заявок на рассмотрении нет.')
        return
    await _send_pending_applications(callback.message, user.id, event_id)


@router.callback_query(F.data.startswith('event_attendance:'))
async def cb_event_attendance(callback: CallbackQuery):
    """Явка после завершения меро — «Были все» / «Были не все» (bot-update.md §2.3.D)."""
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    await callback.answer()
    ready, error = await sync_to_async(services.event_ready_for_attendance)(user.id, event_id)
    if error == 'forbidden':
        await callback.message.answer('⛔ Ты не тим-лидер этого мероприятия.')
        return
    if not ready:
        await callback.message.answer('📋 Явку можно отметить только после завершения мероприятия.')
        return
    await answer_with_expiring_keyboard(
        callback.message, 'Проставь явку по мероприятию:', kb.attendance_all_or_some(event_id),
    )


@router.callback_query(F.data.startswith('attend_all:'))
async def cb_attend_all(callback: CallbackQuery):
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    count, error = await sync_to_async(services.mark_all_attended)(user.id, event_id)
    await callback.answer()
    if error == 'forbidden':
        await callback.message.answer('⛔ Ты не тим-лидер этого мероприятия.')
        return
    if error:
        await callback.message.answer('⚠️ Мероприятие не найдено.')
        return
    await callback.message.edit_text(
        '✅ Отмечено: пришли все. Менеджеру ушло уведомление, что можно забирать табличку для '
        'проставления часов.'
    )


@router.callback_query(F.data.startswith('attend_some:'))
async def cb_attend_some(callback: CallbackQuery):
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    await callback.answer()
    link = await sync_to_async(services.attendance_web_link)(user.id, event_id)
    await callback.message.edit_text(
        'Открой страницу мероприятия — там отметишь, кто был, а кто нет. '
        'Ты авторизуешься автоматически.',
        reply_markup=kb.attendance_web_link_button(link),
    )


@router.callback_query(F.data.startswith('comment:'))
async def cb_comment_start(callback: CallbackQuery, state: FSMContext):
    target_user_id = int(callback.data.split(':', 1)[1])
    await state.update_data(comment_target_user_id=target_user_id)
    await state.set_state(Comment.waiting_text)
    await callback.answer()
    await callback.message.answer('Напиши комментарий к волонтёру:')


@router.message(Comment.waiting_text)
async def comment_got_text(message: Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get('comment_target_user_id')
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    await state.set_state(None)
    await state.clear()

    _, error = await sync_to_async(services.add_user_comment)(
        user.id, target_user_id, message.text
    )
    if error == 'forbidden':
        await message.answer('⛔ У тебя нет доступа к этому действию.')
        return
    if error:
        await message.answer('⚠️ Не удалось сохранить комментарий.')
        return

    await message.answer('📝 Комментарий сохранён (виден менеджерам и тебе в рамках этого меро).')
