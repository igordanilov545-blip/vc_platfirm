"""Тесты единых форматтеров даты (blog/services/formatting.py).

Фиксируют эквивалентность сведённым воедино локальным копиям (_fmt_dt/_fmt_date/…):
покрывают краевые случаи, по которым те расходились — None, date, datetime, не-дата.
"""
import datetime

from django.test import TestCase

from blog.services.formatting import fmt_date, fmt_dt, DASH


class FmtDateTests(TestCase):
    def test_none_and_empty(self):
        self.assertEqual(fmt_date(None), DASH)
        self.assertEqual(fmt_date(''), DASH)

    def test_date(self):
        self.assertEqual(fmt_date(datetime.date(2026, 9, 11)), '11.09.2026')

    def test_datetime_ignores_time(self):
        self.assertEqual(fmt_date(datetime.datetime(2026, 9, 11, 14, 30)), '11.09.2026')

    def test_non_date_falls_back_to_str(self):
        self.assertEqual(fmt_date('всё время'), 'всё время')


class FmtDtTests(TestCase):
    def test_none(self):
        self.assertEqual(fmt_dt(None), DASH)

    def test_datetime_with_time(self):
        self.assertEqual(fmt_dt(datetime.datetime(2026, 9, 11, 14, 30)), '11.09.2026 14:30')

    def test_datetime_without_time_flag(self):
        self.assertEqual(fmt_dt(datetime.datetime(2026, 9, 11, 14, 30), with_time=False), '11.09.2026')

    def test_date_has_no_time_component(self):
        # date без hour → время не дописываем даже при with_time=True (авто-режим)
        self.assertEqual(fmt_dt(datetime.date(2026, 9, 11)), '11.09.2026')

    def test_non_date_falls_back_to_str(self):
        self.assertEqual(fmt_dt('—'), '—')
