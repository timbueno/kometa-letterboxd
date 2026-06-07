from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kometa_letterboxd.collectors.featured.showdown.latest import (
    build_latest_showdown_collection,
    format_showdown_collection_name,
    generate_latest_showdown_collections,
    select_latest_completed_showdowns,
    select_top_showdown_entries,
)
from kometa_letterboxd.collectors.featured.showdown.probe import (
    CREW_LIST_TEMPLATE,
    ShowdownDataset,
    ShowdownEntry,
    ShowdownSummary,
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
