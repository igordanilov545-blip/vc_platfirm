"""A new release must not keep running the previous table search from browser cache."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.template import Context, Template
from django.test import SimpleTestCase, override_settings


@override_settings(DEBUG=True)
class StaticRevisionTests(SimpleTestCase):
    def asset_url(self):
        return Template("{% load custom_tags %}{% versioned_static 'blog/js/tables.js' %}").render(Context())

    def test_browser_gets_a_new_url_when_search_script_changes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'tables.js'
            path.write_text('old search', encoding='utf-8')
            with patch('django.contrib.staticfiles.finders.find', return_value=str(path)):
                old = self.asset_url()
                self.assertEqual(old, self.asset_url())
                path.write_text('new full-table search', encoding='utf-8')
                new = self.asset_url()
                self.assertNotEqual(old, new)
                self.assertTrue(parse_qs(urlsplit(new).query).get('v'))

    def test_production_keeps_existing_manifest_asset_url(self):
        from django.templatetags.static import static
        with override_settings(DEBUG=False):
            self.assertEqual(self.asset_url(), static('blog/js/tables.js'))
