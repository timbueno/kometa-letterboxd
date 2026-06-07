from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kometa_letterboxd.common.kometa import write_collections_section


class KometaYamlTests(unittest.TestCase):
    def test_write_collections_section_does_not_emit_yaml_aliases(self) -> None:
        shared_tags = ["ephemeral", "showdown"]
        collections = {
            "First": {"tmdb_movie": ["1"], "radarr_tag": shared_tags},
            "Second": {"tmdb_movie": ["2"], "radarr_tag": shared_tags},
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "collections.yml"
            path.write_text("collections: {}\n", encoding="utf-8")

            write_collections_section(
                path,
                collections,
                generator="test",
                config_source=Path("config.yml"),
            )

            output = path.read_text(encoding="utf-8")

        self.assertNotIn("&id", output)
        self.assertNotIn("*id", output)
        self.assertEqual(output.count("radarr_tag:"), 2)


if __name__ == "__main__":
    unittest.main()
