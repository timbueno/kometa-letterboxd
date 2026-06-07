# Latest Letterboxd Showdowns Workflow Specification

## Goal

Add a new optional workflow that generates Kometa collections from the latest
completed Letterboxd Showdowns.

This workflow is intended for short-lived, Radarr-backed collections:

- keep the latest completed Showdowns visible for roughly one month
- include only the top ranked "Most Mentioned" movies from each Showdown
- add missing movies through Kometa's existing Radarr integration
- avoid requiring users to manage a large historical Showdown cache

This workflow must be additive. Existing Dated, Tagged, Random, and current
Showdown behavior must remain unchanged.

## Proposed Configuration

```yaml
showdown_latest:
  count: 2
  entries: 5
  sync_mode: sync
  show_missing: true
  radarr_add_missing: true
  radarr_search: true
  radarr_folder: "/mnt/ephemeral-movies"
  radarr_tag:
    - ephemeral
    - showdown
  visible_library: true
  visible_home: true
  visible_shared: false
  kometa_destination: /path/to/showdown-latest.yml
```

## Configuration Fields

`count`
: Number of latest completed Showdowns to keep. Default should be `2`.

`entries`
: Number of top movies to include from each Showdown's "Most Mentioned" list.
  Default should be `5`.

`sync_mode`
: Kometa sync mode passed to generated collections. Default should be `sync`.

`show_missing`
: Kometa missing-item reporting. Default should be `true`.

`radarr_add_missing`
: Passed through to Kometa. Default can be unset or `false`, but examples should
  use `true`.

`radarr_search`
: Passed through to Kometa. If `radarr_add_missing: true` and this is unset,
  default to `true`.

`radarr_folder`
: Passed through to Kometa/Radarr.

`radarr_tag`
: Passed through to Kometa/Radarr.

`kometa_destination`
: Optional generated YAML destination. If omitted, the workflow writes into the
  default destination used by the other generated collections.

Extra Kometa collection fields should pass through unchanged. This includes,
but is not limited to:

```yaml
collection_order: release.desc
visible_library: true
visible_home: true
visible_shared: false
url_poster: "https://example.com/showdown-poster.jpg"
file_poster: "/config/assets/showdowns/poster.png"
label: "Letterboxd Showdown"
```

## Selection Behavior

1. Fetch the Letterboxd Showdowns index.
2. Skip any Showdown whose status is `In Progress`.
3. Select the latest `count` completed Showdowns from the index order.
4. For each selected Showdown:
   - fetch the Showdown page
   - parse the official description
   - fetch the crew/staff list used for "Most Mentioned"
   - take the top `entries` movies
   - resolve those movies to TMDb IDs
   - generate one Kometa collection

The current in-progress Showdown must not produce a collection.

## Collection Naming

Use the Showdown title plus its index logline/subheadline.

Example:

```text
Short 'n' Sweet: Best adaptation of short to feature
```

Do not prefix the display name with `Showdown:` unless the source title/logline
is unavailable.

If the logline is missing, use only the Showdown title.

## Collection Description

Generated collections should include a Kometa `summary`.

The summary should contain:

- the official Letterboxd Showdown description, when available
- the source Letterboxd Showdown URL

Example:

```yaml
summary: |-
  Official Letterboxd Showdown description.

  https://letterboxd.com/showdown/short-n-sweet/
```

If the official description is unavailable, fall back to a short generated
summary plus the source URL.

## Generated YAML Shape

Use direct `tmdb_movie` IDs.

Example:

```yaml
collections:
  "Short 'n' Sweet: Best adaptation of short to feature":
    sort_title: "Showdown 2026-06 Short 'n' Sweet"
    sync_mode: sync
    show_missing: true
    tmdb_movie:
      - "123"
      - "456"
      - "789"
      - "101"
      - "112"
    summary: |-
      Official Letterboxd Showdown description.

      https://letterboxd.com/showdown/short-n-sweet/
    radarr_add_missing: true
    radarr_search: true
    radarr_folder: /mnt/ephemeral-movies
    radarr_tag:
      - ephemeral
      - showdown
    visible_library: true
    visible_home: true
    visible_shared: false
```

Do not emit `collection_order: custom` by default. Direct `tmdb_movie` entries
can conflict with Kometa's custom-order builder rules when multiple IDs are
present. If `collection_order: custom` is explicitly configured with multiple
TMDb IDs, omit it and print a warning.

## Retention Model

The workflow should retain the latest `count` completed Showdowns.

With `count: 2` and Letterboxd's approximate two-week publishing cadence, each
Showdown collection should remain configured for about one month.

This is intentionally count-based rather than date-based:

```text
June 1   Showdown A completes      Keep: A
June 15  Showdown B completes      Keep: B, A
June 29  Showdown C completes      Keep: C, B   A drops
July 13  Showdown D completes      Keep: D, C   B drops
```

Deleting dropped collections from Plex should be handled by Kometa's library
operations, for example `delete_collections` with `configured: false` and
`managed: true`, if the user chooses that behavior.

## Caching

Users should not need to configure or manually maintain a large Showdown JSON
cache for this workflow.

Implementation may keep a small internal cache under the data directory to avoid
unnecessary network requests, but cache management should remain an
implementation detail.

The workflow should work without a pre-existing `showdown_json` file.

## Reuse Existing Code

Reuse existing Showdown scraper pieces where practical:

- `parse_showdown_index`
- `parse_showdown_description`
- `parse_showdown_crew_list`
- TMDb ID extraction/resolution helpers
- `build_collection_entry`

The existing historical/sliding-window Showdown workflow should remain
unchanged.

## Testing Requirements

Add tests covering:

1. In-progress Showdowns are skipped.
2. Only the latest `count` completed Showdowns are selected.
3. Only the top `entries` movies are emitted per Showdown.
4. Collection names combine title and logline.
5. Official description is included in `summary`.
6. Extra Kometa fields pass through, including visibility settings.
7. `radarr_search` defaults to `true` when `radarr_add_missing: true`.
8. Existing Showdown config and behavior remain backward compatible.

Network access should be mocked in unit tests.

## Non-Goals

- Do not create Plex placeholder items for missing movies.
- Do not require modifications to Kometa.
- Do not replace the existing Showdown workflow.
- Do not require a user-managed historical `showdown_json` cache.
- Do not implement ownership threshold filtering for this workflow.
- Do not implement sliding-window spotlight state for this workflow.
