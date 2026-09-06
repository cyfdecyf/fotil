# Fotil

## Features

- Auto import from specified source directory to destination
  - Dedup when importing files
- Geotag for photos and videos
  - Add GPS info from GPS log
  - Copy time and GPS from other files, or from a Sony sidecar XML
  - Time and GPS tags works with iOS and macOS Photos.app
- Local web UI to review pictures and clean up raw files

## Dev install

Run the following command:

```bash
uv sync
```

## Library config

Libraries are configured in `~/.config/fotil/fotil.toml` (override with the
global `--config` option). A library points at the processed pictures, the
raw files and the trash directory:

```toml
default_library = 'main'

[library.main]
pic_dir = '/path/to/pic'     # processed pictures (jpg/heif/...)
raw_dir = '/path/to/raw'     # raw files, mirroring pic_dir layout
trash_dir = '/path/to/trash' # cleanup destination, nothing is ever deleted
```

Files map between `pic_dir` and `raw_dir` by matching file stem, so
`2024/05-01/DSC08924.JPG` corresponds to `2024/05-01/DSC08924.ARW`.

## Review pictures in the web UI

`fotil web` starts a local web UI (default `http://127.0.0.1:8000`) for the
quick cull after importing:

```bash
fotil web                # fotil web --host 0.0.0.0 --port 8000 to expose it
```

Browse the `pic_dir` directory tree and cull pictures entirely from the
keyboard:

| Keys | Action |
|---|---|
| `←→↑↓` | move the cursor in the grid; in the viewer `←→` switch pictures |
| `Space` / `Enter` | enlarge the picture under the cursor; press again to return |
| `d` / `u` | mark for deletion / undo (acts on the cursor, or the viewer picture) |
| `Home` / `End`, `PgUp` / `PgDn` | jump to first/last, one screen at a time |
| `f` | toggle fit-window ↔ 1:1 pixels in the viewer (or click the picture) |
| `a` | select/clear all loaded pictures |
| `s` | toggle select mode (click = mark instead of enlarge) |
| `?` | cheat sheet |

Marked pictures are outlined in red. Hit **cleanup raw**: the marked
pictures and their same-stem raw files are moved into `trash_dir`, mirroring
the original layout. Nothing is deleted — restore by moving files back by
hand.

HEIF/HIF pictures (Sony camera format) are transcoded to cached JPEG
previews under `~/.cache/fotil/web` for display; originals stay untouched.
On macOS the `sips` backend (ImageIO, hardware HEVC decode) is used when
available, with Pillow as the per-file fallback; set `FOTIL_TRANSCODER`
to `sips` or `pillow` to force a backend. The optional config section

```toml
[web]
sips_size_check = true # default false: always shrink to the preview cap
```

makes sips check image sizes first and leave pictures already within the
2560px preview cap untouched, matching Pillow's never-upscale behavior.
The UI follows the system light/dark theme; the 自动/浅色/深色 control in
the toolbar overrides it (stored in the browser).

## Restore date and GPS on an exported video

After editing a video and exporting the final cut, the exported file has lost the
original camera metadata. Restore it from an original camera clip with one
command:

```bash
fotil geotag copy-time C0123.MP4 final.mov
```

This copies the time tags and camera make/model, stored the way iPhone videos
store them (naive UTC QuickTime times plus `Keys:Make` / `Keys:Model`). When the
source clip ships its Sony `NonRealTimeMeta` sidecar (`C0123.XML`) and the
sidecar carries a GPS fix, the coordinates and the timezone-aware creation date
are copied as well (`Keys:GPSCoordinates`, `Keys:CreationDate`), so macOS
Photos.app treats the final video like an iPhone video — no second step needed.
The sidecar must sit next to the source clip with the same basename, otherwise
its GPS data is lost (see [docs/samples/README.md](docs/samples/README.md)).

If the sidecar has no GPS fix, only the time tags are written; add GPS from a
photo or video taken at a nearby location instead:

```bash
fotil geotag copy-gps nearby.jpg final.mov
```

For videos recorded with the camera clock left in the home timezone, add
`--time-shift` to fix the copied wall time (see `fotil geotag copy-time --help`).

## About date / GPS related tags

See [docs/samples/README.md](docs/samples/README.md) for a detailed description of the
date-time and GPS metadata written by the iPhone 16 and Sony A7M4 sample files, and the
sample `.exif` dumps themselves.
