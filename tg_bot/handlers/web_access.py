"""Установка/сброс логина и пароля для Web Platform (tg-bot.md §3.2–3.3)."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from tg_bot import services, keyboards as kb
from tg_bot.states import WebCredentials

router = Router(name='web_access')


@router.message(Command('webaccess'))
@router.message(F.text == '🔐 Доступ к сайту')
async def cmd_webaccess(message: Message, state: FSMContext):
    await state.set_state(WebCredentials.waiting_login)
    await message.answer(
        '🔐 Хочешь входить на сайт сообщества без Telegram?\n\n'
        'Задай логин и пароль — они понадобятся, если Telegram будет недоступен.\n'
        'Придумай логин (3–50 символов: латиница, цифры, точки, дефисы, подчёркивания):',
        reply_markup=kb.remove_keyboard(),
    )


@router.message(WebCredentials.waiting_login)
async def webaccess_got_login(message: Message, state: FSMContext):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    login = (message.text or '').strip()
    error = await sync_to_async(services.validate_login)(login, user.id)
    if error:
        await message.answer(f'⚠️ {error}')
        return
    await state.update_data(login=login)
    await state.set_state(WebCredentials.waiting_password)
    await message.answer('Теперь придумай пароль:')


@router.message(WebCredentials.waiting_password)
async def webaccess_got_password(message: Message, state: FSMContext):
    user, _ = await sync_to_async(services.get_or_create_user)(
        message.from_user.id, message.from_user.username
    )
    data = await state.get_data()
    login = data.get('login')
    password = (message.text or '').strip()

    await sync_to_async(services.set_web_credentials)(user.id, login, password)
    await state.set_state(None)
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    is_tl, is_mgr = (
        await sync_to_async(services.user_is_team_leader)(user),
        await sync_to_async(services.user_is_manager)(user),
    )
    await message.answer(
        '✅ Готово! Теперь можно входить на сайт по логину и паролю.\n'
        '⚠️ Из соображений безопасности удали сообщение с паролем.',
        reply_markup=kb.main_menu(is_tl, is_mgr),
    )
