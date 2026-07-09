"""Точка входа для Passenger WSGI на Beget (панель "Python-сайт").

Beget подключает файл с этим именем и ищет в нём переменную ``application``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
