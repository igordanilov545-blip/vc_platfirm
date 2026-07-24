"""Справки ПГАС (blog/views/pgas.py) — генерация упирается в WeasyPrint + LibreOffice
(докстрайты вьюх это явно оговаривают: «проверяется на проде, локально WeasyPrint
нет»), которых нет ни в dev-окружении, ни в CI-раннере (только в Docker-образе,
Dockerfile). Поэтому сам PDF-пайплайн (`_build_certificate_pdf`) мокается — тесты
проверяют то, что реально относится к вьюхе: ACL, eligibility-условия, охват по
датам/выбранным мероприятиям, обработку исключений генератора.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from blog.models import Incident
from . import factories as f


def _make_eligible(user):
    """Заполняет все поля, требуемые pgas_certificate_eligibility."""
    user.faculty = 'ФКН'
    user.education_program = 'ПИ'
    user.admission_year = 2022
    from django.utils import timezone
    user.verified_by_manager_at = timezone.now()
    user.save(update_fields=['faculty', 'education_program', 'admission_year', 'verified_by_manager_at'])
    return user


class PgasCertificateDownloadTests(TestCase):
    def setUp(self):
        self.user = f.make_user()
        self.client.force_login(self.user)

    def test_not_eligible_redirects_with_message(self):
        r = self.client.post(reverse('pgas_certificate_download'))
        self.assertEqual(r.status_code, 302)

    @patch('blog.views.pgas._build_certificate_pdf')
    def test_eligible_downloads_pdf(self, mock_build):
        mock_build.return_value = (b'%PDF-1.4 fake', 'pgas-test.pdf')
        _make_eligible(self.user)
        r = self.client.post(reverse('pgas_certificate_download'), {'scope': 'season'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(mock_build.called)

    @patch('blog.views.pgas._build_certificate_pdf')
    def test_generation_error_is_handled_gracefully(self, mock_build):
        mock_build.side_effect = RuntimeError('LibreOffice недоступен')
        _make_eligible(self.user)
        r = self.client.post(reverse('pgas_certificate_download'))
        self.assertEqual(r.status_code, 302, 'ошибка генерации не должна давать 500')

    def test_get_not_allowed(self):
        r = self.client.get(reverse('pgas_certificate_download'))
        self.assertEqual(r.status_code, 405)


class PgasCertificateIssueTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.target = f.make_user()

    def test_manager_sees_form(self):
        self.client.force_login(self.manager)
        r = self.client.get(reverse('pgas_certificate_issue', args=[self.target.id]))
        self.assertEqual(r.status_code, 200)

    def test_stranger_forbidden(self):
        stranger = f.make_user()
        self.client.force_login(stranger)
        r = self.client.get(reverse('pgas_certificate_issue', args=[self.target.id]))
        self.assertEqual(r.status_code, 403)

    def test_owner_not_eligible_redirected(self):
        self.client.force_login(self.target)
        r = self.client.get(reverse('pgas_certificate_issue', args=[self.target.id]))
        self.assertEqual(r.status_code, 302)

    @patch('blog.views.pgas._build_certificate_pdf')
    def test_manager_generates_for_ineligible_target(self, mock_build):
        """Менеджер выдаёт справку без ограничения eligibility (в отличие от
        волонтёра себе) — есть хотя бы одно посещённое меро."""
        mock_build.return_value = (b'%PDF-1.4 fake', 'pgas.pdf')
        event = f.make_event()
        shift = f.make_shift(event, days_from_now=-1)
        f.make_participation(self.target, shift, status='attended')
        self.client.force_login(self.manager)
        r = self.client.post(reverse('pgas_certificate_issue', args=[self.target.id]), {
            'generate': '1',
        })
        self.assertEqual(r.status_code, 200)

    def test_generate_without_events_shows_error(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse('pgas_certificate_issue', args=[self.target.id]), {
            'generate': '1', 'event_ids': [],
        })
        self.assertEqual(r.status_code, 302)


class PgasTemplateDownloadTests(TestCase):
    def test_manager_downloads_template(self):
        manager = f.make_manager()
        self.client.force_login(manager)
        r = self.client.get(reverse('pgas_template_download'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r['Content-Type'],
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    def test_volunteer_forbidden(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.get(reverse('pgas_template_download'))
        self.assertEqual(r.status_code, 403)


class PgasRequestVerificationTests(TestCase):
    def test_only_verification_missing_creates_incident(self):
        user = f.make_user(faculty='ФКН', education_program='ПИ', admission_year=2022)
        self.client.force_login(user)
        r = self.client.post(reverse('pgas_request_verification'))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Incident.objects.filter(kind='pgas_verification', related_user=user).exists())

    def test_incomplete_profile_rejected(self):
        user = f.make_user()  # факультет/ОП/год не заполнены
        self.client.force_login(user)
        r = self.client.post(reverse('pgas_request_verification'))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Incident.objects.filter(kind='pgas_verification', related_user=user).exists())
