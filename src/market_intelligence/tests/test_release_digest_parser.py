from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "extract_image_digest.sh"
)


class ReleaseDigestParserTests(unittest.TestCase):
    def test_extracts_digest_from_docker_push_tag_line(self) -> None:
        digest = "a708337d2b231ce5ac5870c30face0de4506fcc479004a6cc1a0160026c738d2"
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            input=f"{('f' * 40)}: digest: sha256:{digest} size: 3658\n",
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), f"sha256:{digest}")

    def test_ignores_progress_lines_and_selects_final_digest(self) -> None:
        first = "1" * 64
        final = "2" * 64
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            input=(
                "layer: Pushed\n"
                f"tag-one: digest: sha256:{first} size: 1\n"
                f"tag-two: digest: sha256:{final} size: 2\n"
            ),
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), f"sha256:{final}")

    def test_rejects_missing_or_invalid_digest(self) -> None:
        for output in ("layer: Pushed\n", f"tag: digest: sha256:{'z' * 64}\n"):
            with self.subTest(output=output):
                result = subprocess.run(
                    ["bash", str(SCRIPT)],
                    input=output,
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("valid SHA-256 digest", result.stderr)


if __name__ == "__main__":
    unittest.main()
