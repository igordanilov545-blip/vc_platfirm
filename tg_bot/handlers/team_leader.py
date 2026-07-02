"""Функции тим-лидера: мои мероприятия, обработка заявок, явка, комментарии (tg-bot.md §5)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from tg_bot import services, keyboards as kb
from tg_bot.states import Comment
from blog.services import roles as roles_service

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
        if e['new_applications']:
            await _send_pending_applications(message, user.id, e['id'])


async def _send_pending_applications(message: Message, user_id: int, event_id: int):
    apps, error = await sync_to_async(services.event_pending_applications)(user_id, event_id)
    if error or not apps:
        return
    for a in apps:
        contact = f' (@{a.telegram_username.lstrip("@")})' if a.telegram_username else ''
        phone = f'\n☎ {a.phone}' if a.phone else ''
        text = (
            f'📥 Заявка на «{a.event.title}»\n'
            f'👤 {a.first_name} {a.last_name or ""}'.strip() + contact + phone
        )
        await message.answer(text, reply_markup=kb.application_decision(a.id))


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

    await callback.message.edit_reply_markup(reply_markup=None)
    if approve:
        name = f'{application.first_name} {application.last_name or ""}'.strip()
        await callback.message.answer(f'✅ Заявка {name} одобрена. Волонтёр получил уведомление.')
        if application.event.recruit_status == 'closed':
            await callback.message.answer(
                f'ℹ️ Набор на «{application.event.title}» закрыт — одобренных заявок достаточно.'
            )
    else:
        await callback.message.answer('💤 Заявка переведена в резерв.')


@router.callback_query(F.data.startswith('app_profile:'))
async def cb_profile(callback: CallbackQuery):
    from blog.models import Application
    application_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )

    def _load():
        return Application.objects.select_related('event', 'user').filter(pk=application_id).first()

    application = await sync_to_async(_load)()
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
    await callback.message.answer('\n'.join(line for line in lines if line))


@router.callback_query(F.data.startswith('att:'))
async def cb_attendance(callback: CallbackQuery):
    _, participation_id_s, status = callback.data.split(':')
    participation_id = int(participation_id_s)
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    participation, error = await sync_to_async(services.set_attendance)(
        user.id, participation_id, status
    )
    await callback.answer()
    if error == 'forbidden':
        await callback.message.answer('⛔ Ты не тим-лидер этого мероприятия.')
        return
    if error:
        await callback.message.answer('⚠️ Запись об участии не найдена.')
        return

    await callback.message.answer('✅ Явка сохранена. Часы и статистика волонтёров пересчитаны.')


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
