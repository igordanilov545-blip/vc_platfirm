"""FSM-состояния бота (короткоживущие сценарии, не персистентные сущности)."""
from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    """Регистрация волонтёра (tg-bot.md §3.2)."""
    waiting_name = State()
    waiting_phone = State()


class PendingApplication(StatesGroup):
    """Отложенное намерение подать заявку у гостя (tg-bot.md §4.3.1)."""
    event_id = State()


class ShiftSelection(StatesGroup):
    """Выбор смен при подаче/редактировании заявки (bot-update.md §2.1.E) — пул
    отмеченных `EventShift.id` хранится в данных состояния (`selected_shift_ids`)."""
    choosing = State()


class TelegramLogin(StatesGroup):
    """Узнавание гостя по прошлым заявкам, «Вход через Telegram» (bot-update.md §2.1.B).
    Если username сменился и совпадения по нему нет — просим ФИО (`waiting_name`), затем
    ждём подтверждения «Да, это я» / «Нет» по найденному кандидату (`waiting_confirm`)."""
    waiting_name = State()
    waiting_confirm = State()


class WebCredentials(StatesGroup):
    """Установка/сброс логина и пароля для Web Platform (tg-bot.md §3.2–3.3)."""
    waiting_login = State()
    waiting_password = State()


class Attendance(StatesGroup):
    """Простановка явки тим-лидером (tg-bot.md §5.3)."""
    in_progress = State()


class Comment(StatesGroup):
    """Комментарий волонтёру от ТЛ/менеджера (tg-bot.md §5.4)."""
    waiting_text = State()


class Feedback(StatesGroup):
    """Отзыв о мероприятии после участия (tg-bot.md §4.6)."""
    waiting_comment = State()


class ApplicationCancel(StatesGroup):
    """Отмена активной заявки самим волонтёром — причина обязательна
    (tg-bot.md §4.3.3, доступно только пока до меро больше `const.late_cancel_hours`)."""
    waiting_reason = State()
