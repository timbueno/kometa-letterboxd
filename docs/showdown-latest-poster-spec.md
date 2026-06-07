# Latest Showdown Poster Generation Specification

## Goal

Add optional generated poster artwork for the `showdown_latest` workflow.

The poster should use the Letterboxd Showdown source image when available and
compose it with a clear Showdown masthead plus the Showdown title/logline.

This feature must be additive:

- existing `showdown_latest` YAML output remains unchanged unless poster config
  is present
- Dated, Tagged, Random, and historical Showdown behavior remain unchanged
- user-provided Kometa poster fields such as `file_poster` and `url_poster`
  remain valid
- Kometa itself does not need modification

## Proposed Configuration

```yaml
showdown_latest:
  count: 2
  entries: 5
  poster:
    output_directory: "./assets/showdown-latest"
    kometa_path: "/config/assets/showdown-latest"
    logo_path: "./assets/letterboxd-logo.png"
    logo_label: "SHOWDOWN"
    background: true
    width: 1000
    height: 1500
    format: jpg
```

## Configuration Fields

`poster`
: Optional nested config. If omitted, no posters are generated.

`poster.output_directory`
: Local directory where this script writes generated poster files. Relative
  paths resolve relative to the config file.

`poster.kometa_path`
: Optional directory path emitted in generated YAML. Use this when Kometa runs
  in a container or environment where the poster directory is mounted at a
  different path. If omitted, the generated YAML uses the local poster path.

`poster.logo_path`
: Optional local raster image file for a Letterboxd logo or custom masthead.
  The repository includes a PNG at `assets/letterboxd-logo.png`. If omitted or
  unreadable, the poster uses a text masthead.

`poster.logo_label`
: Optional text label drawn beside or below the logo. Default: `SHOWDOWN`. Set
  to an empty string to show only the provided logo.

`poster.background`
: Whether to save and emit a Kometa collection background from the source
  Letterboxd still. Default: `true`.

`poster.width`
: Poster width in pixels. Default: `1000`.

`poster.height`
: Poster height in pixels. Default: `1500`.

`poster.format`
: Output format. Initially support `jpg` and `png`. Default: `jpg`.

## Rendering Behavior

For each selected completed Showdown:

1. Fetch the Showdown page.
2. Parse the official Showdown description.
3. Parse the Showdown background/source image URL.
4. Download the source image.
5. Compose a poster:
   - blurred, darkened full-poster background derived from the source image
   - sharp source still scaled to fit the poster width without changing aspect
     ratio
   - dark gradient at the top for title readability
   - optional logo image plus `logo_label`, or text masthead
   - Showdown title as primary text
   - Showdown logline as secondary text
   - top and bottom fades around the sharp still
   - subtle Letterboxd color bars for identity when no logo is supplied
6. Write the poster to `poster.output_directory`.
7. If `poster.background` is enabled, write the source Letterboxd still to
   `poster.output_directory` without darkening, cropping, resizing, or
   recompression.
8. Emit `file_poster` and, when available, `file_background` in the generated
   Kometa collection YAML.

If the Showdown image cannot be found or downloaded, the collection should still
be generated without `file_poster`. A poster failure should not prevent the
Radarr-backed collection from being produced unless the failure is a local setup
problem such as Pillow not being installed while poster config is enabled.

## Generated YAML

Example:

```yaml
collections:
  "Short 'n' Sweet: Best adaptation of short to feature":
    sort_title: "Showdown Latest 01 Short 'n' Sweet: Best adaptation of short to feature"
    sync_mode: sync
    tmdb_movie:
      - "244786"
      - "4995"
      - "869626"
      - "764"
      - "500"
    summary: |-
      Official Letterboxd Showdown description.

      https://letterboxd.com/showdown/short-n-sweet/
    file_poster: /config/assets/showdown-latest/short-n-sweet.jpg
    file_background: /config/assets/showdown-latest/short-n-sweet-background.jpg
    radarr_add_missing: true
    radarr_search: true
```

If the user explicitly configures `file_poster` or `url_poster` as pass-through
Kometa YAML, that explicit setting should take precedence over generated poster
paths. If the user explicitly configures `file_background` or `url_background`,
that explicit setting should take precedence over generated background paths.

## Logo Handling

The repository includes `assets/letterboxd-logo.png` for the default
Letterboxd-branded masthead, but the script should not require that asset to
generate collections.

Users who want logo-based posters can provide a local raster asset:

```yaml
showdown_latest:
  poster:
    output_directory: "./assets/showdown-latest"
    logo_path: "./assets/letterboxd-logo.png"
    logo_label: "SHOWDOWN"
```

The logo is optional. Without it, the poster uses text branding. If the provided
logo already includes the word "Letterboxd", leave `logo_label` at `SHOWDOWN`
or set it to a different short label.

## Dependency

Poster rendering requires Pillow. Since poster generation is optional, Pillow
should be declared as an optional project extra.

Installation:

```bash
.venv/bin/python -m pip install -e ".[posters]"
```

## Testing Requirements

Add tests covering:

1. Poster config loads without changing existing config behavior.
2. The latest Showdown scraper stores the parsed background image URL.
3. Generated collections include `file_poster` when a poster path is provided.
4. Explicit `file_poster` or `url_poster` pass-through fields are not replaced.
5. Poster filenames and Kometa paths are stable and slug-based.
6. Rendering writes an image at the requested dimensions when Pillow is
   available.

Network access should be mocked in unit tests.

## Non-Goals

- Do not implement Kometa overlays.
- Do not generate posters for Dated, Tagged, Random, or historical Showdown
  workflows in this change.
- Do not require SVG logo rendering support.
