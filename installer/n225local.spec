# -*- mode: python ; coding: utf-8 -*-
r"""ランチャー（AutoTrader-Local.exe）だけを実行ファイルにする（PyInstaller）。

配布仕様の正本＝リポルート `DISTRIBUTION_MAP.md`「ローカル版の配布仕様（D15）」。
ここに仕様を書き写さない。

  ★重いもの（numpy / pandas / pyarrow）は**入れない**。インストール先の `lib\` から読む
    （シミュレーター版の `起動_シミュレーション.exe` と同じ作り）。

  使い方（リポルートの共有 .venv で）:
    .venv\Scripts\python -m PyInstaller --noconfirm ^
      --distpath N225LocalEngine\installer\dist --workpath N225LocalEngine\installer\build ^
      N225LocalEngine\installer\n225local.spec
"""
from pathlib import Path

HERE = Path(SPECPATH)                      # …\N225LocalEngine\installer   # noqa: F821
ROOT = HERE.parent                         # …\N225LocalEngine
REPO = ROOT.parent                         # …\N225TradingSystem

ICON = REPO / "assets" / "localengine_dashboard.ico"

a = Analysis(                              # noqa: F821
    [str(HERE / "launcher.py")],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # ランチャーを小さく保つ。これらは lib\ から読むので同梱しない。
    excludes=[
        "numpy", "pandas", "pyarrow", "openpyxl", "bs4", "requests", "urllib3",
        "matplotlib", "scipy", "lxml", "IPython", "pytest", "PyInstaller", "setuptools", "pip",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)                          # noqa: F821

exe = EXE(                                 # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AutoTrader-Local",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,                         # 黒い窓を出さない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)
