# kometa-letterboxd

Generate Kometa collections from Letterboxd lists, Showdowns, and dated collections.

## Installation

Create a project-local virtual environment and install the package into it:

```bash
git clone https://github.com/brege/kometa-letterboxd
cd kometa-letterboxd
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

If you want generated Showdown posters, install the optional poster extra in the
same virtual environment:

```bash
python -m pip install -e ".[posters]"
```

## Usage

```bash
.venv/bin/kometa-letterboxd --config config.yml
```

See `config.example.yml` for configuration options.

Run tests from the same virtual environment:

```bash
.venv/bin/python -m unittest discover -s tests
```

## Background

Surfacing content in a mature Plex library that is neither chaotically random nor repetitively ordered (imdb rating, date released, top 250 X) is a great challenge.

This project interfaces Plex with Letterboxd through scripting *around* Kometa. This tool builds the Kometa config files to be batched with Kometa's normal job runs. The first two are rather simple, a monthly serial collection "group" and another to build a letterboxd-tagged collection. The third is more sophisticated, integrating [Letterboxd's Showdowns](https://letterboxd.com/showdown/) feature into a Plex library. I quite like this feature on Letterboxd. Seeing these lists without context is a cross-word-like game.

### List Builders

- [Dated](/lists/dated.py):monthly Letterboxd lists of the form "favorite movies - August, 2022". Replaces the "favorite movies" with "new title", and can be made into a wrapper to dynamically build a monthly collection. This is a basic list builder I've provided to help you scaffold your own. It's too specific and probably not mush use to others.

- [Tagged](/lists/tagged.py): if you tag collections with "plex" on Letterboxd, this builder will create Kometa collections from these collections. These are handpicked films that are easier to pick and tease out of Letterboxd than anywhere else, especially compared to Plex.

- [Random](/kometa_letterboxd/collectors/user/random.py): builds a stable random subset from a large Letterboxd list. The subset rotates by schedule, currently monthly, but repeated runs in the same month produce the same movies.

- [Latest Showdowns](/kometa_letterboxd/collectors/featured/showdown/latest.py): builds Radarr-backed collections from the latest completed Letterboxd Showdowns, using only the top ranked movies from each Showdown.

- [Showdown](/lists/showdown.py): this is a sophisticated method. [Letterboxd Showdowns](https://letterboxd.com/showdown/) is a page of over 250 lists, each of which are constructed by a [motif](https://en.wikipedia.org/wiki/Motif_(narrative)) such as "Brief Encounter" or "Sense and Sensibility" that don't narrowly fit into a genre (War) or theme (political and human rights).

Importing a whole Showdown page, which Kometa can do, is problematic. These pages contain a lot of movies from users that definitely do not fit the motif. Letterboxd staff cuts the aggregate list down to the 20 best represented movies for that motif.

### Random Collections

Random collections are useful when a Letterboxd list is too large to import as a single Plex collection. Configure a source list, a target count, a seed namespace, and a monthly period:

```yaml
random:
  namespace_emoji: "🔀"
  collections:
    - name: "Random from TNMN"
      url: "https://letterboxd.com/tn_movienight/list/tuesday-night-movie-night-recommendations/"
      count: 10
      seed: "tnmn"
      period: "monthly"
      sync_mode: "sync"
      show_missing: true
      radarr_add_missing: true
      radarr_search: true
      radarr_folder: "/media/ephemeral-movies"
      radarr_tag:
        - "ephemeral"
        - "tnmn-random"
```

`namespace_emoji` is optional. When set, it is prepended to generated collection
names, for example `🔀 Random from TNMN`. You can also set `namespace_emoji` on
an individual random collection to override the workflow default. If the name
already starts with the same emoji, it is not duplicated.

The selector resolves movies from the complete source list, deduplicates them by stable identifier, and ranks them with a SHA-256 key derived from `<seed>-<YYYY-MM>` and the movie ID. For example, `tnmn-2026-06` produces the same ten movies for every run in June 2026, while `tnmn-2026-07` produces a different monthly subset. Reordering the source list does not change the selection when the underlying movie IDs are unchanged.

Random collections are emitted with direct `tmdb_movie` IDs when Letterboxd exposes the TMDb ID on each selected film page. The script fetches the complete list pages to build the pool, samples by stable Letterboxd movie identifiers, and then resolves TMDb IDs only for the selected subset. If `count` is larger than the source list size, the collection uses all resolved movies.

Random collections omit `collection_order` by default. Kometa allows `collection_order: custom` only with a single builder, and direct `tmdb_movie` entries can be treated as multiple builders when several IDs are provided. You can still set non-custom order values such as `release.desc`.

Random collections emit `show_missing: true` by default so Kometa logs which selected titles are not yet in Plex. Set `show_missing: false` on a collection if you want quieter logs.

When `radarr_add_missing: true` is set, Random collections also emit `radarr_search: true` by default so Radarr starts a search after Kometa adds missing movies. Set `radarr_search: false` if you only want Radarr to add and monitor them.

### Latest Showdowns

Latest Showdowns generates collections from the latest completed Letterboxd Showdowns and skips the current in-progress Showdown. With `count: 2`, the two latest completed Showdowns remain configured, which is roughly one month of retention at Letterboxd's usual two-week cadence.

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
  visible_library: true
  visible_home: true
  visible_shared: false
  poster:
    output_directory: "./assets/showdown-latest"
    kometa_path: "/config/assets/showdown-latest"
    logo_path: "./assets/letterboxd-logo.png"
    logo_label: "SHOWDOWN"
    background: true
```

Each collection uses the Showdown title plus logline, for example `🥊 Short 'n'
Sweet: Best adaptation of short to feature`, includes the Showdown description
as the Plex collection summary, and emits direct `tmdb_movie` IDs for the top
`entries` movies.

The optional `poster` block generates a poster image for each latest Showdown
collection and emits `file_poster` in the Kometa YAML. By default it also saves
the source Letterboxd still without darkening or resizing and emits
`file_background`. Set `background: false` if you only want posters.
`output_directory` is where this script writes the images. `kometa_path` is the
path Kometa should use to read the same directory, which is useful when Kometa
runs in Docker. If the script and Kometa see the same filesystem path, omit
`kometa_path`.

The repository includes a Letterboxd logo PNG at `assets/letterboxd-logo.png`.
The renderer appends `logo_label`, which defaults to `SHOWDOWN`, beside or
below that logo. If `logo_path` is omitted, the generated poster uses a text
masthead. Install poster support with
`.venv/bin/python -m pip install -e ".[posters]"`.

### Showdowns in Plex

![Letterboxd Showdowns in Plex](./showdowns.png)

The showdowns listed here are:
- **Intensive Care** - [letterboxd.com/showdown/intensive-care](https://letterboxd.com/showdown/intensive-care/)
- **A League of Their Own** - [letterboxd.com/showdown/a-league-of-their-own](https://letterboxd.com/showdown/a-league-of-their-own/)
- **Sense and Sensibility** - [letterboxd.com/showdown/sense-and-sensibility](https://letterboxd.com/showdown/sense-and-sensibility/)

### How Showdowns Work

A moderate sized Plex collection (500-1000 titles) will have ~50 possible showdown collections with 6 movies or more. If you tell this script to build every candidate Showdown collection, it will spam your Movies library with too many small collections.

This is restrained by:

- setting a minimum number of overlapping movies in your plex library (>=6 movies in both Plex AND a Showdown list).
- setting a "window size" (5 movies) for your daily runner of this tool. How many showdown collections should be in your library at any given time?
- setting the spotlight (1 movie). This is the center highlight of your sliding window.

#### Illustration

```
  ===[--X--]====================
  ====[--X--]===================
  =====[--X--]==================

  window (5): [--X--]
  X: the visible one on home page
  -: discoverable in collections
  =: all other collections w/ threshold >= 6
```

You can of course set the window size to 1, `[X]`, if you only want the spotlight.

### Configuration

See `config.example.yml` for an example config file. You can either reference your Kometa config file in your `config.yml`, or input your Plex token directly.

The first run will take around 30 minutes. The subsequent runs will only update when new completed Showdowns appear on Letterboxd. A pre-cache may be made externally available with enough interest.

### License

[MIT](LICENSE)
