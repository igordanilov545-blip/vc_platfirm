"""Функции волонтёра: мероприятия, заявки, статистика, подписка, оценка (tg-bot.md §4)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from tg_bot import services, keyboards as kb
from tg_bot.states import ApplicationCancel, PendingApplication, Feedback, ShiftSelection
from tg_bot.ui import answer_with_expiring_keyboard
from data_base import data_controller as dc

router = Router(name='volunteer')


def get_event_title(event_id: int):
    event = dc.get_event_by_id(event_id)
    return event.title if event else None


async def _send_events(message: Message, from_user_id: int = None):
    tg_id = from_user_id or message.from_user.id
    # user_id в open_events — это внутренний id пользователя (не telegram_id): нужен, чтобы
    # понять, на какие меро уже подана заявка (тогда вместо «Подать заявку» показываем статус).
    user, _ = await sync_to_async(services.get_or_create_user)(tg_id, message.from_user.username)
    events = await sync_to_async(services.open_events)(limit=7, user_id=user.id)
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
        # Если на это меро уже есть активная заявка — не предлагаем подать ещё раз,
        # а показываем её статус и кнопки посмотреть/изменить (db.md правило 7d).
        if e['my_application_id']:
            lines.append(f"\nℹ️ Ты уже подал(а) заявку на это мероприятие — статус: {e['my_application_status']}.")
            can_cancel, _, _ = await sync_to_async(services.application_cancel_eligibility)(
                user.id, e['my_application_id']
            )
            await answer_with_expiring_keyboard(
                message, '\n'.join(lines),
                kb.existing_application_actions(e['my_application_id'], can_cancel),
            )
        else:
            await answer_with_expiring_keyboard(message, '\n'.join(lines), kb.apply_button(e['id']))


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
    'blacklisted': '⛔ Не можем принять заявку — обратись к менеджеру центра.',
    'not_found': '⚠️ Мероприятие не найдено или снято с публикации.',
}


@router.callback_query(F.data.startswith('apply:'))
async def cb_apply(callback: CallbackQuery, state: FSMContext):
    """«Откликнуться на «…»» — гостя отправляет на регистрацию (запомнив меро),
    авторизованного волонтёра — сразу на экран выбора смен (bot-update.md §2.1.E)."""
    event_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )

    if await sync_to_async(services.is_guest)(user):
        await state.update_data(pending_event_id=event_id)
        await callback.answer()
        await callback.message.answer(
            '📝 Чтобы подать заявку, сначала нужно войти. Ты уже оставлял(а) заявки раньше?',
            reply_markup=None,
        )
        await answer_with_expiring_keyboard(
            callback.message, 'Выбери вариант:', kb.need_auth_actions(),
        )
        return

    await _show_shift_selection(callback.message, state, event_id)
    await callback.answer()


async def _show_shift_selection(message: Message, state: FSMContext, event_id: int,
                                 selected_ids: set = None, editing: bool = False):
    shifts = await sync_to_async(services.event_open_shifts)(event_id)
    if not shifts:
        await message.answer(ERROR_TEXTS['closed'])
        return
    selected_ids = selected_ids or set()
    data = await state.get_data()
    await state.update_data(
        shift_event_id=event_id, shift_selected_ids=list(selected_ids),
        edit_application_id=data.get('edit_application_id') if editing else None,
        shift_editing=editing,
    )
    await state.set_state(ShiftSelection.choosing)
    title = await sync_to_async(get_event_title)(event_id)
    header = f'✏️ «{title}» — измени смены (уже отмечены твои):' if editing else f'🗓 «{title}» — выбери смены:'
    await answer_with_expiring_keyboard(
        message, header,
        kb.shift_selection_keyboard(event_id, shifts, selected_ids, editing=editing),
    )


@router.callback_query(ShiftSelection.choosing, F.data.startswith('shift_pick:'))
async def cb_shift_pick(callback: CallbackQuery, state: FSMContext):
    _, event_id_s, shift_id_s = callback.data.split(':')
    event_id, shift_id = int(event_id_s), int(shift_id_s)
    data = await state.get_data()
    selected_ids = set(data.get('shift_selected_ids') or [])
    editing = bool(data.get('shift_editing'))
    if shift_id in selected_ids:
        selected_ids.discard(shift_id)
    else:
        selected_ids.add(shift_id)
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_shift_selection(callback.message, state, event_id, selected_ids, editing=editing)


@router.callback_query(ShiftSelection.choosing, F.data.startswith('shift_all:'))
async def cb_shift_all(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split(':', 1)[1])
    await callback.answer()
    await _finalize_application(callback, state, event_id, shift_ids=None)


@router.callback_query(ShiftSelection.choosing, F.data.startswith('shift_apply:'))
async def cb_shift_apply(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split(':', 1)[1])
    data = await state.get_data()
    selected_ids = data.get('shift_selected_ids') or []
    await callback.answer()
    if not selected_ids:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await _show_shift_selection(callback.message, state, event_id, set())
        await callback.message.answer('Сначала выбери смену 🙂')
        return
    await _finalize_application(callback, state, event_id, shift_ids=selected_ids)


async def _finalize_application(callback: CallbackQuery, state: FSMContext, event_id: int, shift_ids):
    await state.set_state(None)
    await state.clear()

    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    message = callback.message
    application, error = await sync_to_async(services.apply_to_event)(user.id, event_id, shift_ids)

    if error == 'need_registration':
        await message.answer('📝 Сначала нужно зарегистрироваться — используй /register.')
        return
    if error == 'already_applied':
        can_cancel, _, _ = await sync_to_async(services.application_cancel_eligibility)(
            user.id, application.id
        )
        text = (
            f'ℹ️ У тебя уже есть активная заявка на «{application.event.title}» '
            f'({application.get_status_display()}).'
        )
        await answer_with_expiring_keyboard(
            message, text, kb.existing_application_actions(application.id, can_cancel)
        )
        return
    if error:
        await message.answer(ERROR_TEXTS.get(error, '⚠️ Не получилось подать заявку.'))
        return

    await message.answer(
        f'✅ Твоя заявка на «{application.event.title}» принята на рассмотрение. '
        'Бот пришлёт ответ сюда.'
    )


@router.callback_query(F.data == 'myapp_ok')
async def cb_myapp_ok(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith('myapp_edit:'))
@router.callback_query(F.data.startswith('app_edit:'))
async def cb_application_edit_start(callback: CallbackQuery, state: FSMContext):
    """Редактирование заявки (bot-update.md §2.2.F) — экран выбора смен с уже
    отмеченными текущими сменами заявки; снял все смены → предложение отменить."""
    application_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    application = await sync_to_async(services.get_own_application)(user.id, application_id)
    await callback.answer()
    if not application:
        await callback.message.answer('⚠️ Заявка не найдена.')
        return

    can_cancel, _, late_cancel_hours = await sync_to_async(services.application_cancel_eligibility)(
        user.id, application_id
    )
    if not can_cancel:
        await callback.message.answer(
            f'До мероприятия осталось меньше допустимого ({late_cancel_hours:g} ч) — изменить '
            'заявку через бота нельзя. Для редактирования напишите тим-лидеру.'
        )
        return

    current_shift_ids = await sync_to_async(
        lambda: set(application.selected_shifts.values_list('id', flat=True))
    )()
    await state.update_data(edit_application_id=application_id)
    await _show_shift_selection(
        callback.message, state, application.event_id, current_shift_ids, editing=True,
    )


@router.callback_query(ShiftSelection.choosing, F.data.startswith('shift_edit_apply:'))
async def cb_shift_edit_apply(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    application_id = data.get('edit_application_id')
    selected_ids = data.get('shift_selected_ids') or []
    await state.set_state(None)
    await state.clear()
    await callback.answer()

    if not selected_ids:
        # Снял все смены — по дереву это равносильно отмене заявки: просим причину.
        await callback.message.answer(
            '⚠️ Все смены сняты. Если хочешь отменить заявку — напиши причину отмены:'
        )
        await state.update_data(cancel_application_id=application_id)
        await state.set_state(ApplicationCancel.waiting_reason)
        return

    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    new_application, error = await sync_to_async(services.edit_own_application)(
        user.id, application_id, selected_ids
    )
    if error:
        await callback.message.answer('⚠️ Не удалось изменить заявку — возможно, она уже неактивна.')
        return
    await callback.message.answer(
        f'✅ Новая заявка на «{new_application.event.title}» с обновлёнными сменами отправлена! '
        'Тим-лидер рассмотрит её и пришлёт ответ сюда, в бот.'
    )


@router.callback_query(F.data.startswith('app_cancel:'))
async def cb_application_cancel_start(callback: CallbackQuery, state: FSMContext):
    """Отмена заявки — сначала проверяем срок (`late_cancel_hours`), затем спрашиваем
    обязательную причину (tg-bot.md §4.3.3)."""
    application_id = int(callback.data.split(':', 1)[1])
    user, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    can_cancel, reason_code, late_cancel_hours = await sync_to_async(
        services.application_cancel_eligibility
    )(user.id, application_id)
    await callback.answer()

    if not can_cancel:
        if reason_code == 'too_late':
            await callback.message.answer(
                f'⛔ Отменить заявку можно не позднее чем за {late_cancel_hours:g} ч. до начала '
                'мероприятия — обратись к тим-лидеру или менеджеру напрямую.'
            )
        elif reason_code == 'not_found':
            await callback.message.answer('⚠️ Заявка не найдена.')
        else:
            await callback.message.answer('⚠️ Эта заявка уже неактивна.')
        return

    await state.update_data(cancel_application_id=application_id)
    await state.set_state(ApplicationCancel.waiting_reason)
    await callback.message.answer('Напиши, пожалуйста, причину отмены:')


@router.message(ApplicationCancel.waiting_reason)
async def application_cancel_got_reason(message: Message, state: FSMContext):
    reason = (message.text or '').strip()
    if not reason:
        await message.answer('Причина обязательна — напиши, пожалуйста, коротко почему отменяешь.')
        return

    data = await state.get_data()
    application_id = data.get('cancel_application_id')
    await state.set_state(None)
    await state.clear()

    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    application, error = await sync_to_async(services.cancel_own_application)(
        user.id, application_id, reason
    )
    if error == 'too_late':
        await message.answer(
            '⛔ Не успели — до мероприятия осталось слишком мало времени. '
            'Обратись к тим-лидеру или менеджеру напрямую.'
        )
        return
    if error:
        await message.answer('⚠️ Не удалось отменить заявку — возможно, она уже неактивна.')
        return
    await message.answer(f'❌ Заявка на «{application.event.title}» отменена.')


@router.message(Command('myapps'))
@router.message(F.text == '📝 Мои заявки')
async def cmd_myapps(message: Message):
    """Мои заявки одним сообщением (bot-update.md §2.2.E): дата меро, значок ✅/❌ по
    сменам, ссылка на пост. Кнопки «Редактировать»/«OK» — «OK» просто убирает кнопки."""
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    apps = await sync_to_async(services.my_active_applications)(user.id)
    if not apps:
        await answer_with_expiring_keyboard(
            message, '📝 У тебя пока нет заявок. Посмотри активные мероприятия — вдруг что-то подойдёт.',
            kb.view_events_button(),
        )
        return

    lines = ['📝 Твои заявки:\n']
    for a in apps:
        status_line = a['status_display']
        if a.get('shifts_summary'):
            status_line += f"\n   Смены: {a['shifts_summary']}"
        if a.get('post_link'):
            status_line += f"\n   🔗 {a['post_link']}"
        lines.append(f"• «{a['event_title']}» — 📆 {a['created_at'].strftime('%d.%m.%Y')} — {status_line}\n")
    await message.answer('\n'.join(lines))

    # Кнопки редактирования — отдельным маленьким сообщением на каждую заявку (общий
    # текст уже отправлен одним блоком выше, здесь только действия).
    for a in apps:
        await answer_with_expiring_keyboard(
            message, f"«{a['event_title']}»", kb.myapp_actions(a['id']),
        )


@router.message(Command('stats'))
@router.message(F.text == '📊 Статистика')
async def cmd_stats(message: Message):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    stats = await sync_to_async(services.user_stats)(user.id)

    lines = ['📊 За этот сезон:']
    lines.append(f"• Часов: {stats['season_hours']}")
    lines.append(f"• Мероприятий: {stats['season_events']}")
    if stats['is_star']:
        lines.append('⭐ Звёздочка ПГАС!')
    else:
        lines.append(f"⭐ До «Звёздочки ПГАС» осталось {stats['hours_to_pgas']:g} ч")
    if stats['potential_hours']:
        lines.append(f"⏳ По активным заявкам может добавиться ещё ~{stats['potential_hours']} ч")

    lines.append('\n— За всё время —')
    lines.append(f"• Часов всего: {stats['total_hours']}")
    lines.append(f"• Мероприятий всего: {stats['total_events']}")

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
    await answer_with_expiring_keyboard(
        callback.message, 'Спасибо! Хочешь добавить комментарий, или на этом всё?',
        kb.feedback_comment_prompt(),
    )


@router.callback_query(F.data == 'feedback_comment')
async def cb_feedback_comment(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Feedback.waiting_comment)
    await callback.answer()
    await callback.message.answer('Напиши комментарий:')


@router.message(Feedback.waiting_comment)
async def feedback_comment_text(message: Message, state: FSMContext):
    data = await state.get_data()
    feedback_id = data.get('feedback_id')
    if feedback_id:
        await sync_to_async(
            lambda: dc.update_feedback_comment(feedback_id, message.text)
        )()
    await state.set_state(None)
    await message.answer('✅ Спасибо за отзыв!')


@router.callback_query(F.data == 'feedback_done')
async def cb_feedback_done(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer('✅ Спасибо за отзыв!')
