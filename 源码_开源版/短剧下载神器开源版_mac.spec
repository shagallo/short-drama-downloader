# -*- mode: python ; coding: utf-8 -*-
# macOS 打包配置：在 macOS（或 GitHub Actions macos 构建机）上执行
#   pyinstaller --clean --noconfirm 短剧下载神器开源版_mac.spec
# 需要先生成 static/assets/app_icon.icns（CI 流水线会自动生成）。

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
from pathlib import Path


webview_hidden = collect_submodules('webview')
ii_datas, ii_binaries, ii_hidden = collect_all('imageio_ffmpeg')

a = Analysis(
    ['app.py'],
    pathex=['liushen'],
    binaries=ii_binaries,
    datas=[('1.py', '.'), ('static', 'static')]
        + [(str(p), str(p.parent)) for p in Path('liushen').rglob('*.py') if p.name != 'test_sign.py']
        + collect_data_files('webview')
        + ii_datas,
    hiddenimports=[
        'flask',
        'requests',
        'Crypto.Cipher.AES',
        'Crypto.Util.Counter',
        'Crypto.Util.Padding',
        'gmssl.sm3',
        'betterproto',
        'bs4',
        'lxml',
        'webview',
        'objc',
        'Foundation',
        'AppKit',
        'WebKit',
        'platform_support',
        'smoke_test',
        'device_register',
    ] + webview_hidden + ii_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='短剧下载神器开源版',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='短剧下载神器开源版',
)
app = BUNDLE(
    coll,
    name='短剧下载神器开源版.app',
    icon='static/assets/app_icon.icns',
    bundle_identifier='com.duanju.downloader.opensource',
    info_plist={
        'CFBundleShortVersionString': '1.2.0',
        'CFBundleVersion': '1.2.0',
        'NSDownloadsFolderUsageDescription': '保存您选择下载的短剧分集。',
        'NSRemovableVolumesUsageDescription': '保存短剧到您选择的外部磁盘。',
        'CFBundleName': '短剧下载神器',
        'NSHighResolutionCapable': True,
    },
)
