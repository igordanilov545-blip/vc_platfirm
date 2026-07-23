"""Отбивка об одобрении заявки со ссылками меро (чат + Добро.ру) — task-3.

Проверяем: при одобрении в сообщение попадают уже заданные ссылки; недостающие
досылаются позже (send_pending_approval_links) ровно один раз, без дублей.
Инвариант — blog/services/notifications.py (_stamp_links_sent / send_pending_approval_links).
"""
from django.test import TestCase

from blog.models import BotOutbox, Application
from blog.services.applications import process_application
from blog.services.notifications import send_pending_approval_links
from . import factories as f


class ApprovalLinksTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.volunteer = f.make_user()
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=3)
        self.application = f.make_application(
            self.event, user=self.volunteer, shifts=[self.shift], status='new'
        )

    def _vol_messages(self):
        return list(
            BotOutbox.objects.filter(chat_id=self.volunteer.telegram_id).values_list('text', flat=True)
        )

    def test_links_present_at_approval_are_included(self):
        self.event.chat_link = 'https://t.me/chat'
        self.event.dobro_ru_link = 'https://dobro.ru/e/1'
        self.event.save()
        BotOutbox.objects.all().delete()

        process_application(self.application, 'approved', processed_by=self.manager)

        msgs = self._vol_messages()
        self.assertEqual(len(msgs), 1)
        self.assertIn('https://t.me/chat', msgs[0])
        self.assertIn('https://dobro.ru/e/1', msgs[0])

        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.chat_link_sent_at)
        self.assertIsNotNone(self.application.dobro_link_sent_at)

    def test_missing_links_are_resent_when_manager_fills_them(self):
        # Одобряем без ссылок — в сообщении их нет, отметки не проставлены.
        BotOutbox.objects.all().delete()
        process_application(self.application, 'approved', processed_by=self.manager)
        approval = self._vol_messages()
        self.assertEqual(len(approval), 1)
        self.assertNotIn('http', approval[0])
        self.application.refresh_from_db()
        self.assertIsNone(self.application.chat_link_sent_at)
        self.assertIsNone(self.application.dobro_link_sent_at)

        # Менеджер вписал ссылки → досылаем.
        BotOutbox.objects.all().delete()
        self.event.chat_link = 'https://t.me/chat'
        self.event.dobro_ru_link = 'https://dobro.ru/e/1'
        self.event.save()
        n = send_pending_approval_links(self.event)
        self.assertEqual(n, 1)
        resend = self._vol_messages()
        self.assertEqual(len(resend), 1)
        self.assertIn('https://t.me/chat', resend[0])
        self.assertIn('https://dobro.ru/e/1', resend[0])

        # Повторный вызов не должен слать ничего (без дублей).
        BotOutbox.objects.all().delete()
        self.assertEqual(send_pending_approval_links(self.event), 0)
        self.assertEqual(self._vol_messages(), [])

    def test_only_newly_added_link_is_resent(self):
        # Одобряем, когда есть только чат — уходит только он.
        self.event.chat_link = 'https://t.me/chat'
        self.event.save()
        BotOutbox.objects.all().delete()
        process_application(self.application, 'approved', processed_by=self.manager)
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.chat_link_sent_at)
        self.assertIsNone(self.application.dobro_link_sent_at)

        # Позже добавили Добро.ру — досылается ТОЛЬКО добро, без повтора чата.
        BotOutbox.objects.all().delete()
        self.event.dobro_ru_link = 'https://dobro.ru/e/1'
        self.event.save()
        send_pending_approval_links(self.event)
        msgs = self._vol_messages()
        self.assertEqual(len(msgs), 1)
        self.assertIn('https://dobro.ru/e/1', msgs[0])
        self.assertNotIn('https://t.me/chat', msgs[0])
