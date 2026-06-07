"""Generate deterministic random Kometa collections from Letterboxd lists."""

from __future__ import annotations

import datetime
import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import cloudscraper
import requests
from bs4 import BeautifulSoup

from kometa_letterboxd.common.config import RandomConfig
from kometa_letterboxd.common.kometa import build_collection_entry

from .lists import LETTERBOXD_BASE, to_letterboxd_url


@dataclass(frozen=True)
class RandomMovie:
    title: str
    film_url: str
    film_slug: str
    tmdb_id: str | None = None

    @property
    def stable_id(self) -> str:
        if self.tmdb_id:
            return f"tmdb:{self.tmdb_id}"
        if self.film_slug:
            return f"letterboxd:{self.film_slug}"
        return f"url:{self.film_url}"


def period_key_for(date: datetime.date, period: str) -> str:
    if period != "monthly":
        raise ValueError(f"Unsupported random period: {period}")
    return date.strftime("%Y-%m")


def select_random_movies(
    movies: Sequence[RandomMovie],
    *,
    count: int,
    seed: str,
    period_key: str,
) -> list[RandomMovie]:
    unique_by_id: dict[str, RandomMovie] = {}
    for movie in sorted(movies, key=lambda item: item.stable_id):
        unique_by_id.setdefault(movie.stable_id, movie)

    ranked = sorted(
        unique_by_id.values(),
        key=lambda movie: (
            hashlib.sha256(
                f"{seed}-{period_key}:{movie.stable_id}".encode()
            ).hexdigest(),
            movie.stable_id,
        ),
    )
    return ranked[:count]


def generate_random_collections(
    random_config: RandomConfig,
    *,
    timeout: int = 30,
    current_date: datetime.date | None = None,
    session: requests.Session | None = None,
    progress: Callable[[str], None] = print,
) -> dict[str, Mapping[str, object]]:
    if not random_config.collections:
        return {}

    today = current_date or datetime.date.today()
    collections: dict[str, Mapping[str, object]] = {}

    for collection_config in random_config.collections:
        period_key = period_key_for(today, collection_config.period)
        progress(
            "\nPreparing random collection "
            f"'{collection_config.name}' for {period_key}..."
        )
        source_movies = fetch_letterboxd_list_movies(
            collection_config.url,
            timeout=timeout,
            session=session,
            progress=progress,
        )
        selected_movies = select_random_movies(
            source_movies,
            count=collection_config.count,
            seed=collection_config.seed,
            period_key=period_key,
        )
        tmdb_ids = [
            str(movie.tmdb_id)
            for movie in selected_movies
            if movie.tmdb_id is not None and str(movie.tmdb_id).strip()
        ]

        progress(
            f"- Selected {len(selected_movies)} of {len(source_movies)} movies "
            f"from {collection_config.url}"
        )

        collections[collection_config.name] = build_collection_entry(
            collection_config.url,
            sort_title=collection_config.name,
            sync_mode=collection_config.sync_mode,
            collection_order=collection_config.collection_order,
            extra=collection_config.kometa_extra(),
            tmdb_ids=tmdb_ids,
        )

    return collections


def fetch_letterboxd_list_movies(
    url: str,
    *,
    timeout: int = 30,
    session: requests.Session | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[RandomMovie]:
    owns_session = session is None
    ses = session or cloudscraper.create_scraper()

    movies_by_url: dict[str, RandomMovie] = {}
    page = 1

    try:
        while True:
            page_url = _list_page_url(url, page)
            response = ses.get(page_url, timeout=timeout)
            if response.status_code == 403:
                time.sleep(3)
                ses = cloudscraper.create_scraper()
                response = ses.get(page_url, timeout=timeout)
            if response.status_code == 404 and page > 1:
                break

            response.raise_for_status()
            page_movies = parse_letterboxd_list_movies(response.text)
            if not page_movies:
                break

            for movie in page_movies:
                movies_by_url.setdefault(movie.film_url, movie)

            if progress:
                progress(f"- Fetched {len(page_movies)} movies from {page_url}")

            if not _has_next_page(response.text, page):
                break

            page += 1

        movies = list(movies_by_url.values())
        _populate_tmdb_ids(movies, session=ses, timeout=timeout, progress=progress)
        return movies
    finally:
        if owns_session:
            ses.close()


def parse_letterboxd_list_movies(html: str) -> list[RandomMovie]:
    soup = BeautifulSoup(html, "html.parser")
    movies: list[RandomMovie] = []

    for li in soup.select("li.posteritem, li.poster-container"):
        component = li.select_one("div.react-component, div.film-poster")
        if not component:
            continue

        title = _first_attribute(
            component,
            "data-item-name",
            "data-film-name",
            "data-original-title",
            "data-film-title",
        )
        slug = _first_attribute(component, "data-item-slug", "data-film-slug")
        link = _first_attribute(
            component,
            "data-item-link",
            "data-target-link",
            "data-film-link",
        )
        if not link:
            anchor = li.select_one("a[href*='/film/']")
            href = anchor.get("href") if anchor else None
            link = href if isinstance(href, str) else ""
        film_url = urljoin(LETTERBOXD_BASE, link) if link else ""
        if not film_url and slug:
            film_url = urljoin(LETTERBOXD_BASE, f"/film/{slug}/")
        if not film_url:
            continue

        movies.append(
            RandomMovie(
                title=title or slug,
                film_url=film_url,
                film_slug=slug or film_url.rstrip("/").split("/")[-1],
            )
        )

    return movies


def _first_attribute(element, *names: str) -> str:
    for name in names:
        value = element.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _populate_tmdb_ids(
    movies: list[RandomMovie],
    *,
    session: requests.Session,
    timeout: int,
    progress: Callable[[str], None] | None = None,
) -> None:
    for index, movie in enumerate(movies):
        if movie.tmdb_id:
            continue
        try:
            response = session.get(movie.film_url, timeout=timeout)
            response.raise_for_status()
            tmdb_id = _extract_tmdb_id_from_film_page(response.text)
        except requests.RequestException as exc:
            if progress:
                progress(f"  ! Failed to fetch TMDB id for {movie.film_url}: {exc}")
            tmdb_id = None

        if not tmdb_id:
            continue

        movies[index] = RandomMovie(
            title=movie.title,
            film_url=movie.film_url,
            film_slug=movie.film_slug,
            tmdb_id=tmdb_id,
        )


def _extract_tmdb_id_from_film_page(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body")
    if body and body.has_attr("data-tmdb-id"):
        tmdb_value = body.get("data-tmdb-id")
        if isinstance(tmdb_value, str):
            tmdb_id = tmdb_value.strip()
            return tmdb_id or None
    return None


def _list_page_url(url: str, page: int) -> str:
    full_url = to_letterboxd_url(url)
    if page == 1:
        return full_url

    parsed = urlparse(full_url)
    path = parsed.path.rstrip("/")
    if path.endswith(f"/page/{page - 1}"):
        path = path.rsplit("/page/", maxsplit=1)[0]
    path = f"{path}/page/{page}/"
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _has_next_page(html: str, current_page: int) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href]"):
        href = link.get("href")
        if not isinstance(href, str):
            continue
        if f"/page/{current_page + 1}/" in href:
            return True
        text = link.get_text(strip=True).lower()
        classes = link.get("class", [])
        if text in {"next", "older"} or "next" in classes:
            return True
    return False
