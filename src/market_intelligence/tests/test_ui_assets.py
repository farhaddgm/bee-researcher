import re
import unittest
from app.admin_ui import ADMIN_HTML
from app.ui_assets import ASSETS, externalize_document


class UIAssetsTest(unittest.TestCase):
    def test_compiled_document_preserves_all_modules_and_their_order(self):
        body = externalize_document(ADMIN_HTML)
        source_blocks = re.findall(r'<script([^>]*)>([\s\S]*?)</script>', ADMIN_HTML)
        exported = re.findall(r'<script([^>]*)></script>', body)
        self.assertEqual(len(source_blocks), len(exported))
        for (_, source), attributes in zip(source_blocks, exported):
            name = re.search(r'/assets/ui/([^" ]+)', attributes).group(1)
            self.assertEqual(source, ASSETS[name][0])
        self.assertNotRegex(body, r'<style\b')
        self.assertNotRegex(body, r'<script[^>]*>\s*[^<\s]')

    def test_content_hash_changes_with_code_and_duplicate_assets_are_shared(self):
        one = externalize_document('<script id="a">const A=1</script>')
        two = externalize_document('<script id="a">const A=2</script>')
        self.assertNotEqual(one, two)
        self.assertEqual(one, externalize_document('<script id="a">const A=1</script>'))

    def test_external_script_and_json_config_are_not_reinterpreted(self):
        html = '<script src="/a.js"></script><script type="application/json">{"a":1}</script>'
        self.assertEqual(html, externalize_document(html))
