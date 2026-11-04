from ._base import logger, actor


def save_user_appearance(user, fields):
    """Точечная запись проверенных сервисом предпочтений с аудитом владельца."""
    for key, value in fields.items():
        setattr(user, key, value)
    user.save(update_fields=list(fields))
    logger.info('UPDATE users appearance: actor=%s user=%s fields=%s', actor(user), user.pk, fields)
