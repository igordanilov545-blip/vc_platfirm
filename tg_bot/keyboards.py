"""Клавиатуры бота. Меню перестраивается по фактическим правам (tg-bot.md §2)."""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


# ---------------------------------------------------------------------------
# Reply-клавиатуры (основное меню)
# ---------------------------------------------------------------------------

def guest_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text='📅 Мероприятия')
    builder.button(text='📝 Зарегистрироваться')
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def main_menu(is_team_leader: bool = False, is_manager: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text='📅 Мероприятия')
    builder.button(text='📝 Мои заявки')
    builder.button(text='📊 Статистика')
    builder.button(text='🔔 Подписка')
    builder.button(text='🔐 Доступ к сайту')
    if is_team_leader:
        builder.button(text='👥 Мои мероприятия (ТЛ)')
    if is_manager:
        builder.button(text='⚙️ Управление')
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def phone_request_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text='📱 Отправить номер', request_contact=True)
    builder.button(text='Пропустить')
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


# ---------------------------------------------------------------------------
# Inline-клавиатуры
# ---------------------------------------------------------------------------

def start_guest_inline() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='📝 Зарегистрироваться', callback_data='register')
    builder.button(text='📅 Посмотреть мероприятия', callback_data='events')
    builder.adjust(1)
    return builder.as_markup()


def apply_button(event_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Подать заявку', callback_data=f'apply:{event_id}')
    return builder.as_markup()


def applied_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Заявка подана', callback_data='noop')
    return builder.as_markup()


def confirm_pending_application(event_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Да, подать заявку', callback_data=f'apply:{event_id}')
    builder.button(text='Не сейчас', callback_data='dismiss')
    builder.adjust(1)
    return builder.as_markup()


def application_decision(application_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Одобрить', callback_data=f'app_approve:{application_id}')
    builder.button(text='💤 В резерв', callback_data=f'app_reject:{application_id}')
    builder.button(text='👤 Профиль', callback_data=f'app_profile:{application_id}')
    builder.adjust(2, 1)
    return builder.as_markup()


def attendance_row(participation_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Был', callback_data=f'att:{participation_id}:attended')
    builder.button(text='🙁 Уваж.', callback_data=f'att:{participation_id}:absent_excused')
    builder.button(text='⛔ Неявка', callback_data=f'att:{participation_id}:absent_unexcused')
    builder.adjust(3)
    return builder.as_markup()


def rating_keyboard(event_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(1, 11):
        builder.button(text=str(i), callback_data=f'rate:{event_id}:{i}')
    builder.adjust(5)
    return builder.as_markup()


def feedback_comment_prompt() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='💬 Добавить комментарий', callback_data='feedback_comment')
    builder.button(text='Готово', callback_data='feedback_done')
    builder.adjust(1)
    return builder.as_markup()
