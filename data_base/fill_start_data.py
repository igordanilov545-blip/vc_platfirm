from django.core.management.base import BaseCommand
from blog.models import *


class Command(BaseCommand):
    help = 'Заполняет таблицы начальными данными'

    def handle(self, *args, **options):
        pass