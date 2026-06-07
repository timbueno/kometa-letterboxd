"""Fetch and cache Letterboxd showdown datasets."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests import Session

from kometa_letterboxd.common.config import resolve_path

from .storage import load_showdown_cache, save_showdown_cache

BASE_URL = "https://letterboxd.com"
SHOWDOWN_ROOT = f"{BASE_URL}/showdown/"
CREW_LIST_TEMPLATE = f"{BASE_URL}/crew/list/showdown-{{slug}}/"
DEFAULT_TIMEOUT = 15
DEFAULT_HEADERS = {
    "User-Agent": "kometa-letterboxd-showdown/1.0 (+https://letterboxd.com/)"
}
_YEAR_PATTERN = re.compile(r"\((\d{4})\)$")


@dataclass
class ShowdownSummary:
    slug: str
    title: str
    logline: str | None
    status: str | None
    showdown_url: str
    crew_list_url: str
    description: str | None = None
    background_image: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ShowdownSummary:
        return cls(
            slug=str(data.get("slug", "")),
            title=str(data.get("title", "")),
            logline=data.get("logline"),
            status=data.get("status"),
            showdown_url=str(data.get("showdown_url", "")),
            crew_list_url=str(data.get("crew_list_url", "")),
            description=data.get("description"),
            background_image=data.get("background_image"),
        )


@dataclass
class ShowdownEntry:
    rank: int
    film_name: str
    film_slug: str
    film_year: int | None
    film_url: str
    details_endpoint: str | None = None
    tmdb_id: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ShowdownEntry:
        rank_value = data.get("rank", 0)
        try:
            rank_int = int(rank_value)
        except (TypeError, ValueError):
            rank_int = 0
        return cls(
            rank=rank_int,
            film_name=str(data.get("film_name", "")),
            film_slug=str(data.get("film_slug", "")),
            film_year=data.get("film_year"),
            film_url=str(data.get("film_url", "")),
            details_endpoint=data.get("details_endpoint"),
            tmdb_id=data.get("tmdb_id"),
        )

    def ensure_film_url(self) -> str:
        if self.film_url:
            return self.film_url
        slug = self.film_slug.strip("/")
        if slug:
            return urljoin(BASE_URL, f"/film/{slug}/")
        return ""


@dataclass
class ShowdownDataset:
    summary: ShowdownSummary
    published_at: str | None
    entries: list[ShowdownEntry] = field(default_factory=list)

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def has_missing_tmdb_ids(self) -> bool:
        return any(not entry.tmdb_id for entry in self.entries)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ShowdownDataset:
        summary_data = (
            cast(Mapping[str, Any], data.get("summary"))
            if isinstance(data.get("summary"), Mapping)
            else {}
        )
        summary = ShowdownSummary.from_dict(summary_data)
        raw_entries = (
            cast(Sequence[Any], data.get("entries"))
            if isinstance(data.get("entries"), Sequence)
            else []
        )
        entries: list[ShowdownEntry] = []
        for item in raw_entries:
            if isinstance(item, Mapping):
                entries.append(ShowdownEntry.from_dict(cast(Mapping[str, Any], item)))
        published_at = (
            data.get("published_at")
            if isinstance(data.get("published_at"), str)
            else None
        )
        return cls(summary=summary, published_at=published_at, entries=entries)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _ensure_session(session: Session | None) -> Session:
    if session is not None:
        return session
    ses = requests.Session()
    ses.headers.update(DEFAULT_HEADERS)
    return ses


def fetch_html(url: str, *, session: Session, timeout: int) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_showdown_description(html: str) -> str | None:
    """Extract the description from a showdown page."""
    soup = BeautifulSoup(html, "html.parser")

    # Look for the description in the body-text -prose element
    desc_elem = soup.select_one(".body-text.-prose")
    if desc_elem:
        paragraphs = desc_elem.find_all("p")
        if paragraphs:
            text = "\n\n".join(
                _normalize_description_text(paragraph.get_text(" ", strip=True))
                for paragraph in paragraphs
            )
        else:
            text = _normalize_description_text(desc_elem.get_text(" ", strip=True))
        if text and len(text) > 10:  # Basic sanity check
            return text

    return None


def _normalize_description_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+([—–])", r"\1", text)
    text = re.sub(r"([([{])\s+", r"\1", text)
    return text


def parse_showdown_background_image(html: str) -> str | None:
    """Extract the background image URL from a showdown page."""
    # Look for images with the characteristic background dimensions
    pattern = r'https://[^"\']+?-1200-1200-675-675-crop-fill\.jpg'
    matches = re.findall(pattern, html, re.IGNORECASE)

    if matches:
        # Return the first match, they should all be the same image
        return matches[0]

    return None


def parse_showdown_index(html: str) -> list[ShowdownSummary]:
    soup = BeautifulSoup(html, "html.parser")
    summaries: list[ShowdownSummary] = []
    seen_slugs = set()

    for anchor in soup.select("section.content-teaser a.image"):
        href_value = anchor.get("href")
        if not isinstance(href_value, str) or not href_value.startswith("/showdown/"):
            continue
        href = href_value
        slug = href.strip("/").split("/")[-1]
        if not slug or slug in seen_slugs:
            continue

        section = anchor.find_parent("section", class_="content-teaser")
        if not section:
            continue

        title_tag = section.select_one("h3 a")
        logline_tag = section.select_one("h4")
        status_tag = section.select_one("span.badge")

        title = (
            title_tag.get_text(strip=True)
            if title_tag
            else slug.replace("-", " ").title()
        )
        logline = logline_tag.get_text(strip=True) if logline_tag else None
        status = status_tag.get_text(strip=True) if status_tag else None

        summaries.append(
            ShowdownSummary(
                slug=slug,
                title=title,
                logline=logline,
                status=status,
                showdown_url=urljoin(BASE_URL, href),
                crew_list_url=CREW_LIST_TEMPLATE.format(slug=slug),
            )
        )
        seen_slugs.add(slug)

    return summaries


def _extract_year_from_name(name: str) -> int | None:
    match = _YEAR_PATTERN.search(name or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def parse_showdown_crew_list(html: str) -> tuple[str | None, list[ShowdownEntry]]:
    soup = BeautifulSoup(html, "html.parser")

    published_at = None
    published_time = soup.select_one("p.list-date time")
    if published_time and published_time.has_attr("datetime"):
        published_value = published_time.get("datetime")
        if isinstance(published_value, str):
            published_at = published_value.strip() or None

    entries: list[ShowdownEntry] = []
    for li in soup.select("li.posteritem"):
        component = li.select_one("div.react-component")
        if not component:
            continue

        name = str(component.get("data-item-name", "")).strip()
        slug = str(component.get("data-item-slug", "")).strip()
        link = str(component.get("data-item-link", "")).strip()
        details_value = component.get("data-details-endpoint")
        details_endpoint = details_value if isinstance(details_value, str) else None
        film_url = urljoin(BASE_URL, link) if link else ""

        year = _extract_year_from_name(name)

        rank_text = None
        rank_tag = li.select_one("p.list-number")
        if rank_tag:
            rank_text = rank_tag.get_text(strip=True)
        try:
            rank = int(rank_text) if rank_text else len(entries) + 1
        except ValueError:
            rank = len(entries) + 1

        entries.append(
            ShowdownEntry(
                rank=rank,
                film_name=name or slug,
                film_slug=slug or link.strip("/").split("/")[-1],
                film_year=year,
                film_url=film_url,
                details_endpoint=details_endpoint,
            )
        )

    return published_at, entries


def _extract_tmdb_id_from_film_page(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body")
    if body and body.has_attr("data-tmdb-id"):
        tmdb_value = body.get("data-tmdb-id")
        if isinstance(tmdb_value, str):
            tmdb_id = tmdb_value.strip()
            return tmdb_id or None
    return None


def _populate_descriptions(
    datasets: Sequence[ShowdownDataset],
    *,
    session: Session,
    timeout: int,
    progress: Callable[[str], None] | None = None,
) -> None:
    """Fetch and populate descriptions and background images for showdowns that
    don't have them."""
    for dataset in datasets:
        needs_description = not dataset.summary.description
        needs_background = not dataset.summary.background_image

        if not needs_description and not needs_background:
            continue  # Already has both

        try:
            showdown_html = fetch_html(
                dataset.summary.showdown_url, session=session, timeout=timeout
            )

            if needs_description:
                description = parse_showdown_description(showdown_html)
                dataset.summary.description = description
                if progress and description:
                    progress(f"  - Fetched description ({len(description)} chars)")

            if needs_background:
                background_image = parse_showdown_background_image(showdown_html)
                dataset.summary.background_image = background_image
                if progress and background_image:
                    progress("  - Fetched background image URL")

        except requests.RequestException as exc:
            if progress:
                progress(
                    f"  ! Failed to fetch showdown data from "
                    f"{dataset.summary.showdown_url}: {exc}"
                )


def _populate_tmdb_ids(
    datasets: Sequence[ShowdownDataset],
    *,
    session: Session,
    timeout: int,
    progress: Callable[[str], None] | None = None,
) -> None:
    film_map: dict[str, list[ShowdownEntry]] = {}
    for dataset in datasets:
        for entry in dataset.entries:
            if entry.tmdb_id:
                continue
            film_url = entry.ensure_film_url()
            if not film_url:
                continue
            film_map.setdefault(film_url, []).append(entry)

    for film_url, entries in film_map.items():
        try:
            film_html = fetch_html(film_url, session=session, timeout=timeout)
            tmdb_id = _extract_tmdb_id_from_film_page(film_html)
        except requests.RequestException as exc:  # pragma: no cover - network failure
            if progress:
                progress(f"  ! Failed to fetch TMDB id for {film_url}: {exc}")
            tmdb_id = None

        for entry in entries:
            entry.tmdb_id = tmdb_id


def collect_showdown_dataset(
    *,
    timeout: int = DEFAULT_TIMEOUT,
    limit: int | None = None,
    session: Session | None = None,
    use_cache: bool = True,
    existing_cache: Mapping[str, Mapping[str, object]] | None = None,
    force_refresh: bool = False,
    progress: Callable[[str], None] = print,
) -> list[ShowdownDataset]:
    ses = _ensure_session(session)

    def emit(message: str) -> None:
        if progress:
            progress(message)

    cache = existing_cache or {}

    emit(f"Fetching showdown index: {SHOWDOWN_ROOT}")
    index_html = fetch_html(SHOWDOWN_ROOT, session=ses, timeout=timeout)
    summaries = parse_showdown_index(index_html)

    if limit is not None:
        summaries = summaries[:limit]

    datasets: list[ShowdownDataset] = []
    total = len(summaries)

    for idx, summary in enumerate(summaries, start=1):
        status = (summary.status or "").strip().lower()
        emit(f"[{idx}/{total}] Processing showdown '{summary.title}' ({summary.slug})")

        if status == "in progress":
            emit("  - Showdown marked in progress; skipping entries scrape")
            dataset = ShowdownDataset(summary=summary, published_at=None, entries=[])
            datasets.append(dataset)
            continue

        dataset: ShowdownDataset | None = None
        cached_entry = None
        if use_cache and not force_refresh and summary.slug in cache:
            cached_entry = cache.get(summary.slug)
        if cached_entry:
            dataset = ShowdownDataset.from_dict(cached_entry)
            if dataset.entry_count and dataset.has_missing_tmdb_ids:
                _populate_tmdb_ids(
                    [dataset], session=ses, timeout=timeout, progress=progress
                )
            # Fetch description and background image if missing from cached entry
            if not dataset.summary.description or not dataset.summary.background_image:
                _populate_descriptions(
                    [dataset], session=ses, timeout=timeout, progress=progress
                )
            if dataset.entry_count:
                emit("  - Loaded from cache")

        if dataset is None:
            try:
                crew_html = fetch_html(
                    summary.crew_list_url, session=ses, timeout=timeout
                )
            except (
                requests.RequestException
            ) as exc:  # pragma: no cover - network failure
                emit(f"  ! Failed to fetch crew list: {exc}")
                dataset = ShowdownDataset(
                    summary=summary, published_at=None, entries=[]
                )
            else:
                published_at, entries = parse_showdown_crew_list(crew_html)
                dataset = ShowdownDataset(
                    summary=summary,
                    published_at=published_at,
                    entries=entries,
                )
                if dataset.entry_count:
                    _populate_tmdb_ids(
                        [dataset], session=ses, timeout=timeout, progress=progress
                    )
                    emit(f"  - Collected {dataset.entry_count} entries")
                else:
                    emit("  ! No entries parsed from crew list")

        # Fetch description and background image if we don't have them
        if dataset and (
            not dataset.summary.description or not dataset.summary.background_image
        ):
            _populate_descriptions(
                [dataset], session=ses, timeout=timeout, progress=progress
            )

        datasets.append(dataset)

    return datasets


def refresh_showdown_cache(
    cache_path: Path,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    limit: int | None = None,
    force_refresh: bool = False,
    progress: Callable[[str], None] = print,
) -> list[ShowdownDataset]:
    existing_cache = {} if force_refresh else load_showdown_cache(cache_path)
    datasets = collect_showdown_dataset(
        timeout=timeout,
        limit=limit,
        use_cache=not force_refresh,
        existing_cache=existing_cache,
        force_refresh=force_refresh,
        progress=progress,
    )

    updated_cache: dict[str, dict[str, object]] = {
        dataset.summary.slug: dataset.to_dict()
        for dataset in datasets
        if dataset.entry_count
    }

    # Retain cached entries we did not touch this run when not forcing refresh.
    if not force_refresh:
        for slug, payload in existing_cache.items():
            updated_cache.setdefault(slug, dict(payload))

    save_showdown_cache(cache_path, updated_cache)
    if progress:
        progress(f"Cached {len(updated_cache)} showdown datasets → {cache_path}")

    return datasets


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh the Letterboxd showdown cache"
    )
    parser.add_argument(
        "--cache",
        required=True,
        help="Path to showdown cache JSON file (e.g. showdown.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Fetch only the first N showdowns (useful while testing)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout for each request in seconds",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore existing cache and pull fresh data",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print collected datasets as JSON to stdout",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:  # pragma: no cover - CLI glue
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    cache_path = resolve_path(args.cache, Path.cwd())
    if cache_path is None:
        raise SystemExit("Unable to resolve cache path")

    datasets = refresh_showdown_cache(
        cache_path,
        timeout=args.timeout,
        limit=args.limit,
        force_refresh=args.refresh,
    )

    if args.json:
        payload = [dataset.to_dict() for dataset in datasets]
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
