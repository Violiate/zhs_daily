# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for zhs_daily.

Environment variables:
    ZHS_VARIANT = full | lite       Default: full
    ZHS_ONEFILE = 1 | 0             Default: 1 (single-file exe)

- full (`zhs-daily.exe`): bundles playwright, ddddocr, onnxruntime, opencv, numpy, Pillow.
  Zero external dependencies; supports automatic slider/click captcha solving via system Edge.
- lite (`zhs-daily-lite.exe`): lightweight (~15MB) build with core HTTP protocol, QR login,
  and AI quiz answering; excludes heavy OCR/CV libraries.
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

VARIANT = os.environ.get("ZHS_VARIANT", "full").lower()
ONEFILE = os.environ.get("ZHS_ONEFILE", "1") == "1"

ROOT = os.path.dirname(os.path.abspath(SPECPATH))
NAME = "zhs-daily" if VARIANT == "full" else "zhs-daily-lite"
ENTRY = os.path.join(ROOT, "daily.py")


def _need(rel):
    path = os.path.join(ROOT, rel)
    return os.path.exists(path)


# ------------------------------------------------------------------ 数据文件
datas = []
for rel, dest in (
    ("config.example.yaml", "."),
    ("README.md", "."),
    ("DISCLAIMER.md", "."),
    ("LICENSE", "."),
):
    if _need(rel):
        datas.append((os.path.join(ROOT, rel), dest))

binaries = []

# ------------------------------------------------------------------ 隐藏导入
hiddenimports = [
    "zhsgo",
    "zhsgo.cli",
    "yaml",
    "loguru",
    "requests",
    "Crypto",
    "Crypto.Cipher",
    "Crypto.Cipher.AES",
    "PIL",
    "PIL.Image",
    "PIL.ImageOps",
]

# ------------------------------------------------------------------ 排除项
excludes = [
    "tkinter",
    "_tkinter",
    "pkg_resources",
    "debugpy",
    "pydevd",
    "zmq",
    "matplotlib",
    "pandas",
    "scipy",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "jupyter",
    "pytest",
    "notebook",
    "openai",
    "tiktoken",
    "transformers",
    "torch",
    "tests",
]

# ------------------------------------------------------------------ 变体差异
if VARIANT == "full":
    datas += collect_data_files("ddddocr")
    datas += collect_data_files("playwright")
    binaries += collect_dynamic_libs("onnxruntime")
    hiddenimports += [
        "playwright",
        "playwright.sync_api",
        "playwright.async_api",
        "playwright._impl._driver",
        "ddddocr",
        "onnxruntime",
        "cv2",
        "numpy",
    ]
else:
    excludes += ["playwright", "ddddocr", "onnxruntime", "cv2", "numpy"]


# ------------------------------------------------------------------ 构建
a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(ROOT, "packaging", "rthook_py312.py")],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

_common = dict(
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压缩容易触发 Windows Defender 误报，保持不压缩更安全
    upx=False,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=os.path.join(ROOT, "packaging", "version_info.txt")
    if _need(os.path.join("packaging", "version_info.txt")) else None,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **_common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_common)
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False, upx=False, name=NAME,
    )
