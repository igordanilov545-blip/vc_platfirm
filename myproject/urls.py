from django.contrib import admin
from django.urls import path, include

from tg_bot.webhook import telegram_webhook

urlpatterns = [
    path('admin/', admin.site.urls),
    # Webhook Telegram-бота (shared-хостинг Beget: бот на webhook, не long polling).
    path('tg/webhook/<str:secret>/', telegram_webhook, name='telegram_webhook'),
    path('', include('blog.urls')),
]
