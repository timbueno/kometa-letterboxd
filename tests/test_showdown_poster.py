from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from kometa_letterboxd.collectors.featured.showdown.poster import (
    background_extension,
    build_kometa_poster_path,
    poster_slug,
    render_showdown_poster,
)
from kometa_letterboxd.collectors.featured.showdown.probe import (
    ShowdownDataset,
    ShowdownSummary,
)
from kometa_letterboxd.common.config import ShowdownPosterConfig

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - depends on optional extra
    Image = None


def _dataset(slug: str = "short-n-sweet") -> ShowdownDataset:
    return ShowdownDataset(
        summary=ShowdownSummary(
            slug=slug,
            title="Short 'n' Sweet",
            logline="Best adaptation of short to feature",
            status=None,
            showdown_url=f"https://letterboxd.com/showdown/{slug}/",
            crew_list_url=f"https://letterboxd.com/crew/list/showdown-{slug}/",
            background_image="https://example.com/background.jpg",
        ),
        published_at="2026-06-01T00:00:00Z",
        entries=[],
    )


class ShowdownPosterPathTests(unittest.TestCase):
    def test_poster_slug_uses_showdown_slug(self) -> None:
        self.assertEqual(poster_slug(_dataset()), "short-n-sweet")

    def test_kometa_path_uses_configured_container_directory(self) -> None:
        config = ShowdownPosterConfig.model_validate(
            {
                "output_directory": "./assets/showdowns",
                "kometa_path": "/config/assets/showdowns",
            }
        )

        self.assertEqual(
            build_kometa_poster_path(Path("/tmp/showdowns/short-n-sweet.jpg"), config),
            "/config/assets/showdowns/short-n-sweet.jpg",
        )

    def test_background_extension_ignores_url_query(self) -> None:
        self.assertEqual(
            background_extension(
                "https://a.ltrbxd.com/sm/upload/example/still.jpg?k=abc"
            ),
            "jpg",
        )


@unittest.skipIf(Image is None, "Pillow optional extra is not installed")
class ShowdownPosterRenderTests(unittest.TestCase):
    def test_render_writes_requested_dimensions(self) -> None:
        assert Image is not None

        background = Image.new("RGB", (800, 450), (46, 80, 118))
        buffer = BytesIO()
        background.save(buffer, format="JPEG")

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "short-n-sweet.jpg"
            logo_path = Path(directory) / "letterboxd-logo.png"
            logo = Image.new("RGBA", (250, 55), (0, 0, 0, 0))
            logo.save(logo_path)

            render_showdown_poster(
                buffer.getvalue(),
                title="Short 'n' Sweet",
                logline="Best adaptation of short to feature",
                output_path=output_path,
                width=320,
                height=480,
                image_format="jpg",
                quality=90,
                logo_path=logo_path,
                logo_label="SHOWDOWN",
            )

            with Image.open(output_path) as poster:
                self.assertEqual(poster.size, (320, 480))


if __name__ == "__main__":
    unittest.main()
