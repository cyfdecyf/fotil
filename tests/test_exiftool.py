from pathlib import Path

from fotil.exiftool import Exiftool


def test_read_metadata():
    exiftool = Exiftool()
    img_a = Path('a.jpg')
    img_b = Path('b.jpg')
    test_img = [img_a, img_b]

    metadata = exiftool.read(
        test_img, tags=['DateTimeOriginal'], cd_dir=Path('tests/data/img')
    )

    assert metadata[0]['DateTimeOriginal'] == '2024:01:02 03:04:05'
    assert metadata[1]['DateTimeOriginal'] == '2023:04:05 06:07:08'

    dt = Exiftool.parse_date(metadata[0]['DateTimeOriginal'])
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 2
    assert dt.hour == 3
    assert dt.minute == 4
    assert dt.second == 5

    assert Exiftool.create_date(metadata[0]) == dt
