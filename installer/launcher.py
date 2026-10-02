# -*- coding: utf-8 -*-
r"""ローカル版のランチャー（アイコンから起動する実行ファイルの中身）。

シミュレーター版（`起動_シミュレーション.exe`）と同じ作りで、**起動役だけ**を実行ファイルにする。
戦略やダッシュボードの本体は `.py` のまま同梱し、依存（numpy・pandas・pyarrow ほか）は
インストール先の `lib\` から読む。配布仕様の正本＝リポルート `DISTRIBUTION_MAP.md`「ローカル版の配布仕様（D15）」。

  インストール先の形:
    AutoTrader-Local.exe   ← これ（ランチャー）
    run_dashboard.py           ← 入口（ソースのまま）
    app\  strategies\  data\   ← 本体とユーザーデータ
    lib\                       ← 依存（numpy / pandas / pyarrow / requests / bs4 / openpyxl）
    manual\manual.html         ← マニュアル
"""
import os
import runpy
import sys
import tkinter.messagebox as mbox


def main() -> int:
    # 実行ファイルの置かれているフォルダ＝インストール先。
    base = os.path.dirname(os.path.abspath(sys.executable))

    lib = os.path.join(base, "lib")
    entry = os.path.join(base, "run_dashboard.py")

    # 依存は lib\ から読む。インストール先そのものも import 元にする（app パッケージ）。
    for path in (lib, base):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

    # 作業フォルダをインストール先に合わせる（設定・データの相対パスがここを基準にしているため）。
    os.chdir(base)

    if not os.path.isfile(entry):
        mbox.showerror("AutoTrader Local",
                       f"起動ファイルが見つかりません:\n{entry}\n\n再インストールしてください。")
        return 1
    if not os.path.isdir(lib):
        mbox.showerror("AutoTrader Local",
                       f"ライブラリのフォルダが見つかりません:\n{lib}\n\n再インストールしてください。")
        return 1

    try:
        runpy.run_path(entry, run_name="__main__")
    except Exception as e:                      # 起動できない理由を黙って消さない
        mbox.showerror("AutoTrader Local", f"起動できませんでした:\n{type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
