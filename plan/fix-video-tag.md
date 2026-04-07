exiftool 在使用 11.73 版本时， @src/fotil/cli/geotag.py 中的 copy-gps 命令处理视频文件后 GPS tag 可以在 macOS Photos 中被识别。
在升级到最新版本 13.50 后，同样命令生成的 GPS 信息无法被识别。

使用 exiftool -v <file> 命令保存了两个版本命令生成的 exif 信息，分别是 @tmp/working.gps.txt 和 @tmp/non-working.gps.txt

两个版本的 exiftool 命令可执行文件分别是 `/home/cyf/software/Image-ExifTool-11.73/exiftool` 和 `/usr/bin/vendor_perl/exiftool`。

可用于测试的视频文件 ./tests/data/test.mov

copy-gps 命令调用如下：

```
.venv/bin/fotil geotag copy-gps /share/PhotoShare/photogps/home.HEIC -d ./tests/data/test.mov
```

命令执行过程中，exiftool 会保存备份文件 test.mov_original。

尝试修复 macOS Photos 的 GPS tag 兼容问题。

exiftool 版本历史在 https://exiftool.org/ancient_history.html , 有需要时可以查阅
