# -*- coding: utf-8 -*-
"""画面の 2 つの決まりを、画面を開かずに確かめる（Tk の窓を作らない・ネットワークを使わない）。

① BT／再最適化が例外で止まったとき、後から呼ぶ表示の関数にエラーの内容が届く
   （except の変数は except を抜けると消えるので、文字列にして渡していること）。
② パラメーター画面は null の欄を null のまま保存する（文字列 "None" にしない）。
"""
import json

import pandas as pd

from app.dashboard import bt_view, param_form, reopt_dialog


class _Status:
    def __init__(self):
        self.text = None

    def config(self, text=None, **_):
        self.text = text


def _deferred():
    """self.after(0, f) の代わり：f を積んでおき、except を抜けたあとで呼ぶ（Tk も after の関数は後で呼ぶ）。"""
    pending = []
    return pending, (lambda ms, f: pending.append(f))


def test_bt_error_reaches_dialog(monkeypatch):
    shown = []
    monkeypatch.setattr(bt_view.messagebox, "showerror", lambda title, msg, **k: shown.append((title, msg)))
    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]},
                      index=pd.DatetimeIndex(["2026-11-16 08:45"]))
    monkeypatch.setattr(bt_view.data_provider, "load_parquet", lambda p: df)
    monkeypatch.setattr(bt_view.data_provider, "window", lambda d, **k: d)

    class _Ctrl:
        def backtest(self, name, d):
            raise AttributeError("'X' object has no attribute 'cfg'")

    v = bt_view.BacktestView.__new__(bt_view.BacktestView)       # 窓は作らない
    v.controller, v.name, v.parquet_path, v.months, v.warmup_bars = _Ctrl(), "X", None, 6, 300
    v.status = _Status()
    pending, v.after = _deferred()
    v._worker()
    for f in pending:
        f()
    assert shown == [("BTエラー", "AttributeError: 'X' object has no attribute 'cfg'")]
    assert v.status.text.startswith("BT エラー")


def test_reopt_errors_reach_display(monkeypatch):
    import app.engine.reopt as reopt

    def _boom(*a, **k):
        raise RuntimeError("提案に失敗")
    monkeypatch.setattr(reopt, "propose", _boom)
    monkeypatch.setattr(reopt, "apply", _boom)
    shown = []
    monkeypatch.setattr(reopt_dialog.messagebox, "showerror", lambda title, msg, **k: shown.append((title, msg)))

    d = reopt_dialog.ReoptDialog.__new__(reopt_dialog.ReoptDialog)
    d.folder, d.ctx, d.proposals = None, None, []
    d.status = _Status()
    pending, d.after = _deferred()
    d._propose_worker()
    d._apply_worker()
    for f in pending:
        f()
    assert d.status.text == "エラー: 提案に失敗"
    assert shown == [("適用エラー", "提案に失敗")]


class _Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


def test_param_form_keeps_null(tmp_path):
    path = tmp_path / "config.json"
    cfg = {"a_null": None, "b_null_set": None, "c_null_text": None, "d_num": 3}
    path.write_text(json.dumps(cfg), encoding="utf-8")
    f = param_form.ParamForm.__new__(param_form.ParamForm)      # 窓は作らない
    f.on_saved = f.on_backtest = None
    f.lbl_status = _Status()
    f.after = lambda ms, fn: None
    f.panels = [{"path": path, "cfg": dict(cfg), "vars": {
        "a_null": ("null", _Var("")),            # 空欄のまま保存
        "b_null_set": ("null", _Var("12")),       # 数値を入れた
        "c_null_text": ("null", _Var("None")),    # "None" と打った
        "d_num": ("num", _Var("3")),
    }}]
    f._save(False)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"a_null": None, "b_null_set": 12, "c_null_text": None, "d_num": 3}


def test_null_or_value():
    nv = param_form.ParamForm._null_or_value
    assert [nv(""), nv(" None "), nv("null"), nv("5"), nv("2.5"), nv("abc")] == [None, None, None, 5, 2.5, "abc"]
