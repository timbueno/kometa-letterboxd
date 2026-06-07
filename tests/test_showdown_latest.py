from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kometa_letterboxd.collectors.featured.showdown.latest import (
    build_latest_showdown_collection,
    fetch_latest_showdown_dataset,
    format_showdown_collection_name,
    generate_latest_showdown_collections,
    has_explicit_background_setting,
    has_explicit_poster_setting,
    select_latest_completed_showdowns,
    select_top_showdown_entries,
)
from kometa_letterboxd.collectors.featured.showdown.poster import GeneratedPoster
from kometa_letterboxd.collectors.featured.showdown.probe import (
    CREW_LIST_TEMPLATE,
    ShowdownDataset,
    ShowdownEntry,
    ShowdownSummary,
    parse_showdown_background_image,
    parse_showdown_description,
)
from kometa_letterboxd.common.config import ShowdownLatestConfig, load_config


def _summary(
    slug: str,
    title: str,
    logline: str | None,
    status: str | None = None,
) -> ShowdownSummary:
    return ShowdownSummary(
        slug=slug,
        title=title,
        logline=logline,
        status=status,
        showdown_url=f"https://letterboxd.com/showdown/{slug}/",
        crew_list_url=CREW_LIST_TEMPLATE.format(slug=slug),
    )


def _entry(rank: int, slug: str, tmdb_id: str | None = None) -> ShowdownEntry:
    return ShowdownEntry(
        rank=rank,
        film_name=f"Movie {rank}",
        film_slug=slug,
        film_year=2026,
        film_url=f"https://letterboxd.com/film/{slug}/",
        tmdb_id=tmdb_id,
    )


class ShowdownLatestSelectionTests(unittest.TestCase):
    def test_in_progress_showdowns_are_skipped(self) -> None:
        selected = select_latest_completed_showdowns(
            [
                _summary("current", "Current", "Still voting", "In Progress"),
                _summary("short", "Short 'n' Sweet", "Best adaptation"),
                _summary("care", "Intensive Care", "Hospital films"),
            ],
            count=2,
        )

        self.assertEqual([item.slug for item in selected], ["short", "care"])

    def test_only_latest_count_completed_showdowns_are_selected(self) -> None:
        selected = select_latest_completed_showdowns(
            [
                _summary("one", "One", None),
                _summary("two", "Two", None),
                _summary("three", "Three", None),
            ],
            count=2,
        )

        self.assertEqual([item.slug for item in selected], ["one", "two"])

    def test_only_top_entries_are_selected(self) -> None:
        selected = select_top_showdown_entries(
            [_entry(3, "three"), _entry(1, "one"), _entry(2, "two")],
            count=2,
        )

        self.assertEqual([entry.rank for entry in selected], [1, 2])

    def test_collection_name_combines_title_and_logline(self) -> None:
        name = format_showdown_collection_name(
            _summary(
                "short-n-sweet",
                "Short 'n' Sweet",
                "Best adaptation of short to feature",
            )
        )

        self.assertEqual(
            name,
            "Short 'n' Sweet: Best adaptation of short to feature",
        )

    def test_collection_name_can_be_prefixed_with_namespace_emoji(self) -> None:
        config = ShowdownLatestConfig.model_validate(
            {
                "count": 1,
                "entries": 1,
                "namespace_emoji": "🥊",
                "kometa_destination": "/tmp/showdowns.yml",
            }
        )

        def fake_fetch(url, **_kwargs):
            if url == "https://letterboxd.com/showdown/":
                return INDEX_HTML
            if url.endswith("/showdown/short-n-sweet/"):
                return DESCRIPTION_HTML
            if url.endswith("/crew/list/showdown-short-n-sweet/"):
                return crew_html("short")
            raise AssertionError(f"Unexpected URL: {url}")

        def populate_tmdb_ids(datasets, **_kwargs) -> None:
            for dataset in datasets:
                for entry in dataset.entries:
                    entry.tmdb_id = f"{dataset.summary.slug}-{entry.rank}"

        with (
            patch(
                "kometa_letterboxd.collectors.featured.showdown.latest.fetch_html",
                side_effect=fake_fetch,
            ),
            patch(
                "kometa_letterboxd.collectors.featured.showdown.latest."
                "populate_showdown_tmdb_ids",
                side_effect=populate_tmdb_ids,
            ),
        ):
            collections, _destination = generate_latest_showdown_collections(
                config,
                base_path=Path("/base"),
                progress=lambda _message: None,
            )

        collection_name = (
            "🥊 Short 'n' Sweet: Best adaptation of short to feature"
        )
        self.assertIn(collection_name, collections)
        self.assertEqual(
            collections[collection_name]["sort_title"],
            f"Showdown Latest 01 {collection_name}",
        )


class ShowdownLatestCollectionTests(unittest.TestCase):
    def test_showdown_description_preserves_spaces_around_links(self) -> None:
        html = """
<div class="body-text -prose">
  <p>With <a>Backrooms</a>—the eerie new horror—now haunting cinemas.</p>
  <p>Check out these lists by <a>Imani</a>, <a>Frodobatmanvadr</a> and
     <a>Short of the Week</a> for inspiration.</p>
</div>
"""

        description = parse_showdown_description(html)

        self.assertEqual(
            description,
            "With Backrooms—the eerie new horror—now haunting cinemas.\n\n"
            "Check out these lists by Imani, Frodobatmanvadr and "
            "Short of the Week for inspiration.",
        )

    def test_collection_includes_description_and_extra_kometa_fields(self) -> None:
        config = ShowdownLatestConfig.model_validate(
            {
                "count": 2,
                "entries": 5,
                "radarr_add_missing": True,
                "radarr_folder": "/mnt/ephemeral-movies",
                "radarr_tag": ["ephemeral", "showdown"],
                "visible_library": True,
                "visible_home": True,
                "visible_shared": False,
            }
        )
        summary = _summary(
            "short-n-sweet",
            "Short 'n' Sweet",
            "Best adaptation of short to feature",
        )
        summary.description = "A description from Letterboxd."
        dataset = ShowdownDataset(
            summary=summary,
            published_at="2026-06-01T00:00:00Z",
            entries=[_entry(1, "one", "100"), _entry(2, "two", "101")],
        )

        collection = build_latest_showdown_collection(
            dataset,
            config,
            collection_name=format_showdown_collection_name(summary),
            index=1,
            collection_order=None,
        )

        self.assertEqual(collection["tmdb_movie"], ["100", "101"])
        self.assertEqual(collection["sync_mode"], "sync")
        self.assertEqual(collection["show_missing"], True)
        self.assertEqual(collection["radarr_add_missing"], True)
        self.assertEqual(collection["radarr_search"], True)
        self.assertEqual(collection["radarr_folder"], "/mnt/ephemeral-movies")
        self.assertEqual(collection["radarr_tag"], ["ephemeral", "showdown"])
        self.assertEqual(collection["visible_library"], True)
        self.assertEqual(collection["visible_home"], True)
        self.assertEqual(collection["visible_shared"], False)
        self.assertIn("A description from Letterboxd.", collection["summary"])
        self.assertIn(summary.showdown_url, collection["summary"])

    def test_collection_includes_generated_file_poster(self) -> None:
        config = ShowdownLatestConfig.model_validate({})
        summary = _summary(
            "short-n-sweet",
            "Short 'n' Sweet",
            "Best adaptation of short to feature",
        )
        dataset = ShowdownDataset(
            summary=summary,
            published_at="2026-06-01T00:00:00Z",
            entries=[_entry(1, "one", "100")],
        )

        collection = build_latest_showdown_collection(
            dataset,
            config,
            collection_name=format_showdown_collection_name(summary),
            index=1,
            collection_order=None,
            file_poster="/config/assets/showdowns/short-n-sweet.jpg",
            file_background="/config/assets/showdowns/short-n-sweet-background.jpg",
        )

        self.assertEqual(
            collection["file_poster"],
            "/config/assets/showdowns/short-n-sweet.jpg",
        )
        self.assertEqual(
            collection["file_background"],
            "/config/assets/showdowns/short-n-sweet-background.jpg",
        )

    def test_explicit_poster_fields_are_not_replaced(self) -> None:
        config = ShowdownLatestConfig.model_validate(
            {
                "url_poster": "https://example.com/poster.jpg",
                "url_background": "https://example.com/background.jpg",
            }
        )
        summary = _summary("short-n-sweet", "Short 'n' Sweet", None)
        dataset = ShowdownDataset(
            summary=summary,
            published_at="2026-06-01T00:00:00Z",
            entries=[_entry(1, "one", "100")],
        )

        collection = build_latest_showdown_collection(
            dataset,
            config,
            collection_name=format_showdown_collection_name(summary),
            index=1,
            collection_order=None,
            file_poster="/config/assets/showdowns/generated.jpg",
            file_background="/config/assets/showdowns/generated-background.jpg",
        )

        self.assertEqual(collection["url_poster"], "https://example.com/poster.jpg")
        self.assertEqual(
            collection["url_background"],
            "https://example.com/background.jpg",
        )
        self.assertNotIn("file_poster", collection)
        self.assertNotIn("file_background", collection)
        self.assertTrue(has_explicit_poster_setting(config))
        self.assertTrue(has_explicit_background_setting(config))

    def test_radarr_search_can_be_disabled(self) -> None:
        config = ShowdownLatestConfig.model_validate(
            {"radarr_add_missing": True, "radarr_search": False}
        )

        self.assertEqual(config.kometa_extra()["radarr_search"], False)

    def test_generate_fetches_latest_completed_showdowns(self) -> None:
        config = ShowdownLatestConfig.model_validate(
            {
                "count": 2,
                "entries": 2,
                "radarr_add_missing": True,
                "visible_home": True,
                "kometa_destination": "/tmp/showdowns.yml",
            }
        )

        def fake_fetch(url, **_kwargs):
            if url == "https://letterboxd.com/showdown/":
                return INDEX_HTML
            if url.endswith("/showdown/short-n-sweet/"):
                return DESCRIPTION_HTML
            if url.endswith("/showdown/intensive-care/"):
                return DESCRIPTION_HTML
            if url.endswith("/crew/list/showdown-short-n-sweet/"):
                return crew_html("short")
            if url.endswith("/crew/list/showdown-intensive-care/"):
                return crew_html("care")
            raise AssertionError(f"Unexpected URL: {url}")

        def populate_tmdb_ids(datasets, **_kwargs) -> None:
            for dataset in datasets:
                for entry in dataset.entries:
                    entry.tmdb_id = f"{dataset.summary.slug}-{entry.rank}"

        with (
            patch(
                "kometa_letterboxd.collectors.featured.showdown.latest.fetch_html",
                side_effect=fake_fetch,
            ),
            patch(
                "kometa_letterboxd.collectors.featured.showdown.latest."
                "populate_showdown_tmdb_ids",
                side_effect=populate_tmdb_ids,
            ),
        ):
            collections, destination = generate_latest_showdown_collections(
                config,
                base_path=Path("/base"),
                progress=lambda _message: None,
            )

        self.assertEqual(destination, Path("/tmp/showdowns.yml"))
        self.assertEqual(
            list(collections),
            [
                "Short 'n' Sweet: Best adaptation of short to feature",
                "Intensive Care: Best hospital films",
            ],
        )
        self.assertEqual(
            collections[
                "Short 'n' Sweet: Best adaptation of short to feature"
            ]["tmdb_movie"],
            ["short-n-sweet-1", "short-n-sweet-2"],
        )
        self.assertEqual(
            collections["Intensive Care: Best hospital films"]["tmdb_movie"],
            ["intensive-care-1", "intensive-care-2"],
        )
        self.assertEqual(
            collections["Intensive Care: Best hospital films"]["visible_home"],
            True,
        )

    def test_generate_uses_showdown_image_for_generated_poster(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ShowdownLatestConfig.model_validate(
                {
                    "count": 1,
                    "entries": 1,
                    "kometa_destination": "/tmp/showdowns.yml",
                    "poster": {
                        "output_directory": directory,
                        "kometa_path": "/config/assets/showdowns",
                    },
                }
            )

            def fake_fetch(url, **_kwargs):
                if url == "https://letterboxd.com/showdown/":
                    return INDEX_HTML
                if url.endswith("/showdown/short-n-sweet/"):
                    return DESCRIPTION_WITH_BACKGROUND_HTML
                if url.endswith("/crew/list/showdown-short-n-sweet/"):
                    return crew_html("short")
                raise AssertionError(f"Unexpected URL: {url}")

            def populate_tmdb_ids(datasets, **_kwargs) -> None:
                for dataset in datasets:
                    for entry in dataset.entries:
                        entry.tmdb_id = f"{dataset.summary.slug}-{entry.rank}"

            seen_background_urls = []

            def generate_poster(dataset, *_args, **_kwargs):
                seen_background_urls.append(dataset.summary.background_image)
                return GeneratedPoster(
                    Path(directory) / "short-n-sweet.jpg",
                    "/config/assets/showdowns/short-n-sweet.jpg",
                    Path(directory) / "short-n-sweet-background.jpg",
                    "/config/assets/showdowns/short-n-sweet-background.jpg",
                )

            with (
                patch(
                    "kometa_letterboxd.collectors.featured.showdown.latest.fetch_html",
                    side_effect=fake_fetch,
                ),
                patch(
                    "kometa_letterboxd.collectors.featured.showdown.latest."
                    "populate_showdown_tmdb_ids",
                    side_effect=populate_tmdb_ids,
                ),
                patch(
                    "kometa_letterboxd.collectors.featured.showdown.latest."
                    "generate_showdown_poster",
                    side_effect=generate_poster,
                ),
            ):
                collections, _destination = generate_latest_showdown_collections(
                    config,
                    base_path=Path("/base"),
                    progress=lambda _message: None,
                )

        self.assertEqual(seen_background_urls, [SHOWDOWN_BACKGROUND_URL])
        self.assertEqual(
            collections[
                "Short 'n' Sweet: Best adaptation of short to feature"
            ]["file_poster"],
            "/config/assets/showdowns/short-n-sweet.jpg",
        )
        self.assertEqual(
            collections[
                "Short 'n' Sweet: Best adaptation of short to feature"
            ]["file_background"],
            "/config/assets/showdowns/short-n-sweet-background.jpg",
        )


class ShowdownLatestScraperTests(unittest.TestCase):
    def test_showdown_background_image_is_parsed(self) -> None:
        self.assertEqual(
            parse_showdown_background_image(DESCRIPTION_WITH_BACKGROUND_HTML),
            SHOWDOWN_BACKGROUND_URL,
        )

    def test_showdown_background_image_uses_backdrop_attribute(self) -> None:
        html = f"""
<div id="backdrop" data-backdrop="{SHORT_BACKDROP_URL}"
     data-backdrop2x="{SHORT_BACKDROP_2X_URL}"></div>
"""

        self.assertEqual(
            parse_showdown_background_image(html),
            SHORT_BACKDROP_2X_URL,
        )

    def test_showdown_background_image_uses_opengraph_fallback(self) -> None:
        html = f"""
<meta property="og:image" content="{SHORT_BACKDROP_URL}">
"""

        self.assertEqual(
            parse_showdown_background_image(html),
            SHORT_BACKDROP_URL,
        )

    def test_latest_dataset_stores_background_image(self) -> None:
        summary = _summary(
            "short-n-sweet",
            "Short 'n' Sweet",
            "Best adaptation of short to feature",
        )

        def fake_fetch(url, **_kwargs):
            if url.endswith("/showdown/short-n-sweet/"):
                return DESCRIPTION_WITH_BACKGROUND_HTML
            if url.endswith("/crew/list/showdown-short-n-sweet/"):
                return crew_html("short")
            raise AssertionError(f"Unexpected URL: {url}")

        with (
            patch(
                "kometa_letterboxd.collectors.featured.showdown.latest.fetch_html",
                side_effect=fake_fetch,
            ),
            patch(
                "kometa_letterboxd.collectors.featured.showdown.latest."
                "populate_showdown_tmdb_ids",
            ),
        ):
            dataset = fetch_latest_showdown_dataset(
                summary,
                entries=1,
                timeout=30,
                session=object(),
            )

        self.assertEqual(dataset.summary.background_image, SHOWDOWN_BACKGROUND_URL)


class ShowdownLatestConfigTests(unittest.TestCase):
    def test_existing_showdown_config_still_loads_without_latest(self) -> None:
        payload = """
username: your-letterboxd-username
kometa:
  config_path: /path/to/kometa/config.yml
dated:
  kometa_target: /path/to/output.yml
showdown:
  showdown_json: path/to/showdown.json
  state_file: path/to/state.json
  threshold: 6
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_text(payload, encoding="utf-8")
            config = load_config(path)

        self.assertIsNotNone(config.showdown)
        self.assertIsNone(config.showdown_latest)

    def test_showdown_latest_only_config_can_define_destination(self) -> None:
        payload = """
showdown_latest:
  count: 2
  entries: 5
  kometa_destination: /path/to/showdown-latest.yml
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_text(payload, encoding="utf-8")
            config = load_config(path)

        self.assertIsNone(config.dated)
        self.assertIsNotNone(config.showdown_latest)
        self.assertEqual(
            config.showdown_latest.kometa_destination,
            "/path/to/showdown-latest.yml",
        )

    def test_showdown_latest_poster_config_loads(self) -> None:
        payload = """
showdown_latest:
  count: 2
  entries: 5
  kometa_destination: /path/to/showdown-latest.yml
  poster:
    output_directory: ./assets/showdown-latest
    kometa_path: /config/assets/showdown-latest
    logo_path: ./assets/letterboxd-logo.png
    logo_label: SHOWDOWN
    background: true
    width: 800
    height: 1200
    format: png
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_text(payload, encoding="utf-8")
            config = load_config(path)

        self.assertIsNotNone(config.showdown_latest)
        self.assertIsNotNone(config.showdown_latest.poster)
        self.assertEqual(
            config.showdown_latest.poster.output_directory,
            "./assets/showdown-latest",
        )
        self.assertEqual(config.showdown_latest.poster.logo_label, "SHOWDOWN")
        self.assertEqual(config.showdown_latest.poster.background, True)
        self.assertEqual(config.showdown_latest.poster.image_format, "png")


INDEX_HTML = """
<section class="content-teaser">
  <a class="image" href="/showdown/current-showdown/"></a>
  <h3><a>Current Showdown</a></h3>
  <h4>Still voting</h4>
  <span class="badge">In Progress</span>
</section>
<section class="content-teaser">
  <a class="image" href="/showdown/short-n-sweet/"></a>
  <h3><a>Short 'n' Sweet</a></h3>
  <h4>Best adaptation of short to feature</h4>
</section>
<section class="content-teaser">
  <a class="image" href="/showdown/intensive-care/"></a>
  <h3><a>Intensive Care</a></h3>
  <h4>Best hospital films</h4>
</section>
<section class="content-teaser">
  <a class="image" href="/showdown/old-showdown/"></a>
  <h3><a>Old Showdown</a></h3>
  <h4>Older films</h4>
</section>
"""

DESCRIPTION_HTML = """
<div class="body-text -prose">Official Letterboxd Showdown description.</div>
"""

SHOWDOWN_BACKGROUND_URL = (
    "https://a.ltrbxd.com/resized/sm/upload/example"
    "-1200-1200-675-675-crop-fill.jpg"
)

SHORT_BACKDROP_URL = (
    "https://a.ltrbxd.com/resized/sm/upload/11/iu/xs/ry/"
    "short-term-12-1200-1200-675-675-crop-000000.jpg?v=e3f08c6089"
)

SHORT_BACKDROP_2X_URL = (
    "https://a.ltrbxd.com/resized/sm/upload/11/iu/xs/ry/"
    "short-term-12-1920-1920-1080-1080-crop-000000.jpg?v=e3f08c6089"
)

DESCRIPTION_WITH_BACKGROUND_HTML = f"""
<div class="body-text -prose">Official Letterboxd Showdown description.</div>
<script>window.image = "{SHOWDOWN_BACKGROUND_URL}";</script>
"""


def crew_html(prefix: str) -> str:
    return f"""
<p class="list-date"><time datetime="2026-06-01T00:00:00Z"></time></p>
<li class="posteritem">
  <p class="list-number">1</p>
  <div class="react-component" data-item-name="{prefix} One (2026)"
       data-item-slug="{prefix}-one" data-item-link="/film/{prefix}-one/"></div>
</li>
<li class="posteritem">
  <p class="list-number">2</p>
  <div class="react-component" data-item-name="{prefix} Two (2026)"
       data-item-slug="{prefix}-two" data-item-link="/film/{prefix}-two/"></div>
</li>
<li class="posteritem">
  <p class="list-number">3</p>
  <div class="react-component" data-item-name="{prefix} Three (2026)"
       data-item-slug="{prefix}-three" data-item-link="/film/{prefix}-three/"></div>
</li>
"""


if __name__ == "__main__":
    unittest.main()
