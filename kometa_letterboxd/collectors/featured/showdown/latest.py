"""Generate Kometa collections for the latest completed Letterboxd Showdowns."""

from __future__ import annotations

from collections.abc import Callable, Iterable, MutableMapping, Sequence
from pathlib import Path
from typing import Any

import requests
from requests import Session

from kometa_letterboxd.common.config import ShowdownLatestConfig, resolve_path
from kometa_letterboxd.common.kometa import build_collection_entry

from .probe import (
    DEFAULT_HEADERS,
    SHOWDOWN_ROOT,
    ShowdownDataset,
    ShowdownEntry,
    ShowdownSummary,
    _populate_tmdb_ids as populate_showdown_tmdb_ids,
    fetch_html,
    parse_showdown_background_image,
    parse_showdown_crew_list,
    parse_showdown_description,
    parse_showdown_index,
)
from .poster import generate_showdown_poster


def generate_latest_showdown_collections(
    showdown_config: ShowdownLatestConfig | None,
    *,
    base_path: Path,
    timeout: int = 30,
    session: Session | None = None,
    progress: Callable[[str], None] = print,
) -> tuple[dict[str, MutableMapping[str, Any]], Path | None]:
    if showdown_config is None:
        return {}, None

    owns_session = session is None
    ses = session or requests.Session()
    if owns_session:
        ses.headers.update(DEFAULT_HEADERS)

    try:
        progress("\nFetching latest completed Letterboxd Showdowns...")
        index_html = fetch_html(SHOWDOWN_ROOT, session=ses, timeout=timeout)
        summaries = parse_showdown_index(index_html)
        selected = select_latest_completed_showdowns(
            summaries,
            count=showdown_config.count,
        )

        if not selected:
            progress("Showdown latest: no completed Showdowns found.")
            return {}, resolve_path(showdown_config.kometa_destination, base_path)

        collections: dict[str, MutableMapping[str, Any]] = {}
        wants_generated_poster = not has_explicit_poster_setting(showdown_config)
        wants_generated_background = (
            showdown_config.poster is not None
            and showdown_config.poster.background
            and not has_explicit_background_setting(showdown_config)
        )
        generate_artwork = (
            showdown_config.poster is not None
            and (wants_generated_poster or wants_generated_background)
        )
        for index, summary in enumerate(selected, start=1):
            progress(f"- Processing completed Showdown '{summary.title}'")
            dataset = fetch_latest_showdown_dataset(
                summary,
                entries=showdown_config.entries,
                timeout=timeout,
                session=ses,
                progress=progress,
            )
            collection_name = format_showdown_collection_name(dataset.summary)
            collection_order = resolve_collection_order(
                showdown_config.collection_order,
                builder_item_count=len(_tmdb_ids(dataset.entries)),
                collection_name=collection_name,
                progress=progress,
            )
            file_poster = None
            file_background = None
            if generate_artwork and showdown_config.poster is not None:
                generated_poster = generate_showdown_poster(
                    dataset,
                    showdown_config.poster,
                    base_path=base_path,
                    session=ses,
                    timeout=timeout,
                    render_poster=wants_generated_poster,
                    save_background=wants_generated_background,
                    progress=progress,
                )
                if generated_poster is not None:
                    if wants_generated_poster:
                        file_poster = generated_poster.kometa_path
                    if wants_generated_background:
                        file_background = generated_poster.background_kometa_path
            collections[collection_name] = build_latest_showdown_collection(
                dataset,
                showdown_config,
                collection_name=collection_name,
                index=index,
                collection_order=collection_order,
                file_poster=file_poster,
                file_background=file_background,
            )

        destination = resolve_path(showdown_config.kometa_destination, base_path)
        return collections, destination
    finally:
        if owns_session:
            ses.close()


def select_latest_completed_showdowns(
    summaries: Sequence[ShowdownSummary],
    *,
    count: int,
) -> list[ShowdownSummary]:
    completed = [summary for summary in summaries if is_completed_showdown(summary)]
    return completed[:count]


def is_completed_showdown(summary: ShowdownSummary) -> bool:
    return (summary.status or "").strip().lower() != "in progress"


def fetch_latest_showdown_dataset(
    summary: ShowdownSummary,
    *,
    entries: int,
    timeout: int,
    session: Session,
    progress: Callable[[str], None] | None = None,
) -> ShowdownDataset:
    description = None
    background_image = summary.background_image
    try:
        showdown_html = fetch_html(
            summary.showdown_url,
            session=session,
            timeout=timeout,
        )
        description = parse_showdown_description(showdown_html)
        background_image = (
            parse_showdown_background_image(showdown_html) or background_image
        )
    except requests.RequestException as exc:
        if progress:
            progress(
                f"  ! Failed to fetch Showdown description from "
                f"{summary.showdown_url}: {exc}"
            )

    published_at, parsed_entries = parse_showdown_crew_list(
        fetch_html(summary.crew_list_url, session=session, timeout=timeout)
    )
    top_entries = select_top_showdown_entries(parsed_entries, count=entries)

    dataset = ShowdownDataset(
        summary=ShowdownSummary(
            slug=summary.slug,
            title=summary.title,
            logline=summary.logline,
            status=summary.status,
            showdown_url=summary.showdown_url,
            crew_list_url=summary.crew_list_url,
            description=description,
            background_image=background_image,
        ),
        published_at=published_at,
        entries=top_entries,
    )
    populate_showdown_tmdb_ids(
        [dataset],
        session=session,
        timeout=timeout,
        progress=progress,
    )
    return dataset


def select_top_showdown_entries(
    entries: Sequence[ShowdownEntry],
    *,
    count: int,
) -> list[ShowdownEntry]:
    return sorted(entries, key=lambda entry: entry.rank)[:count]


def format_showdown_collection_name(summary: ShowdownSummary) -> str:
    title = " ".join((summary.title or summary.slug).split())
    logline = " ".join((summary.logline or "").split())
    if title and logline:
        return f"{title}: {logline}"
    return title or summary.slug


def build_latest_showdown_collection(
    dataset: ShowdownDataset,
    showdown_config: ShowdownLatestConfig,
    *,
    collection_name: str,
    index: int,
    collection_order: str | None,
    file_poster: str | None = None,
    file_background: str | None = None,
) -> MutableMapping[str, Any]:
    collection = build_collection_entry(
        dataset.summary.showdown_url,
        sort_title=f"Showdown Latest {index:02d} {collection_name}",
        sync_mode=showdown_config.sync_mode,
        collection_order=collection_order,
        summary=build_showdown_collection_summary(dataset),
        extra=showdown_config.kometa_extra(),
        tmdb_ids=_tmdb_ids(dataset.entries),
    )
    if (
        file_poster
        and "file_poster" not in collection
        and "url_poster" not in collection
    ):
        collection["file_poster"] = file_poster
    if (
        file_background
        and "file_background" not in collection
        and "url_background" not in collection
    ):
        collection["file_background"] = file_background
    return collection


def build_showdown_collection_summary(dataset: ShowdownDataset) -> str:
    description = (dataset.summary.description or "").strip()
    if not description:
        description = (
            "Top most mentioned films from this Letterboxd Showdown."
        )

    showdown_url = dataset.summary.showdown_url.strip()
    if showdown_url:
        return f"{description}\n\n{showdown_url}"
    return description


def resolve_collection_order(
    collection_order: str | None,
    *,
    builder_item_count: int,
    collection_name: str,
    progress: Callable[[str], None] | None = None,
) -> str | None:
    if collection_order != "custom":
        return collection_order

    if builder_item_count <= 1:
        return collection_order

    if progress:
        progress(
            f"- Omitting collection_order: custom for '{collection_name}' because "
            "Kometa treats multiple direct TMDb movie IDs as multiple builders."
        )
    return None


def has_explicit_poster_setting(showdown_config: ShowdownLatestConfig) -> bool:
    extra = showdown_config.kometa_extra()
    return any(key in extra for key in ("file_poster", "url_poster"))


def has_explicit_background_setting(showdown_config: ShowdownLatestConfig) -> bool:
    extra = showdown_config.kometa_extra()
    return any(key in extra for key in ("file_background", "url_background"))


def _tmdb_ids(entries: Iterable[ShowdownEntry]) -> list[str]:
    return [
        str(entry.tmdb_id)
        for entry in entries
        if entry.tmdb_id is not None and str(entry.tmdb_id).strip()
    ]
