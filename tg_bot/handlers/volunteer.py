"""Функции волонтёра: мероприятия, заявки, статистика, подписка, оценка (tg-bot.md §4)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from tg_bot import services, keyboards as kb
from tg_bot.states import PendingApplication, Feedback

router = Router(name='volunteer')


def get_event_title(event_id: int):
    from blog.models import Event
    event = Event.objects.filter(pk=event_id).first()
    return event.title if event else None


async def _send_events(message: Message):
    events = await sync_to_async(services.open_events)(limit=7)
    if not events:
        await message.answer(
            '📅 Сейчас нет мероприятий с открытым набором.\n'
            'Подпишись на уведомления (🔔 Подписка) — сообщу, как только появятся новые.'
        )
        return

    await message.answer(f'📅 Открытые мероприятия (ближайшие {len(events)}):')
    for e in events:
        lines = [f"«{e['title']}»"]
        if e['location']:
            lines.append(f"📍 {e['location']}")
        if e['first_day']:
            lines.append(f"📆 Ближайший день: {e['first_day'].strftime('%d.%m.%Y')}")
        if e['description']:
            lines.append(e['description'])
        await message.answer('\n'.join(lines), reply_markup=kb.apply_button(e['id']))


@router.message(Command('events'))
@router.message(F.text == '📅 Мероприятия')
async def cmd_events(message: Message):
    await _send_events(message)


@router.callback_query(F.data == 'events')
async def cb_events(callback: CallbackQuery):
    await callback.answer()
    await _send_events(callback.message)


ERROR_TEXTS = {
    'closed': '⚠️ Набор на это мероприятие уже закрыт.',
    'already_applied': 'ℹ️ У тебя уже есть активная заявка на это мероприятие. '
                        'Статус — в разделе «📝 Мои заявки».',
    'blacklisted': '⛔ Не можем принять заявку — обратись к менеджеру центра.',
    'not_found': '⚠️ Мероприятие не найдено или снято с публикации.',
}


@router.callback_query(F.data.startswith('apply:'))
async def cb_apply(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )

    if await sync_to_async(services.is_guest)(user):
        await state.update_data(pending_event_id=event_id)
        await callback.answer()
        await callback.message.answer(
            '📝 Чтобы подать заявку, сначала нужно зарегистрироваться — это буквально '
            'имя и телефон, 30 секунд.',
            reply_markup=None,
        )
        from tg_bot.handlers.common import start_registration
        await start_registration(callback.message, state)
        return

    application, error = await sync_to_async(services.apply_to_event)(user.id, event_id)

    if error == 'need_registration':
        await callback.answer()
        await callback.message.answer('📝 Сначала нужно зарегистрироваться — используй /register.')
        return
    if error:
        await callback.answer()
        await callback.message.answer(ERROR_TEXTS.get(error, '⚠️ Не получилось подать заявку.'))
        return

    await callback.message.edit_reply_markup(reply_markup=kb.applied_button())
    await callback.answer('Заявка отправлена!')
    await callback.message.answer(
        f'✅ Заявка на «{application.event.title}» отправлена! '
        'Тим-лидер рассмотрит её и пришлёт ответ сюда, в бот.'
    )


@router.message(Command('myapps'))
@router.message(F.text == '📝 Мои заявки')
async def cmd_myapps(message: Message):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    apps = await sync_to_async(services.my_active_applications)(user.id)
    if not apps:
        await message.answer('📝 У тебя пока нет активных заявок. Загляни в «📅 Мероприятия».')
        return

    status_icon = {'new': '🕓 На рассмотрении', 'approved': '✅ Одобрена'}
    lines = ['📝 Твои активные заявки:\n']
    for a in apps:
        icon = status_icon.get(a['status'], a['status_display'])
        lines.append(f"• «{a['event_title']}» — {icon} ({a['created_at'].strftime('%d.%m.%Y')})")
    await message.answer('\n'.join(lines))


@router.message(Command('stats'))
@router.message(F.text == '📊 Статистика')
async def cmd_stats(message: Message):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    stats = await sync_to_async(services.user_stats)(user.id)

    lines = [
        '📊 Твоя статистика\n',
        f"Всего часов: {stats['total_hours']}",
    ]
    season_line = f"Часов за сезон: {stats['season_hours']}"
    if stats['is_star']:
        season_line += '  ⭐ Звёздочка ПГАС!'
    lines.append(season_line)
    lines.append(f"Мероприятий всего: {stats['total_events']}")
    lines.append(f"Мероприятий за сезон: {stats['season_events']}")

    if stats['blacklisted']:
        lines.append('\n⛔ Твой аккаунт заблокирован. Обратись к менеджеру центра.')

    await message.answer('\n'.join(lines))


@router.message(Command('subscribe'))
@router.message(F.text == '🔔 Подписка')
async def cmd_subscribe(message: Message):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    enabled = await sync_to_async(services.toggle_subscription)(user.id)
    if enabled:
        await message.answer('🔔 Подписка включена. Буду присылать уведомления о новых мероприятиях.')
    else:
        await message.answer('🔕 Подписка выключена. Уведомления о новых меро приходить не будут.')


@router.callback_query(F.data.startswith('rate:'))
async def cb_rate(callback: CallbackQuery, state: FSMContext):
    _, event_id_s, rating_s = callback.data.split(':')
    event_id, rating = int(event_id_s), int(rating_s)
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    feedback, error = await sync_to_async(services.submit_feedback)(user.id, event_id, rating)
    await callback.answer()
    if error == 'already_rated':
        await callback.message.answer('Ты уже оценил(а) это мероприятие, спасибо!')
        return
    if error:
        await callback.message.answer('⚠️ Не получилось сохранить оценку.')
        return

    await state.update_data(feedback_id=feedback.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        'Спасибо! Хочешь добавить комментарий, или на этом всё?',
        reply_markup=kb.feedback_comment_prompt(),
    )


@router.callback_query(F.data == 'feedback_comment')
async def cb_feedback_comment(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Feedback.waiting_comment)
    await callback.answer()
    await callback.message.answer('Напиши комментарий:')


@router.message(Feedback.waiting_comment)
async def feedback_comment_text(message: Message, state: FSMContext):
    from blog.models import EventFeedback
    data = await state.get_data()
    feedback_id = data.get('feedback_id')
    if feedback_id:
        await sync_to_async(
            lambda: EventFeedback.objects.filter(pk=feedback_id).update(comment=message.text)
        )()
    await state.set_state(None)
    await message.answer('✅ Спасибо за отзыв!')


@router.callback_query(F.data == 'feedback_done')
async def cb_feedback_done(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer('✅ Спасибо за отзыв!')
