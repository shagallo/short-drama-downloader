# macOS 1.2.0 构建及兼容说明

## 用户目录

- 配置、任务记录和临时文件：`~/Library/Application Support/ShortDramaDownloader/`
- 默认视频目录：`~/Downloads/短剧下载神器/`
- 不在 `.app` 包内保存文件，从只读安装镜像运行也不需要写入镜像。
- 设置支持 `~/` 路径。检测到 Windows 盘符或应用包内路径会使用默认目录并提示；用户可点击“恢复本机默认目录”。
- 保存目录会执行实际写入测试。外接磁盘断开或权限被拒绝时会报告错误，不会悄悄切换已选磁盘。
- 更换安装包不会删除上述用户目录。旧版位于 `.app/Contents/MacOS` 内的数据不会自动删除；如需保留旧任务，可以先备份并手动迁移至新数据目录。

## 无需本机 Mac 的构建

仓库 `.github/workflows/build-mac.yml` 在 GitHub 的 macOS 构建机上生成两个独立安装包：

- `短剧下载神器开源版_mac_v1.2.0_arm64.dmg`：Apple Silicon。
- `短剧下载神器开源版_mac_v1.2.0_x86_64.dmg`：Intel。

拥有仓库写入/Actions 执行权限的账号推送更新至 `main` 或 `build/mac-*` 分支，或者在已更新代码的分支上手动运行工作流。构建使用 macOS 15 构建机；未验证更旧系统。

构建执行单元测试、打包程序离线自检、原生 WebKit 窗口测试、默认目录写入、Finder 打开和合成视频处理测试。测试不注册设备，不获取第三方视频。安装包只包含程序资源及对应 CPU 的 FFmpeg，不携带 Windows 可执行文件、本机设备配置或下载历史。

构建成功后从 Actions Artifacts 下载 DMG 与 SHA256 文件，拖动应用至 Applications。

安装包尚未配置 Apple Developer ID 签名与公证；首次打开可能触发 macOS 安全提示，需要在系统设置的“隐私与安全性”中允许该应用。不要关闭系统整体安全检查。

## Mac 本机重新打包

需 Python 3.12。在源码目录执行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt pillow
python -m unittest discover -s tests -v
python tools_make_icon.py
```

之后按仓库工作流中的图标转换、PyInstaller 和 DMG 步骤执行。原生 Mac 安装包必须在 macOS 构建；Windows 生成的压缩源码包不是 Mac 应用。

调试模式：`AUTO_DEVICE_CONFIG=0 APP_WINDOW=0 OPEN_BROWSER=0 python app.py 5055`。打包后的程序支持 `--self-test` 与 `--ui-smoke-test`（后者会打开并关闭一个测试窗口）。
