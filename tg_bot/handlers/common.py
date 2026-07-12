"""/start, регистрация, /help, общее меню (tg-bot.md §3)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from tg_bot import services, keyboards as kb
from tg_bot.states import Registration, PendingApplication
from tg_bot.templates_loader import render
from tg_bot.ui import answer_with_expiring_keyboard

router = Router(name='common')


async def _menu_for(user) -> tuple:
    is_tl = await sync_to_async(services.user_is_team_leader)(user)
    is_mgr = await sync_to_async(services.user_is_manager)(user)
    return is_tl, is_mgr


async def _send_web_login_link(message: Message, user):
    """Присылает пользователю одноразовую ссылку для входа в веб (deep-link
    `?start=weblogin`). Ссылка живёт 5 минут (раздел 2b)."""
    link = await sync_to_async(services.issue_web_login_link)(user.id)
    if not link or link.startswith('/'):
        # WEBAPP_URL не сконфигурирован — ссылку построить нельзя.
        await message.answer(
            'Не удалось сформировать ссылку для входа — обратитесь к менеджеру центра.'
        )
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🔐 Авторизоваться на сайте', url=link),
    ]])
    await message.answer(
        'Ссылка для авторизации на сайте готова. Она действует <b>5 минут</b> и работает один раз.\n'
        'Перейдите по ней — вы автоматически войдёте на сайт под своим Telegram-аккаунтом.',
        reply_markup=markup,
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject = None):
    await state.clear()
    user, created = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username,
        first_name=message.from_user.first_name, last_name=message.from_user.last_name,
    )

    # Deep-link входа на сайт: t.me/<bot>?start=weblogin — авто-регистрация (если
    # новый, останется гостем) + одноразовая ссылка входа в веб-сессию.
    args = (command.args or '').strip() if command is not None else ''
    if args == 'weblogin':
        await _send_web_login_link(message, user)
        return

    # Deep-link подтверждения Telegram из ЛК: t.me/<bot>?start=verify_<token>.
    # Показываем инициатору («<ФИО> сейчас пытается подтвердить телеграм») кнопки да/нет.
    if args.startswith('verify_'):
        token = args[len('verify_'):]
        name, err = await sync_to_async(services.verify_token_requester)(token)
        if err:
            await message.answer(
                '⚠️ Ссылка для подтверждения недействительна или устарела. '
                'Запросите её заново в личном кабинете на сайте.'
            )
            return
        await message.answer(
            f'🔐 <b>{name}</b> сейчас пытается подтвердить этот Telegram как свой.\n\n'
            'Это вы? Подтвердите, что аккаунт действительно ваш.',
            reply_markup=kb.telegram_verify_prompt(token),
        )
        return

    if not created and not await sync_to_async(services.is_guest)(user):
        is_tl, is_mgr = await _menu_for(user)
        await message.answer(
            render('start_returning', name=user.first_name),
            reply_markup=kb.main_menu(is_tl, is_mgr),
        )
        return

    await message.answer(render('start_new'), reply_markup=kb.guest_menu())


@router.message(Command('login'))
@router.message(Command('weblogin'))
@router.message(F.text == '🔐 Авторизоваться на сайте')
async def cmd_weblogin(message: Message, state: FSMContext):
    """Прислать одноразовую ссылку для входа на сайт (действует 5 минут). Работает
    сразу после /start — не важно, зарегистрирован пользователь в боте или нет:
    линковка идёт по telegram_id, а ФИО при необходимости дозаполняется на сайте."""
    await state.clear()
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    await _send_web_login_link(message, user)


@router.message(Command('help'))
async def cmd_help(message: Message):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )

    if await sync_to_async(services.is_guest)(user):
        await message.answer(render('help_guest'))
        return

    role = await sync_to_async(services.user_role_label)(user)
    text = render('help_volunteer')

    is_tl, is_mgr = await _menu_for(user)
    if is_tl:
        text += render('help_team_leader')
    if is_mgr:
        text += render('help_manager')
    text += render('help_role_footer', role=role)
    await message.answer(text)


async def start_registration(message_or_cb, state: FSMContext):
    await state.set_state(Registration.waiting_name)
    text = render('register_ask_name')
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.answer(text, reply_markup=kb.remove_keyboard())
        await message_or_cb.answer()
    else:
        await message_or_cb.answer(text, reply_markup=kb.remove_keyboard())


@router.message(Command('register'))
@router.message(F.text == '📝 Зарегистрироваться')
async def cmd_register(message: Message, state: FSMContext):
    await start_registration(message, state)


@router.callback_query(F.data == 'register')
async def cb_register(callback: CallbackQuery, state: FSMContext):
    await start_registration(callback, state)


@router.message(Registration.waiting_name)
async def registration_got_name(message: Message, state: FSMContext):
    # Формат ФИО: «Фамилия Имя [Отчество]». Имя — обязательно; фамилия и отчество —
    # опциональны (можно потом дополнить в личном кабинете на сайте).
    parts = (message.text or '').strip().split()
    if not parts:
        await message.answer('Напиши, пожалуйста, как тебя зовут (Фамилия Имя Отчество).')
        return
    last_name = parts[0] if len(parts) >= 2 else None
    first_name = parts[1] if len(parts) >= 2 else parts[0]
    middle_name = parts[2] if len(parts) >= 3 else None
    await state.update_data(first_name=first_name, last_name=last_name, middle_name=middle_name)
    await state.set_state(Registration.waiting_phone)
    await message.answer(
        f'Отлично, {first_name}! Оставишь номер телефона? Он понадобится '
        'тим-лидерам мероприятий, на которые ты подашь заявку.',
        reply_markup=kb.phone_request_keyboard(),
    )


async def _finish_registration(message: Message, state: FSMContext, phone: str = None):
    data = await state.get_data()
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    await sync_to_async(services.complete_registration)(
        user.id, data.get('first_name'), data.get('last_name'), phone,
        middle_name=data.get('middle_name'),
    )
    await state.set_state(None)

    is_tl, is_mgr = await _menu_for(user)
    await message.answer(
        render('register_done'),
        reply_markup=kb.main_menu(is_tl, is_mgr),
    )

    pending = await state.get_data()
    pending_event_id = pending.get('pending_event_id')
    await state.clear()
    if pending_event_id:
        from tg_bot.handlers.volunteer import get_event_title
        title = await sync_to_async(get_event_title)(pending_event_id)
        if title:
            await answer_with_expiring_keyboard(
                message, f'Кстати, ты хотел подать заявку на «{title}» — подать сейчас?',
                kb.confirm_pending_application(pending_event_id),
            )


@router.message(Registration.waiting_phone, F.contact)
async def registration_got_contact(message: Message, state: FSMContext):
    await _finish_registration(message, state, phone=message.contact.phone_number)


@router.message(Registration.waiting_phone, F.text == 'Пропустить')
async def registration_skip_phone(message: Message, state: FSMContext):
    await _finish_registration(message, state, phone=None)


@router.message(Registration.waiting_phone)
async def registration_got_phone_text(message: Message, state: FSMContext):
    phone = (message.text or '').strip()
    await _finish_registration(message, state, phone=phone or None)


@router.message(Command('appnotify'))
@router.message(F.text == '🔔 Заявки: уведомления')
async def cmd_appnotify(message: Message):
    """Тумблер уведомлений о новых заявках (`notify_applications`) — только для ТЛ/менеджера.
    Волонтёру команда недоступна: ему заявки не приходят в принципе (tg-bot.md §5.5, §7)."""
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    is_tl, is_mgr = await _menu_for(user)
    if not (is_tl or is_mgr):
        await message.answer('⛔ У тебя нет доступа к этому действию.')
        return
    enabled = await sync_to_async(services.toggle_application_notifications)(user.id)
    await message.answer(render('appnotify_on' if enabled else 'appnotify_off'))


@router.callback_query(F.data == 'dismiss')
async def cb_dismiss(callback: CallbackQuery, state: FSMContext):
    await state.update_data(pending_event_id=None)
    await callback.answer('Хорошо, вернёшься к этому позже.')


@router.callback_query(F.data.startswith('tgverify_yes:'))
async def cb_tgverify_yes(callback: CallbackQuery):
    """«Да, это я» — верифицируем Telegram и (если был web:*) привязываем реальный id."""
    token = callback.data.split(':', 1)[1]
    user, err = await sync_to_async(services.confirm_telegram_verification)(
        token, callback.from_user.id, callback.from_user.username,
    )
    if err == 'invalid':
        await callback.message.edit_text(
            '⚠️ Ссылка для подтверждения недействительна или устарела. '
            'Запросите её заново в личном кабинете на сайте.'
        )
        await callback.answer()
        return

    text = '✅ Готово! Ваш Telegram подтверждён.'
    if err == 'conflict':
        text += ('\n\n⚠️ Этот Telegram уже привязан к другому аккаунту, поэтому мы только '
                 'отметили подтверждение. Если это ошибка — напишите менеджеру центра.')
    markup = kb.back_to_site_button()
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer('Аккаунт верифицирован')


@router.callback_query(F.data.startswith('tgverify_no:'))
async def cb_tgverify_no(callback: CallbackQuery):
    """«Нет, это не я» — гасим токен и разлогиниваем инициатора на сайте."""
    token = callback.data.split(':', 1)[1]
    _, err = await sync_to_async(services.reject_telegram_verification)(token)
    if err == 'invalid':
        await callback.message.edit_text('⚠️ Ссылка недействительна или уже использована.')
        await callback.answer()
        return
    await callback.message.edit_text(
        '🚫 Подтверждение отклонено. Тот, кто пытался подтвердить этот Telegram, '
        'разлогинен на сайте в целях безопасности.'
    )
    await callback.answer('Отклонено')


# ---------------------------------------------------------------------------
# Fallback: любое сообщение/callback, не пойманное ни одним хендлером выше (во всех
# роутерах — common подключается последним, см. tg_bot/bot.py). Без этого бот на любой
# "не команде" просто молчал — теперь показывает меню/подсказку вместо тишины.
# ---------------------------------------------------------------------------

@router.message()
async def fallback_message(message: Message, state: FSMContext):
    # Если пользователь сейчас в разгаре FSM-диалога (регистрация и т.п.), но прислал
    # что-то, что не подошло ни под один хендлер состояния — не грузим меню поверх
    # диалога, а мягко просим повторить ожидаемый ответ.
    current_state = await state.get_state()
    if current_state:
        await message.answer('Не совсем понял 🤔 Повтори, пожалуйста, предыдущий шаг.')
        return

    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    if await sync_to_async(services.is_guest)(user):
        await message.answer(
            '🤔 Не знаю такую команду. Вот что я умею:',
            reply_markup=kb.guest_menu(),
        )
        return
    is_tl, is_mgr = await _menu_for(user)
    await message.answer(
        '🤔 Не знаю такую команду. Вот что я умею — выбирай из меню ниже или набери /help.',
        reply_markup=kb.main_menu(is_tl, is_mgr),
    )


@router.callback_query()
async def fallback_callback(callback: CallbackQuery):
    # Нажатие на кнопку из "остывшего" (снятого по времени) или уже обработанного
    # сообщения — вместо тишины честно объясняем, что кнопка больше не действует.
    await callback.answer('Эта кнопка уже не активна — обнови список командой из меню.', show_alert=True)
