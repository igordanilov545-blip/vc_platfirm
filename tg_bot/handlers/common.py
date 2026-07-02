"""/start, регистрация, /help, общее меню (tg-bot.md §3)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from tg_bot import services, keyboards as kb
from tg_bot.states import Registration, PendingApplication

router = Router(name='common')


async def _menu_for(user) -> tuple:
    is_tl = await sync_to_async(services.user_is_team_leader)(user)
    is_mgr = await sync_to_async(services.user_is_manager)(user)
    return is_tl, is_mgr


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user, created = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )

    if not created and not await sync_to_async(services.is_guest)(user):
        is_tl, is_mgr = await _menu_for(user)
        await message.answer(
            f'👋 С возвращением, {user.first_name}!',
            reply_markup=kb.main_menu(is_tl, is_mgr),
        )
        return

    await message.answer(
        '👋 Привет! Я бот Волонтёрского центра.\n\n'
        'Здесь можно:\n'
        '• 📅 смотреть мероприятия и подавать на них заявки\n'
        '• 📊 следить за своей статистикой — часами и количеством меро\n'
        '• 🔔 получать уведомления о новых меро и статусах своих заявок\n\n'
        'Пока ты можешь просто посмотреть список мероприятий (📅 Мероприятия).\n'
        'Чтобы подавать заявки и участвовать — нужна короткая регистрация (имя и телефон).',
        reply_markup=kb.guest_menu(),
    )


@router.message(Command('help'))
async def cmd_help(message: Message):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )

    if await sync_to_async(services.is_guest)(user):
        await message.answer(
            'ℹ️ Что я умею:\n\n'
            '/events — посмотреть открытые мероприятия\n'
            '/register — зарегистрироваться, чтобы подавать заявки\n\n'
            'После регистрации станут доступны: подача заявок, статистика, '
            'подписка на новые меро.'
        )
        return

    role = await sync_to_async(services.user_role_label)(user)
    text = (
        'ℹ️ Что я умею:\n\n'
        '/events — открытые мероприятия и подача заявки\n'
        '/myapps — мои активные заявки\n'
        '/stats — моя статистика (часы, мероприятия)\n'
        '/subscribe — подписка на уведомления о новых меро\n'
        '/webaccess — доступ к сайту (логин/пароль)\n'
    )

    is_tl, is_mgr = await _menu_for(user)
    if is_tl:
        text += (
            '\nКак тим-лидер своих мероприятий ты также можешь:\n'
            '/myevents — мои мероприятия и заявки на них (одобрить / в резерв)\n'
            '— проставлять явку участникам после смены\n'
            '— оставлять внутренние комментарии волонтёрам своих меро\n'
        )
    if is_mgr:
        text += (
            '\nКак менеджер тебе также доступно:\n'
            '/allapplications — все заявки по всем мероприятиям\n'
            '— обработка заявок и явка на любом мероприятии\n'
            '— контакты организаторов активных мероприятий\n'
        )
    text += f'\nТвоя роль: {role}.'
    await message.answer(text)


async def start_registration(message_or_cb, state: FSMContext):
    await state.set_state(Registration.waiting_name)
    text = '📝 Регистрация\n\nКак тебя зовут? (имя и фамилия)'
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.answer(text, reply_markup=kb.remove_keyboard())
        await message_or_cb.answer()
    else:
        await message_or_cb.answer(text, reply_markup=kb.remove_keyboard())


@router.message(Command('register'))
@router.message(F.text == '📝 Зарегистрироваться')
async def cmd_register(message: Message, state: FSMContext):
    await _start_registration(message, state)


@router.callback_query(F.data == 'register')
async def cb_register(callback: CallbackQuery, state: FSMContext):
    await _start_registration(callback, state)


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
        '✅ Готово, ты зарегистрирован! Теперь доступны заявки на мероприятия и вся статистика.',
        reply_markup=kb.main_menu(is_tl, is_mgr),
    )

    pending = await state.get_data()
    pending_event_id = pending.get('pending_event_id')
    await state.clear()
    if pending_event_id:
        from tg_bot.handlers.volunteer import get_event_title
        title = await sync_to_async(get_event_title)(pending_event_id)
        if title:
            await message.answer(
                f'Кстати, ты хотел подать заявку на «{title}» — подать сейчас?',
                reply_markup=kb.confirm_pending_application(pending_event_id),
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


@router.callback_query(F.data == 'dismiss')
async def cb_dismiss(callback: CallbackQuery, state: FSMContext):
    await state.update_data(pending_event_id=None)
    await callback.answer('Хорошо, вернёшься к этому позже.')
