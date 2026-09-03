# Fotil

## Features

- Auto import from specified source directory to destination
  - Dedup when importing files
- Geotag for photos and videos
  - Add GPS info from GPS log
  - Copy time and GPS from other files, or from a Sony sidecar XML
  - Time and GPS tags works with iOS and macOS Photos.app

## Dev install

Run the following command:

```bash
uv sync
```

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
