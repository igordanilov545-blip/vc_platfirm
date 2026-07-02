"""FSM-состояния бота (короткоживущие сценарии, не персистентные сущности)."""
from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    """Регистрация волонтёра (tg-bot.md §3.2)."""
    waiting_name = State()
    waiting_phone = State()


class PendingApplication(StatesGroup):
    """Отложенное намерение подать заявку у гостя (tg-bot.md §4.3.1)."""
    event_id = State()


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
