"""Табличка желающих: ТЛ и менеджеры записывают людей, которые заранее попросились
на будущий забег (documentation/volunteer-wishes.md, tg-bot.md §5.6).

Сценарий: «🙋 Желающие» или /wish → бот просит прислать/переслать сообщение → разбор
и запись (общий сервис с сайтом) → сводка «кого записал» с кнопкой «Отменить запись».
`/wish <текст>` записывает сразу, без второго шага."""
from asgiref.sync import sync_to_async

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from tg_bot import services, keyboards as kb
from tg_bot.states import WishInput
from tg_bot.templates_loader import render
from tg_bot.ui import answer_with_expiring_keyboard

router = Router(name='wishes')


async def _current_user(event):
    user, _ = await sync_to_async(services.get_or_create_user)(
        event.from_user.id, event.from_user.username
    )
    return user


@router.message(Command('wish'))
@router.message(F.text == kb.WISHES_BUTTON)
async def cmd_wish(message: Message, state: FSMContext, command: CommandObject = None):
    user = await _current_user(message)
    if not await sync_to_async(services.can_add_volunteer_wishes)(user.id):
        await message.answer('⛔ Записывать желающих могут тим-лидеры и менеджеры.')
        return
    if command and command.args:
        await _save(message, state, user.id, command.args)
        return
    await state.set_state(WishInput.waiting_text)
    await message.answer(render('wish_prompt'))


@router.message(WishInput.waiting_text)
async def wish_got_text(message: Message, state: FSMContext):
    text = message.text or message.caption or ''
    # Команда или кнопка меню посреди сценария — выходим, а не записываем её как желающего.
    if text.startswith('/') or text in kb.MENU_BUTTONS:
        await state.clear()
        await message.answer('Запись желающих отменена. Нажми нужную кнопку ещё раз.')
        return
    user = await _current_user(message)
    await _save(message, state, user.id, text)


async def _save(message: Message, state: FSMContext, user_id: int, text: str):
    rows, error = await sync_to_async(services.add_volunteer_wishes)(user_id, text)
    if error == 'forbidden':
        await state.clear()
        await message.answer('⛔ Записывать желающих могут тим-лидеры и менеджеры.')
        return
    if error == 'no_people':
        # Состояние не снимаем — можно сразу прислать исправленное сообщение.
        await message.answer(
            '🤔 Не нашёл в сообщении ни @юзернейма, ни телефона, ни ФИО рядом со словом «хочет». '
            'Пришли ещё раз, например: <code>@username хочет на Скорость 21 и 22</code>'
        )
        return
    await state.clear()
    web_url = await sync_to_async(services.volunteer_wishes_web_link)(user_id)
    await answer_with_expiring_keyboard(
        message, services.volunteer_wishes_summary(rows),
        kb.wish_saved_actions(str(rows[0].batch_id), web_url),
    )


@router.callback_query(F.data.startswith('wish_undo:'))
async def cb_wish_undo(callback: CallbackQuery):
    batch_id = callback.data.split(':', 1)[1]
    user = await _current_user(callback)
    deleted, error = await sync_to_async(services.undo_volunteer_wishes)(user.id, batch_id)
    await callback.answer()
    if error == 'forbidden':
        await callback.message.answer('⛔ Отменить запись может только тот, кто её сделал.')
        return
    if error:
        await callback.message.answer('⚠️ Запись уже удалена.')
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f'↩️ Запись отменена, удалено строк: {deleted}.')
