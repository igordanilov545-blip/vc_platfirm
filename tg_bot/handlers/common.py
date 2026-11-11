"""/start, регистрация, /help, общее меню (tg-bot.md §3)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from tg_bot import services, keyboards as kb
from tg_bot.states import Registration, PendingApplication, TelegramLogin
from tg_bot.templates_loader import render
from tg_bot.commands import refresh_chat_commands, help_text_for
from tg_bot.ui import answer_with_expiring_keyboard

router = Router(name='common')


@router.message(Command('get_qr'))
@router.message(F.text.lower().in_({'qr код', 'qr-код', 'qr code', '📱 qr код'}))
async def cmd_get_qr(message: Message):
    """Фото QR доступно сразу после первого появления telegram_id в БД."""
    from aiogram.types import BufferedInputFile
    png = await sync_to_async(services.qr_png_for_telegram)(message.from_user.id)
    if png is None:
        await message.answer('Сначала нажмите /start.')
        return
    await message.answer_photo(BufferedInputFile(png, filename='qr.png'))


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
            'Не удалось сформировать ссылку для входа — напишите менеджеру сообщества.'
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

    await refresh_chat_commands(message.bot, message.chat.id, user)
    if not created and not await sync_to_async(services.is_guest)(user):
        is_tl, is_mgr = await _menu_for(user)
        role = await sync_to_async(services.user_role_label)(user)
        await message.answer(
            render('start_returning', name=user.first_name, role=role),
            reply_markup=kb.main_menu(is_tl, is_mgr),
        )
        return

    await message.answer(render('start_new'), reply_markup=kb.guest_menu())


@router.message(Command('weblogin'))
@router.message(F.text == '🌐 Перейти на сайт')
@router.message(F.text == '🔐 Авторизоваться на сайте')  # та же функция в меню гостя
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

    await refresh_chat_commands(message.bot, message.chat.id, user)
    await message.answer(await sync_to_async(help_text_for)(user))


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


@router.message(Command('login'))
@router.callback_query(F.data == 'tg_login')
async def cmd_or_cb_tg_login(event, state: FSMContext):
    """«Вход через Telegram» — узнавание гостя по прошлым заявкам (bot-update.md §2.1.B,
    узел `login`). Сначала пробуем найти кандидата по текущему username; если username
    сменился (переименовался в Telegram) и совпадения нет — просим ФИО на этом же
    экране и ищем по нему тоже (та же логика матчинга, что и у заявок: username → ФИО)."""
    message = event.message if isinstance(event, CallbackQuery) else event
    tg_username = (event.from_user.username if isinstance(event, CallbackQuery) else message.from_user.username)
    tg_id = event.from_user.id if isinstance(event, CallbackQuery) else message.from_user.id

    user, _ = await sync_to_async(services.get_or_create_user)(tg_id, tg_username)
    if isinstance(event, CallbackQuery):
        await event.answer()

    candidate, name = await sync_to_async(services.recognize_by_telegram)(user.id, tg_username)
    if candidate:
        await _offer_recognized_candidate(message, state, candidate, name)
        return

    await state.set_state(TelegramLogin.waiting_name)
    await message.answer(
        '🔑 Не нашли совпадение по твоему текущему Telegram-имени — возможно, ты менял(а) '
        'username. Напиши, пожалуйста, своё ФИО (как указывал(а) раньше в заявках), '
        'попробуем найти тебя по нему:',
        reply_markup=kb.remove_keyboard(),
    )


async def _offer_recognized_candidate(message: Message, state: FSMContext, candidate, name: str):
    await state.update_data(tglogin_candidate_id=candidate.id)
    await state.set_state(TelegramLogin.waiting_confirm)
    await message.answer(
        f'🔑 Проверяю… Кажется, мы тебя знаем:\n\n👤 {name}\n\nЭто ты?',
        reply_markup=kb.recognize_confirm_actions(),
    )


@router.message(TelegramLogin.waiting_name)
async def tglogin_got_name(message: Message, state: FSMContext):
    parts = (message.text or '').strip().split()
    if not parts:
        await message.answer('Напиши, пожалуйста, ФИО (Фамилия Имя).')
        return
    last_name = parts[0] if len(parts) >= 2 else None
    first_name = parts[1] if len(parts) >= 2 else parts[0]

    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    candidate, name = await sync_to_async(services.recognize_by_telegram)(
        user.id, message.from_user.username, first_name, last_name,
    )
    await state.set_state(None)
    if not candidate:
        await message.answer('Не нашли совпадение по ФИО. Давай зарегистрируемся 👇')
        await start_registration(message, state)
        return
    await _offer_recognized_candidate(message, state, candidate, name)


@router.callback_query(TelegramLogin.waiting_confirm, F.data == 'tglogin_yes')
async def cb_tglogin_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    candidate_id = data.get('tglogin_candidate_id')
    await state.set_state(None)
    await state.clear()
    await callback.answer()

    guest, _ = await sync_to_async(services.get_or_create_user)(
        callback.from_user.id, callback.from_user.username
    )
    account, error = await sync_to_async(services.confirm_recognized_account)(
        guest.id, candidate_id, callback.from_user.id, callback.from_user.username,
    )
    if error == 'collision':
        await callback.message.edit_text(
            '⚠️ Не получилось войти автоматически — напиши менеджеру сообщества, поможем разобраться.'
        )
        return
    if not account:
        await callback.message.edit_text('⚠️ Не получилось найти аккаунт — попробуй зарегистрироваться заново.')
        return

    is_tl, is_mgr = await _menu_for(account)
    await refresh_chat_commands(callback.bot, callback.message.chat.id, account)
    role = await sync_to_async(services.user_role_label)(account)
    await callback.message.edit_text(
        f'✅ С возвращением, {account.first_name}! Ты вошёл(ла) — весь твой прежний опыт '
        f'(часы, меро) на месте.\nСтатус: {role}'
    )
    await callback.message.answer('Что дальше?', reply_markup=kb.main_menu(is_tl, is_mgr))

    pending = await state.get_data()
    pending_event_id = pending.get('pending_event_id')
    await state.clear()
    if pending_event_id:
        from tg_bot.handlers.volunteer import get_event_title, _show_shift_selection
        title = await sync_to_async(get_event_title)(pending_event_id)
        if title:
            await answer_with_expiring_keyboard(
                callback.message, f'Кстати, ты хотел(а) откликнуться на «{title}» — завершить заявку сейчас?',
                kb.confirm_pending_application(pending_event_id),
            )


@router.callback_query(TelegramLogin.waiting_confirm, F.data == 'tglogin_no')
async def cb_tglogin_no(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await callback.answer()
    await callback.message.edit_text('Ок, тогда заведём новый аккаунт. Регистрируемся 👇')
    await start_registration(callback.message, state)


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
    await refresh_chat_commands(message.bot, message.chat.id, user)
    role = await sync_to_async(services.user_role_label)(user)
    await message.answer(
        render('register_done', role=role),
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
    """«Да, это я» — верифицируем Telegram и (если был web:*) привязываем реальный id.
    bot-update.md §2.1.A.0: пользователь при этом автоматически логинится в боте под
    подтверждённым аккаунтом — если он был там ещё гостем, считаем регистрацию/вход
    завершёнными и сразу показываем основное меню его роли."""
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
                 'отметили подтверждение. Если это ошибка — напишите менеджеру сообщества.')
    markup = kb.back_to_site_button()
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer('Аккаунт верифицирован')

    if err != 'conflict' and await sync_to_async(services.is_guest)(user):
        await sync_to_async(services.complete_registration)(user.id, user.first_name or 'Волонтёр')
        is_tl, is_mgr = await _menu_for(user)
        await callback.message.answer(
            'Ты уже авторизован(а) в боте под этим аккаунтом — вот что доступно:',
            reply_markup=kb.main_menu(is_tl, is_mgr),
        )


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
