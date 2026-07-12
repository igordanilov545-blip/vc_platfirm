"""Клавиатуры бота. Меню перестраивается по фактическим правам (tg-bot.md §2)."""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from django.conf import settings


def _add_webapp_button(builder: ReplyKeyboardBuilder):
    """Кнопка запуска Mini App (implementation-plan.md, Этап 4.4.5) — только если
    задан публичный HTTPS-адрес. Telegram принимает Web App URL ТОЛЬКО по https://
    (http/localhost вызывают TelegramBadRequest и роняют отправку меню), поэтому на
    локальной разработке (http://127.0.0.1) кнопку просто не показываем."""
    url = (settings.WEBAPP_URL or '').strip()
    if not url.startswith('https://'):
        return
    builder.button(text='🖥 Личный кабинет', web_app=WebAppInfo(url=url.rstrip('/') + '/webapp/'))


# ---------------------------------------------------------------------------
# Reply-клавиатуры (основное меню)
# ---------------------------------------------------------------------------

def guest_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text='📅 Мероприятия')
    builder.button(text='📝 Зарегистрироваться')
    # Подписку на новые мероприятия можно включать/выключать и гостю — уведомления
    # приходят всем активным подписчикам независимо от завершённости регистрации.
    builder.button(text='🔔 Подписка')
    builder.button(text='🔐 Авторизоваться на сайте')
    _add_webapp_button(builder)
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def main_menu(is_team_leader: bool = False, is_manager: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text='📅 Мероприятия')
    builder.button(text='📝 Мои заявки')
    builder.button(text='📊 Статистика')
    builder.button(text='🔔 Подписка')
    builder.button(text='🌐 Перейти на сайт')
    if is_team_leader:
        builder.button(text='👥 Мои мероприятия (ТЛ)')
    if is_manager:
        builder.button(text='⚙️ Управление')
    # Тумблер уведомлений о новых заявках — только у тех, кому они вообще приходят
    # (ТЛ своих меро и менеджеры). Волонтёру эта кнопка не показывается (§5.5).
    if is_team_leader or is_manager:
        builder.button(text='🔔 Заявки: уведомления')
    _add_webapp_button(builder)
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


def telegram_verify_prompt(token: str) -> InlineKeyboardMarkup:
    """Кнопки «Да/Нет» при подтверждении владения Telegram из ЛК (deep-link
    `?start=verify_<token>`). «Да» — верифицируем и привязываем id, «Нет» — гасим токен
    и разлогиниваем инициатора на сайте (blog.services.telegram_verify)."""
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Да, это я', callback_data=f'tgverify_yes:{token}')
    builder.button(text='❌ Нет, это не я', callback_data=f'tgverify_no:{token}')
    builder.adjust(1)
    return builder.as_markup()


def back_to_site_button() -> InlineKeyboardMarkup:
    """Кнопка «Обратно на сайт» после успешного подтверждения Telegram."""
    url = (settings.WEBAPP_URL or '').strip()
    if not url.startswith('https://'):
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text='🌐 Обратно на сайт', url=url.rstrip('/') + '/')
    return builder.as_markup()


def apply_button(event_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Подать заявку', callback_data=f'apply:{event_id}')
    return builder.as_markup()


def applied_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Заявка подана', callback_data='noop')
    return builder.as_markup()


def existing_application_actions(application_id: int, can_cancel: bool) -> InlineKeyboardMarkup:
    """Кнопки при повторной подаче заявки на меро, где уже есть активная (tg-bot.md §4.3.2,
    db.md правило 7d): посмотреть/изменить всегда доступны, отмена — только если до меро
    осталось больше `const.late_cancel_hours` (иначе кнопки нет вовсе, чтобы не провоцировать
    на действие, которое всё равно будет отклонено)."""
    builder = InlineKeyboardBuilder()
    builder.button(text='✏️ Изменить заявку', callback_data=f'app_edit:{application_id}')
    if can_cancel:
        builder.button(text='❌ Отменить заявку', callback_data=f'app_cancel:{application_id}')
    builder.adjust(1)
    return builder.as_markup()


def need_auth_actions() -> InlineKeyboardMarkup:
    """Гость жмёт «Откликнуться» — предлагаем войти по прошлым заявкам или
    зарегистрироваться (bot-update.md §2.1.B/C, узел `need_auth`)."""
    builder = InlineKeyboardBuilder()
    builder.button(text='🔑 Войти через Telegram', callback_data='tg_login')
    builder.button(text='📝 Зарегистрироваться', callback_data='register')
    builder.adjust(1)
    return builder.as_markup()


def recognize_confirm_actions() -> InlineKeyboardMarkup:
    """«Кажется, мы тебя знаем» — подтвердить/отклонить найденный аккаунт
    (bot-update.md §2.1.B, узел `login`)."""
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Да, это я', callback_data='tglogin_yes')
    builder.button(text='Нет, это не я', callback_data='tglogin_no')
    builder.adjust(1)
    return builder.as_markup()


def shift_selection_keyboard(event_id: int, shifts, selected_ids: set) -> InlineKeyboardMarkup:
    """Экран выбора смен при подаче/редактировании заявки (bot-update.md §2.1.E):
    «Выбрать все смены», по кнопке на каждую смену (отмеченные — с ✅), «Подать заявку»."""
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Выбрать все смены', callback_data=f'shift_all:{event_id}')
    for shift in shifts:
        label = f"{shift.day.strftime('%d.%m')} · {shift.start_time.strftime('%H:%M')}–{shift.end_time.strftime('%H:%M')}"
        if shift.id in selected_ids:
            label = f'✅ {label}'
        builder.button(text=label, callback_data=f'shift_pick:{event_id}:{shift.id}')
    builder.button(text='Подать заявку' if not selected_ids else 'Подать заявку ✅', callback_data=f'shift_apply:{event_id}')
    builder.adjust(1)
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


def event_actions(event_id: int) -> InlineKeyboardMarkup:
    """Кнопки под мероприятием в списке `/myevents` (tg-bot.md §5.2, TL4):
    открыть все заявки на рассмотрении или одобрить их одним действием."""
    builder = InlineKeyboardBuilder()
    builder.button(text='📋 Все заявки', callback_data=f'event_apps:{event_id}')
    builder.button(text='✅ Одобрить все заявки', callback_data=f'event_apps_approve_all:{event_id}')
    builder.button(text='📝 Явка', callback_data=f'event_attendance:{event_id}')
    builder.adjust(1)
    return builder.as_markup()


def profile_comment_button(target_user_id: int) -> InlineKeyboardMarkup:
    """Кнопка оставить внутренний комментарий волонтёру (tg-bot.md §5.4)."""
    builder = InlineKeyboardBuilder()
    builder.button(text='📝 Комментарий волонтёру', callback_data=f'comment:{target_user_id}')
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
