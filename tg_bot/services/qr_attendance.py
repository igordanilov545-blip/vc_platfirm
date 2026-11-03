"""Личный QR для бота: только существующий telegram_id, анкета не обязательна."""
from django.db import close_old_connections
from data_base import data_controller as dc
from blog.services.qr_attendance import personal_qr_png


def qr_png_for_telegram(telegram_id):
    """Вернуть фото постоянного QR либо None, если /start ещё не был выполнен."""
    close_old_connections()
    user = dc.get_user_by_telegram_id(telegram_id)
    return personal_qr_png(user) if user else None
