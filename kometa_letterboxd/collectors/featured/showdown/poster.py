"""Poster rendering for latest Letterboxd Showdown collections."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import requests
from requests import Session

from kometa_letterboxd.common.config import ShowdownPosterConfig, resolve_path

from .probe import ShowdownDataset


@dataclass(frozen=True)
class GeneratedPoster:
    local_path: Path | None = None
    kometa_path: str | None = None
    background_local_path: Path | None = None
    background_kometa_path: str | None = None


def generate_showdown_poster(
    dataset: ShowdownDataset,
    poster_config: ShowdownPosterConfig,
    *,
    base_path: Path,
    session: Session,
    timeout: int,
    render_poster: bool = True,
    save_background: bool = True,
    progress: Callable[[str], None] | None = None,
) -> GeneratedPoster | None:
    """Generate a poster image and return its local and Kometa-visible paths."""

    if not render_poster and not save_background:
        return None

    background_url = (dataset.summary.background_image or "").strip()
    if not background_url:
        if progress:
            progress(
                f"  ! No Showdown image found for '{dataset.summary.title}'; "
                "skipping poster."
            )
        return None

    try:
        response = session.get(background_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        if progress:
            progress(
                f"  ! Failed to download Showdown image for "
                f"'{dataset.summary.title}': {exc}"
            )
        return None

    output_directory = resolve_path(poster_config.output_directory, base_path)
    if output_directory is None:
        return None

    output_directory.mkdir(parents=True, exist_ok=True)
    extension = poster_extension(poster_config)
    output_path = (
        output_directory / f"{poster_slug(dataset)}.{extension}"
        if render_poster
        else None
    )
    background_path = (
        output_directory
        / f"{poster_slug(dataset)}-background.{background_extension(background_url)}"
        if save_background
        else None
    )
    logo_path = (
        resolve_path(poster_config.logo_path, base_path)
        if poster_config.logo_path
        else None
    )

    if background_path is not None:
        background_path.write_bytes(response.content)
        if progress:
            progress(f"  - Saved background: {background_path}")

    if output_path is not None:
        try:
            render_showdown_poster(
                response.content,
                title=dataset.summary.title,
                logline=dataset.summary.logline,
                output_path=output_path,
                width=poster_config.width,
                height=poster_config.height,
                image_format=poster_config.image_format,
                quality=poster_config.quality,
                logo_path=logo_path,
                logo_label=poster_config.logo_label,
                progress=progress,
            )
        except OSError as exc:
            if progress:
                progress(
                    f"  ! Failed to render poster for "
                    f"'{dataset.summary.title}': {exc}"
                )
            output_path = None
        else:
            if progress:
                progress(f"  - Generated poster: {output_path}")

    if output_path is None and background_path is None:
        return None

    return GeneratedPoster(
        local_path=output_path,
        kometa_path=(
            build_kometa_poster_path(output_path, poster_config)
            if output_path is not None
            else None
        ),
        background_local_path=background_path,
        background_kometa_path=(
            build_kometa_poster_path(background_path, poster_config)
            if background_path is not None
            else None
        ),
    )


def poster_slug(dataset: ShowdownDataset) -> str:
    return _safe_slug(dataset.summary.slug or dataset.summary.title)


def poster_extension(poster_config: ShowdownPosterConfig) -> str:
    if poster_config.image_format == "png":
        return "png"
    return "jpg"


def background_extension(image_url: str) -> str:
    suffix = Path(urlparse(image_url).path).suffix.lower().lstrip(".")
    if suffix in {"jpg", "jpeg", "png", "webp"}:
        return "jpg" if suffix == "jpeg" else suffix
    return "jpg"


def build_kometa_poster_path(
    local_path: Path,
    poster_config: ShowdownPosterConfig,
) -> str:
    if poster_config.kometa_path:
        return str(PurePosixPath(poster_config.kometa_path) / local_path.name)
    return str(local_path)


def render_showdown_poster(
    background_bytes: bytes,
    *,
    title: str,
    logline: str | None,
    output_path: Path,
    width: int,
    height: int,
    image_format: str,
    quality: int,
    logo_path: Path | None = None,
    logo_label: str | None = "SHOWDOWN",
    progress: Callable[[str], None] | None = None,
) -> None:
    Image, ImageDraw, ImageFilter, ImageFont, ImageOps = _load_pillow()

    with Image.open(BytesIO(background_bytes)) as source_image:
        canvas = _compose_background(
            Image,
            ImageFilter,
            ImageOps,
            source_image,
            width=width,
            height=height,
        )
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    _draw_vertical_gradient(
        overlay_draw,
        width=width,
        height=int(height * 0.54),
        start_alpha=248,
        end_alpha=18,
    )
    _draw_bottom_gradient(
        overlay_draw,
        width=width,
        height=height,
        gradient_height=int(height * 0.2),
        start_alpha=0,
        end_alpha=125,
    )
    canvas = Image.alpha_composite(canvas, overlay)

    draw = ImageDraw.Draw(canvas)
    margin = max(36, int(width * 0.075))
    top = max(36, int(height * 0.055))

    logo = _load_logo(
        Image,
        logo_path,
        max_width=int(width * 0.46),
        max_height=int(height * 0.07),
        progress=progress,
    )
    if logo is not None:
        masthead_bottom = _draw_logo_masthead(
            canvas,
            draw,
            ImageFont,
            logo=logo,
            label=logo_label,
            x=margin,
            y=top,
            width=width,
        )
        text_top = masthead_bottom + int(height * 0.045)
    else:
        _draw_text_masthead(
            draw,
            ImageFont,
            x=margin,
            y=top,
            width=width,
        )
        text_top = top + int(height * 0.095)

    title_font, title_lines = _fit_wrapped_text(
        draw,
        ImageFont,
        title,
        max_width=width - (margin * 2),
        start_size=max(42, int(width * 0.088)),
        min_size=max(30, int(width * 0.052)),
        max_lines=4,
        bold=True,
    )
    title_bottom = _draw_lines(
        draw,
        title_lines,
        font=title_font,
        x=margin,
        y=text_top,
        line_gap=max(8, int(height * 0.009)),
        fill=(255, 255, 255, 255),
    )

    if logline:
        logline_font, logline_lines = _fit_wrapped_text(
            draw,
            ImageFont,
            logline,
            max_width=width - (margin * 2),
            start_size=max(24, int(width * 0.039)),
            min_size=max(18, int(width * 0.028)),
            max_lines=3,
            bold=False,
        )
        _draw_lines(
            draw,
            logline_lines,
            font=logline_font,
            x=margin,
            y=title_bottom + max(18, int(height * 0.018)),
            line_gap=max(7, int(height * 0.008)),
            fill=(222, 229, 235, 235),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if image_format == "png":
        canvas.save(output_path, format="PNG", optimize=True)
    else:
        canvas.convert("RGB").save(
            output_path,
            format="JPEG",
            quality=quality,
            optimize=True,
        )


def _load_pillow() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "showdown_latest.poster requires Pillow. Install it in the venv with "
            '.venv/bin/python -m pip install -e ".[posters]"'
        ) from exc
    return Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def _compose_background(
    image_module: Any,
    image_filter_module: Any,
    image_ops_module: Any,
    source_image: Any,
    *,
    width: int,
    height: int,
) -> Any:
    source = source_image.convert("RGB")
    base = image_ops_module.fit(
        source,
        (width, height),
        method=image_module.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    ).filter(
        image_filter_module.GaussianBlur(radius=max(12, int(width * 0.026)))
    )
    canvas = base.convert("RGBA")
    canvas = image_module.alpha_composite(
        canvas,
        image_module.new("RGBA", (width, height), (13, 17, 21, 150)),
    )

    hero = _resize_source_still(image_module, source, width=width, height=height)
    hero_y = min(
        height - hero.height,
        max(int(height * 0.4), int(height * 0.5) - (hero.height // 2)),
    )
    hero_y = max(0, hero_y)
    hero_x = (width - hero.width) // 2
    hero_mask = _build_still_fade_mask(image_module, hero.width, hero.height)
    canvas.paste(hero, (hero_x, hero_y), hero_mask)
    return canvas


def _resize_source_still(
    image_module: Any,
    source: Any,
    *,
    width: int,
    height: int,
) -> Any:
    target_width = width
    target_height = max(1, round(source.height * (target_width / source.width)))
    max_height = int(height * 0.6)
    if target_height > max_height:
        target_height = max_height
        target_width = max(1, round(source.width * (target_height / source.height)))

    return source.resize(
        (target_width, target_height),
        image_module.Resampling.LANCZOS,
    ).convert("RGBA")


def _build_still_fade_mask(image_module: Any, width: int, height: int) -> Any:
    mask = image_module.new("L", (width, height), 255)
    top_fade = max(1, int(height * 0.22))
    bottom_fade = max(1, int(height * 0.38))

    for y in range(top_fade):
        alpha = int(255 * (y / top_fade))
        _draw_mask_line(mask, y, width, alpha)

    for offset, y in enumerate(range(height - bottom_fade, height)):
        progress = offset / max(1, bottom_fade - 1)
        alpha = int(255 * (1 - progress))
        _draw_mask_line(mask, y, width, alpha)

    return mask


def _draw_mask_line(mask: Any, y: int, width: int, alpha: int) -> None:
    mask.paste(alpha, (0, y, width, y + 1))


def _draw_vertical_gradient(
    draw: Any,
    *,
    width: int,
    height: int,
    start_alpha: int,
    end_alpha: int,
) -> None:
    for y in range(height):
        progress = y / max(1, height - 1)
        alpha = int(start_alpha + (end_alpha - start_alpha) * (progress**1.7))
        draw.line([(0, y), (width, y)], fill=(20, 24, 28, alpha))


def _draw_bottom_gradient(
    draw: Any,
    *,
    width: int,
    height: int,
    gradient_height: int,
    start_alpha: int,
    end_alpha: int,
) -> None:
    top = max(0, height - gradient_height)
    for y in range(top, height):
        progress = (y - top) / max(1, gradient_height - 1)
        alpha = int(start_alpha + (end_alpha - start_alpha) * progress)
        draw.line([(0, y), (width, y)], fill=(20, 24, 28, alpha))


def _draw_logo_masthead(
    canvas: Any,
    draw: Any,
    image_font_module: Any,
    *,
    logo: Any,
    label: str | None,
    x: int,
    y: int,
    width: int,
) -> int:
    canvas.alpha_composite(logo, (x, y))
    bottom = y + logo.height
    normalized_label = " ".join((label or "").split())
    if not normalized_label:
        return bottom

    font = _font(image_font_module, max(18, int(width * 0.03)), bold=True)
    label_bbox = draw.textbbox((0, 0), normalized_label, font=font)
    label_width = label_bbox[2] - label_bbox[0]
    label_height = label_bbox[3] - label_bbox[1]
    gap = max(18, int(width * 0.026))
    label_x = x + logo.width + gap
    label_y = y + max(0, (logo.height - label_height) // 2) - label_bbox[1]

    if label_x + label_width > width - x:
        label_x = x
        label_y = y + logo.height + max(12, int(width * 0.016)) - label_bbox[1]

    draw.text(
        (label_x, label_y),
        normalized_label,
        font=font,
        fill=(222, 229, 235, 235),
    )
    return max(bottom, label_y + label_bbox[3])


def _draw_text_masthead(
    draw: Any,
    image_font_module: Any,
    *,
    x: int,
    y: int,
    width: int,
) -> None:
    bar_width = max(8, int(width * 0.012))
    bar_height = max(42, int(width * 0.058))
    gap = max(5, int(width * 0.007))
    colors = [(0, 224, 84), (255, 128, 0), (64, 188, 244)]
    for index, color in enumerate(colors):
        draw.rounded_rectangle(
            [
                x + index * (bar_width + gap),
                y,
                x + index * (bar_width + gap) + bar_width,
                y + bar_height,
            ],
            radius=max(2, bar_width // 3),
            fill=(*color, 255),
        )

    font = _font(image_font_module, max(18, int(width * 0.026)), bold=True)
    text_x = x + (len(colors) * (bar_width + gap)) + max(14, int(width * 0.018))
    draw.text(
        (text_x, y + max(5, int(width * 0.007))),
        "LETTERBOXD SHOWDOWN",
        font=font,
        fill=(222, 229, 235, 235),
    )


def _load_logo(
    image_module: Any,
    logo_path: Path | None,
    *,
    max_width: int,
    max_height: int,
    progress: Callable[[str], None] | None,
) -> Any | None:
    if logo_path is None:
        return None

    try:
        with image_module.open(logo_path) as logo:
            image = logo.convert("RGBA")
    except OSError as exc:
        if progress:
            progress(f"  ! Failed to load logo at {logo_path}: {exc}")
        return None

    scale = min(max_width / image.width, max_height / image.height, 1)
    target_size = (
        max(1, int(image.width * scale)),
        max(1, int(image.height * scale)),
    )
    return image.resize(target_size, image_module.Resampling.LANCZOS)


def _fit_wrapped_text(
    draw: Any,
    image_font_module: Any,
    text: str,
    *,
    max_width: int,
    start_size: int,
    min_size: int,
    max_lines: int,
    bold: bool,
) -> tuple[Any, list[str]]:
    normalized = " ".join(text.split())
    best_font = _font(image_font_module, min_size, bold=bold)
    best_lines = _wrap_text(draw, normalized, best_font, max_width)

    for size in range(start_size, min_size - 1, -2):
        font = _font(image_font_module, size, bold=bold)
        lines = _wrap_text(draw, normalized, font, max_width)
        if len(lines) <= max_lines:
            return font, lines

    return best_font, best_lines[:max_lines]


def _wrap_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""

    for word in text.split():
        candidates = _split_word_to_width(draw, word, font, max_width)
        for candidate in candidates:
            test_line = f"{current} {candidate}".strip()
            if not current or _text_width(draw, test_line, font) <= max_width:
                current = test_line
            else:
                lines.append(current)
                current = candidate

    if current:
        lines.append(current)
    return lines or [text]


def _split_word_to_width(
    draw: Any,
    word: str,
    font: Any,
    max_width: int,
) -> list[str]:
    if _text_width(draw, word, font) <= max_width:
        return [word]

    chunks: list[str] = []
    current = ""
    for char in word:
        candidate = f"{current}{char}"
        if current and _text_width(draw, candidate, font) > max_width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _draw_lines(
    draw: Any,
    lines: list[str],
    *,
    font: Any,
    x: int,
    y: int,
    line_gap: int,
    fill: tuple[int, int, int, int],
) -> int:
    cursor_y = y
    line_height = _line_height(draw, font)
    for line in lines:
        draw.text((x, cursor_y), line, font=font, fill=fill)
        cursor_y += line_height + line_gap
    return cursor_y - line_gap


def _font(image_font_module: Any, size: int, *, bold: bool) -> Any:
    candidates = (
        [
            "DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        ]
        if bold
        else [
            "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
    )

    for candidate in candidates:
        try:
            return image_font_module.truetype(candidate, size=size)
        except OSError:
            continue

    try:
        return image_font_module.load_default(size=size)
    except TypeError:
        return image_font_module.load_default()


def _text_width(draw: Any, text: str, font: Any) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _line_height(draw: Any, font: Any) -> int:
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return bbox[3] - bbox[1]


def _safe_slug(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "showdown"
