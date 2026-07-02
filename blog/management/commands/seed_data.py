from django.core.management.base import BaseCommand
from blog.models import Role, EventCategory, DobroStatus


class Command(BaseCommand):
    help = 'Заполняет таблицы начальными данными'

    def handle(self, *args, **options):
        # Роли
        roles_data = ['volunteer', 'manager', 'team_leader']
        
        for role_key in roles_data:
            Role.objects.get_or_create(role=role_key)
        
        self.stdout.write(self.style.SUCCESS('✓ Роли созданы'))

        # Категории мероприятий
        categories_data = ['sport', 'culture', 'education', 'ecology']
        
        for cat_key in categories_data:
            EventCategory.objects.get_or_create(name=cat_key)
        
        self.stdout.write(self.style.SUCCESS('✓ Категории созданы'))

        # Статусы Dobro
        statuses_data = [
            'Зарегистрирован',
            'Подтвержден',
            'Отклонен',
            'В ожидании',
        ]
        
        for status in statuses_data:
            DobroStatus.objects.get_or_create(status=status)
        
        self.stdout.write(self.style.SUCCESS('✓ Статусы Dobro созданы'))
        
        self.stdout.write(self.style.SUCCESS('\nВсе данные успешно загружены!'))