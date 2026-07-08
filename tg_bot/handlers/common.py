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
        message.from_user.id, message.from_user.username
    )

    # Deep-link входа на сайт: t.me/<bot>?start=weblogin — авто-регистрация (если
    # новый, останется гостем) + одноразовая ссылка входа в веб-сессию.
    if command is not None and (command.args or '').strip() == 'weblogin':
        await _send_web_login_link(message, user)
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
    parts = (message.text or '').strip().split(maxsplit=1)
    if not parts or not parts[0]:
        await message.answer('Напиши, пожалуйста, как тебя зовут.')
        return
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else None
    await state.update_data(first_name=first_name, last_name=last_name)
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
        user.id, data.get('first_name'), data.get('last_name'), phone
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
