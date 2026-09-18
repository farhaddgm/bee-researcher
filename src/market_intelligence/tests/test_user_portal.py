import unittest

from fastapi.testclient import TestClient

from app.main import app


class UserPortalContractTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_read_only_portal_is_available_and_non_indexable(self):
        response = self.client.get("/user")
        self.assertEqual(200, response.status_code)
        self.assertIn("News reader", response.text)
        self.assertIn("read-only news portal", response.text)
        self.assertIn("/user/api/assistants", response.text)
        self.assertNotIn("/admin/api/assistants", response.text)
        self.assertEqual("noindex, nofollow, noarchive, nosnippet", response.headers["x-robots-tag"])
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertIn('<meta name="googlebot" content="noindex,nofollow,noarchive,nosnippet">', response.text)
        self.assertIn('<meta name="bingbot" content="noindex,nofollow,noarchive,nosnippet">', response.text)
        self.assertIn("nonce-", response.headers["content-security-policy"])

    def test_portal_data_requires_its_own_authenticated_session(self):
        self.assertEqual(401, self.client.get("/user/api/me").status_code)
        self.assertEqual(401, self.client.get("/user/api/assistants").status_code)

    def test_portal_has_no_backoffice_mutation_surface(self):
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        self.assertIn("/user/api/login", paths)
        self.assertIn("/user/api/logout", paths)
        self.assertIn("/user/api/preferences", paths)
        self.assertIn("/user/api/assistants/{assistant_id}/reading-state", paths)
        self.assertIn("/user/api/publications/{publication_id}/reading-state", paths)
        self.assertIn("/user/api/assistants/{assistant_id}/publications", paths)
        self.assertNotIn("/user/api/assistants/{assistant_id}/settings", paths)
        self.assertNotIn("/user/api/mfa/verify", paths)

    def test_portal_feedback_is_explicit_and_separate_from_reading_state(self):
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        self.assertIn("/user/api/publications/{publication_id}/feedback", paths)
        body = self.client.get("/user").text
        self.assertIn("reader-feedback-ui", body)
        self.assertIn("user_feedback_access", body)
        self.assertIn("/user/api/publications/", body)
        # The reader shell calls these functions through its lexical bindings;
        # the feedback hook must therefore be invoked from the core functions,
        # not only through a window-property wrapper.
        self.assertIn("window.__beeReaderCanFeedback=Boolean(user?.user_feedback_access)", body)
        self.assertIn("window.__beeReaderSyncFeedback?.(id)", body)

    def test_portal_login_does_not_expose_mfa_challenge(self):
        response = self.client.get("/user")
        self.assertNotIn("Two-step verification", response.text)
        self.assertNotIn("mfaChallenge", response.text)
        self.assertNotIn("/user/api/mfa/verify", response.text)
        self.assertIn("Reader settings", response.text)
        self.assertNotIn("Page ${state.page} of ${totalPages}", response.text)
        self.assertIn("plainText", response.text)

    def test_portal_login_uses_the_same_authentication_composition_as_admin(self):
        body = self.client.get("/user").text
        self.assertIn('<html lang="en" dir="ltr" data-theme="honey"', body)
        self.assertIn('rel="preload" as="image" href="/assets/bee-researcher-grey.svg"', body)
        self.assertIn('rel="preload" as="font" href="/assets/Vazirmatn-Regular.woff2"', body)
        self.assertNotIn("cdn.jsdelivr.net/gh/rastikerdar", body)
        self.assertIn('id="login" class="login-shell"', body)
        self.assertIn('<section class="login-card"', body)
        self.assertIn('class="logo"><img class="brand-logo"', body)
        self.assertIn('id="usernameError" class="field-error"', body)
        self.assertIn('id="passwordError" class="field-error"', body)
        self.assertIn('id="loginButton" class="btn primary login-submit"', body)
        self.assertIn('id="loginLanguage" class="language-choice"', body)
        self.assertIn('id="loginLanguageSelect" class="language-select"', body)
        self.assertIn("Authentication is deliberately a shared visual contract", body)
        self.assertIn("html[data-theme=\"honey\"] .login-shell", body)
        self.assertIn('const loginCopy={', body)
        self.assertIn("function setLoginLocale", body)

    def test_priority_queue_and_deep_reading_tools_are_present(self):
        body = self.client.get("/user").text
        self.assertIn('value="priority"', body)
        self.assertIn('id="priorityFilter"', body)
        self.assertIn("priorityScore", body)
        self.assertIn("priorityReason", body)
        self.assertIn('id="priorityNote"', body)
        self.assertIn('class="dialog deep-reading-dialog"', body)
        self.assertIn('id="dialogReadLater"', body)
        self.assertIn('id="dialogHighlight"', body)
        self.assertIn('id="dialogNote"', body)
        self.assertIn('id="dialogTags"', body)
        self.assertIn('id="dialogHighlights"', body)
        self.assertIn('id="saveReadingState"', body)
        self.assertIn("/user/api/publications/", body)

    def test_reader_navigation_and_numbered_pagination_are_present(self):
        body = self.client.get("/user").text
        self.assertIn('id="sidebarSettingsButton"', body)
        self.assertIn('id="sidebarUserName"', body)
        self.assertIn('id="sidebarAccountTrigger"', body)
        self.assertIn('id="sidebarAccountMenu"', body)
        self.assertIn('class="sidebar-logo-mark"', body)
        self.assertIn('id="searchForm"', body)
        self.assertIn('id="sidebarOverlay"', body)
        self.assertIn("setSidebarCollapsed", body)
        self.assertIn('id="pageNumbers"', body)
        self.assertIn('data-page="${value}"', body)
        self.assertNotIn('id="pageStatus"', body)

    def test_reader_settings_has_reset_and_aligned_layout_hooks(self):
        body = self.client.get("/user/settings").text
        self.assertIn('id="resetSettingsButton"', body)
        self.assertIn('id="saveSettingsButton"', body)
        self.assertIn('id="settingsSaveNote"', body)
        self.assertIn('settings-panel .setting', body)
        self.assertNotIn('id="settingsBack"', body)
        self.assertNotIn('Changes are not saved yet.', body)
        self.assertIn('class="shortcut-hint"', body)
        self.assertGreaterEqual(body.count('class="info-button"'), 9)
        self.assertIn('class="setting setting-notification"', body)
        self.assertIn('class="switch-track"', body)

    def test_reader_skeleton_covers_a_full_grid_and_news_help_is_compact(self):
        body = self.client.get("/user").text
        self.assertIn("Array.from({length:count}", body)
        self.assertIn('class="info-button page-info"', body)
        self.assertIn('data-tooltip="Read the same published content selected for your accessible assistants."', body)
        self.assertNotIn('<p>Read the same published content selected for your accessible assistants.</p>', body)

    def test_reader_settings_is_a_dedicated_page(self):
        response = self.client.get("/user/settings")
        self.assertEqual(200, response.status_code)
        self.assertIn('data-user-page="settings"', response.text)
        self.assertIn('id="settingsPanel"', response.text)
        self.assertIn('href="/user/settings"', response.text)
        self.assertIn("isSettingsPage", response.text)

    def test_reader_pages_share_content_width_and_safe_loading_hooks(self):
        feed = self.client.get("/user").text
        settings = self.client.get("/user/settings").text
        for body in (feed, settings):
            self.assertIn('.layout{width:min(1320px,100%);max-width:1320px}', body)
            self.assertIn('.settings-route .layout{max-width:1320px}', body)
            self.assertIn('id="assistantSelect"', body)
            self.assertIn('aria-busy="true"', body)
            self.assertIn('requestSeq', body)
        self.assertIn('preferenceQueue', body)
        self.assertIn('touch=false', body)
        self.assertIn('state.source=params.get(\'source\')||\'\'', feed)
        self.assertIn("if(state.source)params.set('source',state.source)", feed)

    def test_text_direction_is_scoped_to_news_content(self):
        body = self.client.get("/user").text
        self.assertIn('data-news-dir', body)
        self.assertIn('grid.dataset.newsDir', body)
        self.assertNotIn('document.documentElement.dataset.dir', body)


if __name__ == "__main__":
    unittest.main()
