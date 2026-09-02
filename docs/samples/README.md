# Sample files & device metadata

I live in China (UTC+08:00). The sample files are intentionally selected from ones taken in Japan (UTC+09:00),
so that we can see how time zone is handled by the devices and by macOS *Photos.app*.

Metadata samples (`.exif` dumps extracted with `exiftool -s`):

| Sample | Media file | Device / format |
|---|---|---|
| [iPhone16-photo.exif](iPhone16-photo.exif) | [iPhone16-photo.heic](iPhone16-photo.heic) | iPhone 16, HEIC photo |
| [iPhone16-video.exif](iPhone16-video.exif) | [iPhone16-video.mov](iPhone16-video.mov) | iPhone 16, MOV video |
| [Sony-A7M4-photo.exif](Sony-A7M4-photo.exif) | not committed (too large) | Sony A7M4, ARW photo |
| [Sony-A7M4-video.exif](Sony-A7M4-video.exif) | not committed (too large) | Sony A7M4, MP4 (XAVC S) video |
| [Sony-A7M4-video.XML](Sony-A7M4-video.XML) | sidecar of the Sony MP4 (same basename) | Sony A7M4, XAVC S `NonRealTimeMeta` sidecar |

## Photos (HEIC / ARW): local time + separate offset tags

Raw tags stored in the file:

| Tag | iPhone 16 | Sony A7M4 | Behavior |
|---|---|---|---|
| `DateTimeOriginal` | `2025:08:30 16:03:06` | `2025:08:29 21:51:39` | Local wall-clock time, no tz |
| `CreateDate` | `2025:08:30 16:03:06` | `2025:08:29 21:51:39` | Local wall-clock time, no tz |
| `ModifyDate` | `2025:08:30 16:03:06` | `2025:08:29 21:51:39` | Local wall-clock time, no tz |
| `OffsetTime` / `OffsetTimeOriginal` / `OffsetTimeDigitized` | `+09:00` (all three) | `+09:00` (all three) | tz offset lives in its own tag |
| `SubSecTimeOriginal` / `SubSecTimeDigitized` | `701` / `701` | `302` / `302` | Sub-seconds, separate tags |
| `SubSecTime` | *(absent)* | `302` | Only Sony writes it (pairs with `ModifyDate`) |
| `GPSTimeStamp` / `GPSDateStamp` | `07:03:03.21` / `2025:08:30` | `12:51:39` / `2025:08:29` | UTC |

ExifTool *composite* tags (assembled from the raw tags above, not stored in the file):

| Composite tag | iPhone 16 | Sony A7M4 | Assembled from |
|---|---|---|---|
| `SubSecDateTimeOriginal` | `2025:08:30 16:03:06.701+09:00` | `2025:08:29 21:51:39.302+09:00` | `DateTimeOriginal` + `SubSecTimeOriginal` + `OffsetTimeOriginal` |
| `SubSecCreateDate` | `2025:08:30 16:03:06.701+09:00` | `2025:08:29 21:51:39.302+09:00` | `CreateDate` + `SubSecTimeDigitized` + `OffsetTimeDigitized` |
| `SubSecModifyDate` | `2025:08:30 16:03:06+09:00` *(no ms: `SubSecTime` absent)* | `2025:08:29 21:51:39.302+09:00` | `ModifyDate` + `SubSecTime` + `OffsetTime` |
| `GPSDateTime` | `2025:08:30 07:03:03.21Z` | `2025:08:29 12:51:39Z` | `GPSDateStamp` + `GPSTimeStamp`, always UTC |

Notes:

- iPhone and Sony photos behave the same. The only difference: Sony also writes `SubSecTime`, so its
  `SubSecModifyDate` carries milliseconds while the iPhone's does not.
- The iPhone's `GPSDateTime` (`07:03:03.21Z` = `16:03:03.21+09:00`) trails the shutter time
  (`16:03:06.701+09:00`) by ~3.5 s — it is the time of the GPS fix, not the shutter time.
  Sony's `GPSDateTime` matches the shutter time exactly (to the second).
- `FileModifyDate` / `FileAccessDate` / `FileInodeChangeDate` are filesystem timestamps, not embedded metadata.

## Videos (MOV / MP4): QuickTime times are UTC, plus one vendor-local tag

| Tag | iPhone 16 (MOV) | Sony A7M4 (MP4) | Behavior |
|---|---|---|---|
| `CreateDate` (MovieHeader) | `2025:08:28 13:26:39` | `2025:08:29 12:45:10` | **UTC**, no tz marker |
| `ModifyDate` (MovieHeader) | `2025:08:28 13:26:42` | `2025:08:29 12:45:10` | UTC; iPhone's is 3 s later (file finalize) |
| `TrackCreateDate` / `TrackModifyDate` / `MediaCreateDate` / `MediaModifyDate` | `13:26:39` / `13:26:42` / `13:26:39` / `13:26:42` | all `12:45:10` | UTC |
| `CreationDate` (Apple `com.apple.quicktime.creationdate`) | `2025:08:28 22:26:39+09:00` | *(absent)* | Local time **with tz**; shown in *QuickTime.app* inspector |
| `CreationDateValue` (Sony `rtmd` metadata track) | *(absent)* | `2025:08:29 21:45:10+09:00` | Local time **with tz** |
| `TimeZone` (Sony `rtmd`) | *(absent)* | `+09:00` | Camera tz, separate tag |
| `LastUpdate` (Sony `rtmd`) | *(absent)* | `2025:08:29 21:45:28+09:00` | Recording stop (start + `Duration` 17.52 s) |

Notes:

- The vendor local-time tags are consistent with the UTC QuickTime times:
  `13:26:39Z` ↔ `22:26:39+09:00`, and `12:45:10Z` ↔ `21:45:10+09:00`.
- Prefer the vendor tag (`CreationDate` / `CreationDateValue`) when present; otherwise remember that
  QuickTime `CreateDate` is UTC and must be converted — never interpret it as local time.
- Sony's `CreationDateValue` / `LastUpdate` / `TimeZone` come from the `NonRealTimeMeta` XML, which Sony
  embeds in the MP4 `rtmd` track and also writes as an uppercase `.XML` sidecar with the clip's basename
  (see [Sony video sidecar XML](#sony-video-sidecar-xml-nonrealtimemeta) below).
- Neither device writes sub-second tags in videos.

In Photos.app, both videos and photos can be correctly sorted by time.

## About GPS related tags

| Tag | iPhone 16 photo (HEIC) | iPhone 16 video (MOV) | Sony A7M4 photo (ARW) | Sony A7M4 video (MP4) |
|---|---|---|---|---|
| Storage location | EXIF GPS IFD | QuickTime metadata (`GPSCoordinates`, Apple) | EXIF GPS IFD | sidecar `.XML` file — `NonRealTimeMeta/AcquisitionRecord/Group[@name='ExifGPS']`; the copy embedded in the MP4 `rtmd` track exposes only `VersionID` |
| `GPSLatitude` / `GPSLongitude` (+ `Ref`) | 34°25'47.55"N, 135°14'17.81"E | 34°42'12.24"N, 135°30'2.52"E | 34°42'19.88"N, 135°29'36.09"E | 34°42'19.831"N, 135°29'36.607"E (stored as `34;42;19.831` rational DMS) |
| `GPSAltitude` (+ `Ref`) | 3.9 m Above Sea Level | 8.581 m Below Sea Level | *(absent)* | — (2-D fix, no altitude) |
| `GPSTimeStamp` / `GPSDateStamp` (→ `GPSDateTime`) | `07:03:03.21Z` / `2025:08:30` | *(absent)* | `12:51:39Z` / `2025:08:29` | `12:45:06.000Z` / `2025:08:29` |
| `GPSSpeed` | 0 km/h | *(absent)* | *(absent)* | — |
| `GPSImgDirection` / `GPSDestBearing` | 237.52° True North | *(absent)* | *(absent)* | — |
| `GPSHPositioningError` | 41.8 m | *(absent)* | *(absent)* | — |
| `LocationAccuracyHorizontal` | *(absent)* | 12.9 m | *(absent)* | — |
| `GPSVersionID` / `GPSStatus` / `GPSMeasureMode` / `GPSMapDatum` / `GPSDifferential` | *(absent)* | *(absent)* | `2.3.0.0` / `Measurement Active` / `2-D` / `WGS-84` / `No Correction` | `2.2.0.0` / `A` / `2` / `WGS-84` / `0` |

Key differences:

- **Where it lives**: photos use the standard EXIF GPS IFD. iPhone videos embed GPS as a QuickTime
  `GPSCoordinates` metadata item instead. Sony videos put a full EXIF-style GPS group in the sidecar
  `.XML` file — from the MP4 itself, exiftool surfaces only the `VersionID`.
- **GPS time**: every file except the iPhone video carries a GPS UTC timestamp. The fix time is never
  the capture time: the iPhone photo's fix trails the shutter by ~3.5 s, the Sony video's fix
  (`12:45:06Z`) precedes the recording start (`12:45:10Z`) by ~4 s, and the Sony photo's matches the
  shutter exactly.
- **Accuracy**: iPhone reports it (`GPSHPositioningError` in photos, `LocationAccuracyHorizontal` in
  videos); Sony does not.
- **Motion sensors**: only the iPhone photo writes `GPSSpeed` / `GPSImgDirection` / `GPSDestBearing`.
- **Survey fields**: only the Sony photo writes `GPSVersionID` / `GPSStatus` / `GPSMeasureMode` /
  `GPSMapDatum` / `GPSDifferential`. Its `GPSMeasureMode` is `2-Dimensional Measurement`, consistent
  with the missing altitude.
- **Altitude caveat**: the iPhone video reports `8.581 m Below Sea Level` in Osaka (which is at sea
  level) — the sign/precision of video GPS altitude is unreliable.

## Sony video sidecar XML (`NonRealTimeMeta`)

Sony XAVC S clips ship with an uppercase `.XML` sidecar (same basename as the MP4) containing the
`NonRealTimeMeta` data; a copy is also embedded in the MP4 `rtmd` track, but exiftool surfaces only
part of it from there — in this sample the full GPS fix is only visible in the sidecar file.

| Content | Value in sample | Notes |
|---|---|---|
| Full `ExifGPS` group | `Latitude` `34;42;19.831` N, `Longitude` `135;29;36.607` E, `TimeStamp` `12:45:06.000`, `DateStamp` `2025:08:29`, `Status` `A`, `MeasureMode` `2`, `MapDatum` `WGS-84`, `Differential` `0`, `VersionID` `2.2.0.0` | EXIF-style rational DMS (`deg;min;sec`); 2-D fix → no altitude, no accuracy estimate |
| GPS fix vs recording | fix `12:45:06Z` vs `CreationDate` `21:45:10+09:00` (= `12:45:10Z`) | fix acquired ~4 s before recording start; coordinates match the ARW photo taken ~6 min later on the same evening to within ~15 m |
| Color metadata | `CaptureGammaEquation` `s-log3-cine`, `CaptureColorPrimaries` `s-gamut3-cine`, `CodingEquations` `rec709` | the clip was shot S-Log3 / S-Gamut3.Cine |
| Timecode | `LtcChangeTable` (`tcFps` 24): LTC changes at frame 0 (`16261010`, `increment`) and frame 419 (`03441010`, `end`) | camera LTC timecode, unrelated to wall-clock time |
| Device / lens | `ILCE-7M4`, serial `99999`, `FE PZ 16-35mm F4 G` | sanitized serial, not a real serial |
| Per-frame event tables | `ImagerControlInformation`, `LensControlInformation`, `DistortionCorrection`, `Gyroscope`, `Accelerometor` | each contains only a `start` event at frame 0 here; they mark where per-frame sensor data changes (useful for stabilization workflows) |
| Clip linkage | `TargetMaterial` `umidRef`, `Duration` `420` frames, top-level `lastUpdate` `2025-08-29T21:45:28+09:00` | ties the sidecar to the clip's UMID; `lastUpdate` is the exiftool `LastUpdate` tag |

Practical note for the importer: the `.XML` sidecar must be kept together with the MP4, otherwise the
video's GPS data is lost.
