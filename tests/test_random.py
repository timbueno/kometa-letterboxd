from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kometa_letterboxd.collectors.user.random import (
    RandomMovie,
    generate_random_collections,
    select_random_movies,
)
from kometa_letterboxd.common.config import RandomConfig, load_config


def _movies(*tmdb_ids: int) -> list[RandomMovie]:
    return [
        RandomMovie(
            title=f"Movie {tmdb_id}",
            film_url=f"https://letterboxd.com/film/movie-{tmdb_id}/",
            film_slug=f"movie-{tmdb_id}",
            tmdb_id=str(tmdb_id),
        )
        for tmdb_id in tmdb_ids
    ]


def _unresolved_movies(*movie_ids: int) -> list[RandomMovie]:
    return [
        RandomMovie(
            title=f"Movie {movie_id}",
            film_url=f"https://letterboxd.com/film/movie-{movie_id}/",
            film_slug=f"movie-{movie_id}",
        )
        for movie_id in movie_ids
    ]


def _stable_ids(movies: list[RandomMovie]) -> list[str]:
    return [movie.stable_id for movie in movies]


class RandomSelectionTests(unittest.TestCase):
    def test_same_month_produces_identical_results(self) -> None:
        movies = _movies(*range(1, 31))

        first = select_random_movies(
            movies,
            count=10,
            seed="tnmn",
            period_key="2026-06",
        )
        second = select_random_movies(
            movies,
            count=10,
            seed="tnmn",
            period_key="2026-06",
        )

        self.assertEqual(_stable_ids(first), _stable_ids(second))

    def test_different_month_rotates_results(self) -> None:
        movies = _movies(*range(1, 31))

        june = select_random_movies(
            movies,
            count=10,
            seed="tnmn",
            period_key="2026-06",
        )
        july = select_random_movies(
            movies,
            count=10,
            seed="tnmn",
            period_key="2026-07",
        )

        self.assertNotEqual(_stable_ids(june), _stable_ids(july))

    def test_oversized_request_returns_all_movies(self) -> None:
        movies = _movies(1, 2, 3)

        selected = select_random_movies(
            movies,
            count=10,
            seed="tnmn",
            period_key="2026-06",
        )

        self.assertEqual(len(selected), 3)

    def test_source_order_does_not_change_selection(self) -> None:
        movies = _movies(*range(1, 31))

        original = select_random_movies(
            movies,
            count=10,
            seed="tnmn",
            period_key="2026-06",
        )
        reordered = select_random_movies(
            list(reversed(movies)),
            count=10,
            seed="tnmn",
            period_key="2026-06",
        )

        self.assertEqual(_stable_ids(original), _stable_ids(reordered))

    def test_random_collection_outputs_tmdb_ids_and_extra_settings(self) -> None:
        config = RandomConfig.model_validate(
            {
                "collections": [
                    {
                        "name": "Random from TNMN",
                        "url": "https://letterboxd.com/example/list/source/",
                        "count": 3,
                        "seed": "tnmn",
                        "period": "monthly",
                        "sync_mode": "sync",
                        "collection_order": "custom",
                        "radarr_add_missing": True,
                        "radarr_folder": "/media/ephemeral-movies",
                        "radarr_tag": ["ephemeral", "tnmn-random"],
                    }
                ]
            }
        )

        with patch(
            "kometa_letterboxd.collectors.user.random.fetch_letterboxd_list_movies",
            return_value=_movies(*range(1, 11)),
        ):
            collections = generate_random_collections(
                config,
                current_date=datetime.date(2026, 6, 7),
                progress=lambda _message: None,
            )

        entry = collections["Random from TNMN"]
        self.assertIn("tmdb_movie", entry)
        self.assertNotIn("letterboxd_list", entry)
        self.assertEqual(len(entry["tmdb_movie"]), 3)
        self.assertEqual(entry["sync_mode"], "sync")
        self.assertNotIn("collection_order", entry)
        self.assertEqual(entry["show_missing"], True)
        self.assertEqual(entry["radarr_add_missing"], True)
        self.assertEqual(entry["radarr_search"], True)
        self.assertEqual(entry["radarr_folder"], "/media/ephemeral-movies")
        self.assertEqual(entry["radarr_tag"], ["ephemeral", "tnmn-random"])

    def test_random_collection_can_disable_radarr_search(self) -> None:
        config = RandomConfig.model_validate(
            {
                "collections": [
                    {
                        "name": "Random from TNMN",
                        "url": "https://letterboxd.com/example/list/source/",
                        "count": 3,
                        "seed": "tnmn",
                        "radarr_add_missing": True,
                        "radarr_search": False,
                    }
                ]
            }
        )

        with patch(
            "kometa_letterboxd.collectors.user.random.fetch_letterboxd_list_movies",
            return_value=_movies(*range(1, 11)),
        ):
            collections = generate_random_collections(
                config,
                current_date=datetime.date(2026, 6, 7),
                progress=lambda _message: None,
            )

        self.assertEqual(collections["Random from TNMN"]["radarr_search"], False)

    def test_random_collection_can_disable_show_missing(self) -> None:
        config = RandomConfig.model_validate(
            {
                "collections": [
                    {
                        "name": "Random from TNMN",
                        "url": "https://letterboxd.com/example/list/source/",
                        "count": 3,
                        "seed": "tnmn",
                        "show_missing": False,
                    }
                ]
            }
        )

        with patch(
            "kometa_letterboxd.collectors.user.random.fetch_letterboxd_list_movies",
            return_value=_movies(*range(1, 11)),
        ):
            collections = generate_random_collections(
                config,
                current_date=datetime.date(2026, 6, 7),
                progress=lambda _message: None,
            )

        self.assertEqual(collections["Random from TNMN"]["show_missing"], False)

    def test_random_collection_keeps_non_custom_collection_order(self) -> None:
        config = RandomConfig.model_validate(
            {
                "collections": [
                    {
                        "name": "Random from TNMN",
                        "url": "https://letterboxd.com/example/list/source/",
                        "count": 3,
                        "seed": "tnmn",
                        "collection_order": "release.desc",
                    }
                ]
            }
        )

        with patch(
            "kometa_letterboxd.collectors.user.random.fetch_letterboxd_list_movies",
            return_value=_movies(*range(1, 11)),
        ):
            collections = generate_random_collections(
                config,
                current_date=datetime.date(2026, 6, 7),
                progress=lambda _message: None,
            )

        self.assertEqual(
            collections["Random from TNMN"]["collection_order"],
            "release.desc",
        )

    def test_random_collection_omits_custom_order_for_multiple_tmdb_movies(
        self,
    ) -> None:
        config = RandomConfig.model_validate(
            {
                "collections": [
                    {
                        "name": "Random from TNMN",
                        "url": "https://letterboxd.com/example/list/source/",
                        "count": 3,
                        "seed": "tnmn",
                        "collection_order": "custom",
                    }
                ]
            }
        )
        messages: list[str] = []

        with patch(
            "kometa_letterboxd.collectors.user.random.fetch_letterboxd_list_movies",
            return_value=_movies(*range(1, 11)),
        ):
            collections = generate_random_collections(
                config,
                current_date=datetime.date(2026, 6, 7),
                progress=messages.append,
            )

        self.assertNotIn("collection_order", collections["Random from TNMN"])
        self.assertTrue(
            any("Omitting collection_order: custom" in message for message in messages)
        )

    def test_random_collection_resolves_tmdb_ids_only_after_sampling(self) -> None:
        config = RandomConfig.model_validate(
            {
                "collections": [
                    {
                        "name": "Random from TNMN",
                        "url": "https://letterboxd.com/example/list/source/",
                        "count": 3,
                        "seed": "tnmn",
                    }
                ]
            }
        )
        resolver_lengths: list[int] = []

        def populate_selected(movies, **_kwargs) -> None:
            resolver_lengths.append(len(movies))
            for index, movie in enumerate(movies):
                movies[index] = RandomMovie(
                    title=movie.title,
                    film_url=movie.film_url,
                    film_slug=movie.film_slug,
                    tmdb_id=str(index + 100),
                )

        with (
            patch(
                "kometa_letterboxd.collectors.user.random.fetch_letterboxd_list_movies",
                return_value=_unresolved_movies(*range(1, 401)),
            ),
            patch(
                "kometa_letterboxd.collectors.user.random._populate_tmdb_ids",
                side_effect=populate_selected,
            ),
        ):
            collections = generate_random_collections(
                config,
                current_date=datetime.date(2026, 6, 7),
                progress=lambda _message: None,
            )

        self.assertEqual(resolver_lengths, [3])
        self.assertEqual(
            collections["Random from TNMN"]["tmdb_movie"],
            ["100", "101", "102"],
        )


class ConfigCompatibilityTests(unittest.TestCase):
    def test_existing_dated_config_still_loads(self) -> None:
        payload = """
username: your-letterboxd-username
request_timeout: 30
lists_cache: data/user/dated.json
refresh_lists: false

dated:
  kometa_target: /path/to/kometa/config.yml
  letterboxd_prefix: "Movie Night - "
  plex_prefix: "Martin's Movie Night - "
  days_before: 0

tagged:
  tag: plex
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_text(payload, encoding="utf-8")
            config = load_config(path)

        self.assertIsNotNone(config.dated)
        self.assertEqual(
            config.dated.kometa_destination,
            "/path/to/kometa/config.yml",
        )
        self.assertEqual(config.random.collections, [])

    def test_random_only_config_can_define_destination(self) -> None:
        payload = """
random:
  kometa_destination: /path/to/kometa/config.yml
  collections:
    - name: Random from TNMN
      url: https://letterboxd.com/example/list/source/
      count: 10
      seed: tnmn
      period: monthly
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_text(payload, encoding="utf-8")
            config = load_config(path)

        self.assertIsNone(config.username)
        self.assertIsNone(config.dated)
        self.assertEqual(config.random.kometa_destination, "/path/to/kometa/config.yml")
        self.assertEqual(len(config.random.collections), 1)

    def test_repository_example_config_loads(self) -> None:
        config_path = Path(__file__).parents[1] / "config.example.yml"

        config = load_config(config_path)

        self.assertIsNotNone(config.dated)
        self.assertEqual(len(config.random.collections), 1)


if __name__ == "__main__":
    unittest.main()
