# Setup and Operations Guide

This guide documents the workflow added around `kometa-letterboxd`: deterministic
Random collections, latest completed Letterboxd Showdowns, generated artwork,
namespace emoji prefixes, and scheduled execution.

## Repository Setup

Clone the fork or project repository on the machine that will generate Kometa
YAML:

```bash
git clone https://github.com/timbueno/kometa-letterboxd.git
cd kometa-letterboxd
git checkout codex/random-workflow
```

Create and install into a project-local virtual environment:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[posters]"
```

Use the `posters` extra if you want generated latest-Showdown posters and
backgrounds. Without it, the non-artwork workflows can still run.

## Configuration File

Copy the example and edit local paths:

```bash
cp config.example.yml config.yml
```

`config.yml` is ignored by git. Keep server-specific paths, Plex/Kometa paths,
and local Radarr settings there.

## Output File

Point one workflow at the generated Kometa YAML destination. Example:

```yaml
random:
  kometa_destination: "/path/to/kometa/config/letterboxd-generated.yml"
```

or:

```yaml
showdown_latest:
  kometa_destination: "/path/to/kometa/config/letterboxd-generated.yml"
```

Kometa should include or reference that generated file in its normal run. This
script does not modify Kometa itself.

## Random Collections

Random collections select a deterministic random subset from a large Letterboxd
list. The current supported period is monthly.

```yaml
random:
  namespace_emoji: "🔀"
  collections:
    - name: "Random from Ebert's Great Movies"
      url: "https://letterboxd.com/dave/list/official-top-250-narrative-feature-films/"
      count: 5
      seed: "ebert"
      period: "monthly"
      sync_mode: "sync"
      show_missing: true
      radarr_add_missing: true
      radarr_search: true
      radarr_folder: "/mnt/ephemeral-movies"
      radarr_tag:
        - ephemeral
        - ebert-random
```

Behavior:

- The same month produces the same movies every run.
- A new month rotates the selection.
- Source list order does not affect the result.
- The script fetches list pages to build the pool, then resolves TMDb IDs only
  for the selected subset.
- If `count` is larger than the list size, all resolved movies are used.

`namespace_emoji` is optional and prepends the emoji to generated collection
names. A collection-level `namespace_emoji` overrides the random workflow
default.

## Latest Showdowns

Latest Showdowns skips the current in-progress Showdown and keeps the latest
completed Showdowns.

```yaml
showdown_latest:
  namespace_emoji: "🥊"
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
  visible_library: false
  visible_home: true
  visible_shared: true
```

Behavior:

- `count: 2` keeps roughly one month of Showdowns when Letterboxd publishes
  about every two weeks.
- `entries: 5` includes the top five "Most Mentioned" movies.
- Collection names use the Showdown title plus logline, optionally prefixed by
  `namespace_emoji`.
- The collection summary includes the Letterboxd Showdown description and URL.

## Artwork

The repository includes:

```text
assets/letterboxd-logo.png
```

Enable latest-Showdown artwork like this:

```yaml
showdown_latest:
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

Generated YAML will include `file_poster` and, by default, `file_background`.

`output_directory` is where this script writes files. `kometa_path` is what
Kometa should use to read those same files. If the script and Kometa run in the
same filesystem context, omit `kometa_path`.

Backgrounds are saved from the Letterboxd still directly without darkening,
resizing, cropping, or recompression. Set `background: false` if you only want
collection posters.

Generated poster/background files under `assets/showdown-latest/` are ignored
by git.

## Radarr and Missing Movies

For missing movies, use:

```yaml
show_missing: true
radarr_add_missing: true
radarr_search: true
radarr_folder: "/mnt/ephemeral-movies"
```

Kometa cannot create placeholder movie items inside Plex collections when the
movie is not present in Plex. `show_missing` only reports missing titles.
`radarr_add_missing` and `radarr_search` tell Kometa to add/search through
Radarr. The movie appears in Plex collections after Radarr imports the file and
Plex scans it.

Make sure `radarr_folder` matches one of the root folders Radarr reports to
Kometa.

## Visibility

Pass through Kometa visibility fields where needed:

```yaml
visible_library: false
visible_home: true
visible_shared: true
```

`visible_home` controls whether the collection is promoted on managed users'
home screens. `visible_shared` controls shared users. `visible_library` controls
library recommended visibility.

## Removing Old Collections

When a generated collection name changes, the old Plex collection may remain.
The recommended cleanup is on the Kometa side with library operations for
unconfigured managed collections, for example using Kometa settings that delete
collections where `configured: false` and `managed: true`.

This script intentionally focuses on generating current YAML.

## Manual Run

From the project directory:

```bash
.venv/bin/kometa-letterboxd --config config.yml
```

Or use the wrapper:

```bash
./run-kometa-letterboxd.sh
tail -n 100 logs/kometa-letterboxd.log
```

The wrapper resolves its own directory, so it can be called from cron or another
working directory.

Useful environment overrides:

```bash
KOMETA_LETTERBOXD_CONFIG=/path/to/config.yml ./run-kometa-letterboxd.sh
KOMETA_LETTERBOXD_LOG_DIR=/var/log/kometa-letterboxd ./run-kometa-letterboxd.sh
KOMETA_LETTERBOXD_DATA=/path/to/data ./run-kometa-letterboxd.sh
```

## Scheduled Run

Edit cron:

```bash
crontab -e
```

Run daily at 11:30 PM server-local time:

```cron
30 23 * * * /root/kometa-letterboxd/run-kometa-letterboxd.sh
```

Schedule this before Kometa runs, so Kometa reads fresh generated YAML.

Check logs:

```bash
tail -n 100 /root/kometa-letterboxd/logs/kometa-letterboxd.log
```

The wrapper uses `flock` when available and a directory lock fallback otherwise,
so overlapping runs exit early.

## Updating an Existing Server

From the repo on the server:

```bash
git pull
. .venv/bin/activate
python -m pip install -e ".[posters]"
.venv/bin/python -m unittest discover -s tests
```

Then test the real config:

```bash
./run-kometa-letterboxd.sh
tail -n 100 logs/kometa-letterboxd.log
```

## Troubleshooting

`collection_order: custom can only be used with a single builder`
: Omit `collection_order: custom` for direct multi-TMDb generated collections.
  The Random and latest-Showdown workflows now omit incompatible custom ordering.

Collection is ignored by Kometa
: Usually all selected TMDb IDs are missing from Plex. Confirm Radarr settings,
  Radarr folder, and Plex scanning.

No poster generated
: Confirm `showdown_latest.poster` is configured, Pillow is installed with
  `python -m pip install -e ".[posters]"`, and the Showdown page exposes an
  image.

Kometa cannot read generated artwork
: Check that `output_directory` and `kometa_path` refer to the same mounted
  directory from the script's point of view and Kometa's point of view.

Cron runs at the wrong time
: Cron uses the server's local timezone unless configured otherwise.

Script runs manually but not in cron
: Use absolute paths in cron. The wrapper handles its own working directory,
  but cron still needs the absolute path to the wrapper script.
