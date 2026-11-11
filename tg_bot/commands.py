"""Единый реестр команд бота (tg-bot.md §0) — меню «/» в Telegram по роли.

Отсюда строится нативное меню команд: общее (для всех, кто ещё не нажимал /start) и
личное для чата по роли пользователя (гость / волонтёр / тим-лидер / менеджер).
Справка (/help, шаблоны help_*.txt) обязана упоминать каждую команду своей роли —
это проверяет blog/tests/test_bot_commands.py. Новая команда = хендлер + строка здесь
+ строка в справке.
"""
from asgiref.sync import sync_to_async

from blog.logging_utils import get_bot_logger

logger = get_bot_logger(__name__)

DESCRIPTIONS = {
    'start': 'Главное меню',
    'events': 'Открытые мероприятия и подача заявки',
    'myapps': 'Мои активные заявки',
    'stats': 'Моя статистика: часы и мероприятия',
    'get_qr': 'Мой QR-код для отметки на сменах',
    'subscribe': 'Уведомления о новых мероприятиях',
    'weblogin': 'Ссылка для входа на сайт',
    'webaccess': 'Логин и пароль для сайта',
    'login': 'Войти, если уже оставлял(а) заявки',
    'register': 'Регистрация',
    'help': 'Что умеет бот',
    'myevents': 'Мои мероприятия (тим-лидер): заявки и явка',
    'wish': 'Записать желающих на будущий забег',
    'appnotify': 'Уведомления о новых заявках: вкл/выкл',
    'allapplications': 'Все заявки и контакты организаторов',
    'publish': 'Опубликовать мероприятие',
    'broadcast': 'Сделать рассылку по мероприятию',
}

GUEST = ('start', 'events', 'get_qr', 'login', 'register', 'subscribe', 'weblogin', 'help')
VOLUNTEER = ('start', 'events', 'myapps', 'stats', 'get_qr', 'subscribe', 'weblogin', 'webaccess', 'help')
TEAM_LEADER = ('myevents', 'wish', 'appnotify')
MANAGER = ('allapplications', 'publish', 'broadcast', 'wish', 'appnotify')


def commands_for(is_guest=False, is_team_leader=False, is_manager=False):
    """[(команда, описание)] для роли; роли аддитивны, порядок — как в меню."""
    names = list(GUEST if is_guest else VOLUNTEER)
    if not is_guest:
        extra = (TEAM_LEADER if is_team_leader else ()) + (MANAGER if is_manager else ())
        names[-1:-1] = [name for index, name in enumerate(extra) if name not in names and name not in extra[:index]]
    return [(name, DESCRIPTIONS[name]) for name in names]


def _bot_commands(items):
    from aiogram.types import BotCommand
    return [BotCommand(command=name, description=description) for name, description in items]


async def set_default_commands(bot):
    """Меню по умолчанию (до /start роль неизвестна) — команды гостя."""
    await bot.set_my_commands(_bot_commands(commands_for(is_guest=True)))


async def refresh_chat_commands(bot, chat_id, user):
    """Личное меню «/» чата по текущей роли. Ошибка Telegram не ломает сценарий."""
    from aiogram.types import BotCommandScopeChat
    from tg_bot import services

    try:
        is_guest = await sync_to_async(services.is_guest)(user)
        is_tl = await sync_to_async(services.user_is_team_leader)(user)
        is_mgr = await sync_to_async(services.user_is_manager)(user)
        await bot.set_my_commands(
            _bot_commands(commands_for(is_guest=is_guest, is_team_leader=is_tl, is_manager=is_mgr)),
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    except Exception:
        logger.warning('Не удалось обновить меню команд чата %s', chat_id, exc_info=True)


def build_help_text(is_guest=False, is_team_leader=False, is_manager=False, role=''):
    """Текст /help по роли из шаблонов help_*.txt. Блоки разделены пустой строкой;
    менеджеру, который ещё и тим-лидер, общие команды (/wish, /appnotify) не дублируются."""
    from tg_bot.templates_loader import render

    if is_guest:
        return render('help_guest')
    text = render('help_volunteer')
    if is_team_leader:
        text += render('help_team_leader')
    if is_manager:
        lines = render('help_manager').split('\n')
        text += '\n'.join(line for line in lines if not (line.startswith('/') and line in text))
    return text + render('help_role_footer', role=role)


def help_text_for(user):
    """Синхронно (через sync_to_async из хендлера): роль пользователя → текст /help."""
    from tg_bot import services

    return build_help_text(
        is_guest=services.is_guest(user),
        is_team_leader=services.user_is_team_leader(user),
        is_manager=services.user_is_manager(user),
        role=services.user_role_label(user),
    )
