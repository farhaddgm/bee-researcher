import unittest
from pathlib import Path

from app.admin_ui import ADMIN_HTML
from app.user_ui import USER_HTML


class BackofficePresentationTest(unittest.TestCase):
    def test_both_portals_embed_the_same_contract_once(self):
        for html in (ADMIN_HTML, USER_HTML):
            self.assertEqual(html.count('id="backoffice-ui-contract"'), 1)
            self.assertEqual(html.count('id="backoffice-ui-controller"'), 1)
            self.assertIn("window.__beeShowToast", html)
            self.assertIn("#beeUiTooltip", html)

    def test_shared_controller_has_no_paid_or_polling_work(self):
        source = Path(__file__).parents[1].joinpath("app/backoffice_ui.js").read_text()
        for prohibited in ("fetch(", "setInterval(", "MutationObserver(", ".innerHTML=", "onclick="):
            self.assertNotIn(prohibited, source)
        self.assertIn("copy.textContent=message", source)
        self.assertIn("if(!error)node._timer", source)

    def test_loading_hosts_are_actually_cleaned_up(self):
        self.assertNotIn("layer.remove();layer.parentElement?", ADMIN_HTML)
        self.assertIn("host.classList.remove('admin-ux-skeleton-host')", ADMIN_HTML)
        self.assertIn(".assistant-card,#app .view.active .support-v4-card", ADMIN_HTML)
        self.assertNotIn(".sidebar-foot span{display:none}", ADMIN_HTML)

    def test_minimal_settings_and_news_direction_contract_retained(self):
        self.assertIn('id="saveSettingsButton"', USER_HTML)
        self.assertEqual(USER_HTML.count('class="setting"'), 8)
        self.assertIn('class="setting setting-notification"', USER_HTML)
        self.assertIn('Text direction (news only)', USER_HTML)
        self.assertIn("@media(prefers-reduced-motion:reduce)", USER_HTML)


if __name__ == "__main__":
    unittest.main()
