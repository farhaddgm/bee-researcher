import unittest
from pathlib import Path

from scripts.check_csp_inline_budget import (
    DEFAULT_MAX_ONCLICK,
    DEFAULT_MAX_STYLE,
    check_budget,
    count_inline_attributes,
)


class CSPMigrationBudgetTest(unittest.TestCase):
    def test_current_backoffice_is_within_the_staged_budget(self):
        source = (Path(__file__).resolve().parents[1] / "app" / "admin_ui.py").read_text(encoding="utf-8")
        counts = check_budget(source)
        self.assertLessEqual(counts["onclick"], DEFAULT_MAX_ONCLICK)
        self.assertLessEqual(counts["style"], DEFAULT_MAX_STYLE)
        # The source observability panel and final admin design layer add two
        # audited style blocks.
        self.assertEqual(53, counts["style"])

    def test_budget_fails_closed_when_an_inline_attribute_is_added(self):
        with self.assertRaises(ValueError):
            check_budget('<button onclick="run()">', max_onclick=0)
        with self.assertRaises(ValueError):
            check_budget('<div style="color:red">', max_style=0)

    def test_counter_is_case_insensitive_and_does_not_count_plain_words(self):
        counts = count_inline_attributes("onclick = 'a' STYLE='b' style-name='c' data-style='d'")
        self.assertEqual({"onclick": 1, "style": 2}, counts)

    def test_counter_ignores_dom_property_assignments(self):
        counts = count_inline_attributes("button.onclick=run; element.style=color; <button onclick=\"run()\">")
        self.assertEqual({"onclick": 1, "style": 0}, counts)

    def test_runtime_migrator_covers_legacy_handlers_and_styles(self):
        source = (Path(__file__).resolve().parents[1] / "app" / "admin_ui.py").read_text(encoding="utf-8")
        self.assertIn("MI-208: migrate legacy HTML attributes", source)
        self.assertIn("cspInlineStyleMap", source)
        self.assertIn("migrateHandler", source)

    def test_runtime_migrator_uses_single_escaped_javascript_patterns(self):
        source = (Path(__file__).resolve().parents[1] / "app" / "admin_ui.py").read_text(encoding="utf-8")
        migrator_lines = [
            line for line in source.splitlines()
            if "function parseArg" in line or "function migrateHandler" in line
        ]
        self.assertEqual(2, len(migrator_lines))
        joined = "\n".join(migrator_lines)
        self.assertIn(r"function decodeQuoted(value)", source)
        self.assertIn(r"value[value.length-1]", joined)
        self.assertIn(r"/^-?\d+(?:\.\d+)?$/", joined)
        self.assertIn(r"/^([A-Za-z_$][\w$]*)\(([\s\S]*)\)\s*;?$/", joined)
        self.assertNotIn(r"[\\w$]", joined)
        self.assertNotIn(r"\\d", joined)
        self.assertNotIn(".at(-1)", joined)


if __name__ == "__main__":
    unittest.main()
