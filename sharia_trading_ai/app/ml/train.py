"""
Training & evaluasi model ML sinyal (BUY/SELL/HOLD) dengan walk-forward.

- Split temporal murni: train hanya memakai data SEBELUM periode test,
  dengan purge sebesar horizon label (hindari kebocoran forward return).
- Model: LightGBM multiclass; fallback sklearn HistGradientBoosting bila
  lightgbm tidak tersedia (mis. libomp belum terpasang di mesin deploy).
- Evaluasi bukan sekadar accuracy: simulasi portofolio rebalance tiap N hari
  (top-k sinyal BUY, biaya transaksi round-trip), Sharpe, max drawdown,
  dibandingkan benchmark IHSG dan proxy rule-based teknikal.

CLI:
    python -m app.ml.train                 # walk-forward eval + artifact final
    python -m app.ml.train --horizon 10    # satu horizon saja
    python -m app.ml.train --no-eval       # langsung latih artifact final
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import BASE_DIR
from app.ml.dataset import DATASET_PATH
from app.ml.features import FEATURE_COLUMNS, LABEL_HORIZONS, LABEL_THRESHOLDS

ARTIFACT_DIR = BASE_DIR / "ml" / "artifacts"
WALKFWD_DIR = BASE_DIR.parent / "ml_data" / "walkforward"

TEST_START = "2024-01-01"     # sesuai rencana: test rolling 2024-2026
TOP_K = 5                     # jumlah posisi per rebalance (selaras Top-5 dashboard)
COST_ROUNDTRIP = 0.004        # fee beli+jual IDX ~0.4%
CONF_THRESHOLD = 0.45         # P(BUY) minimum agar sinyal ML dianggap layak

CLASS_MAP = {-1.0: 0, 0.0: 1, 1.0: 2}   # SELL, HOLD, BUY
CLASS_NAMES = ["SELL", "HOLD", "BUY"]


# --------------------------------------------------------------------------- #
#  Engine (LightGBM dengan fallback sklearn)                                  #
# --------------------------------------------------------------------------- #
def _lgbm():
    try:
        import lightgbm as lgb
        return lgb
    except Exception:
        return None


def train_model(X: pd.DataFrame, y: pd.Series):
    """Latih classifier 3 kelas. Return (engine, model)."""
    lgb = _lgbm()
    if lgb is not None:
        params = dict(
            objective="multiclass", num_class=3, learning_rate=0.05,
            num_leaves=63, min_data_in_leaf=200, feature_fraction=0.8,
            bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
            verbosity=-1, seed=42,
        )
        dtrain = lgb.Dataset(X, label=y.map(CLASS_MAP))
        model = lgb.train(params, dtrain, num_boost_round=400)
        return "lightgbm", model
    from sklearn.ensemble import HistGradientBoostingClassifier
    model = HistGradientBoostingClassifier(
        max_iter=400, learning_rate=0.05, max_leaf_nodes=63,
        min_samples_leaf=200, l2_regularization=1.0, random_state=42)
    model.fit(X, y.map(CLASS_MAP))
    return "sklearn", model


def predict_proba(engine: str, model, X: pd.DataFrame) -> np.ndarray:
    """Probabilitas [P(SELL), P(HOLD), P(BUY)] per baris."""
    if engine == "lightgbm":
        return model.predict(X)
    return model.predict_proba(X)


def feature_importance(engine: str, model) -> dict[str, float]:
    if engine == "lightgbm":
        imp = model.feature_importance(importance_type="gain")
        total = imp.sum() or 1.0
        return {f: round(float(v) / total, 4)
                for f, v in sorted(zip(FEATURE_COLUMNS, imp),
                                   key=lambda t: -t[1])}
    return {}   # sklearn HGB tidak punya importance murah; kosongkan


# --------------------------------------------------------------------------- #
#  Backtest sederhana: rebalance tiap N hari, top-k sinyal BUY                #
# --------------------------------------------------------------------------- #
def simulate(df: pd.DataFrame, horizon: int, signal_col: str, rank_col: str,
             top_k: int = TOP_K, cost: float = COST_ROUNDTRIP) -> dict:
    """Equity curve rebalance tiap `horizon` hari bursa di tanggal test.

    df: baris = (date, ticker) dengan kolom signal (bool), rank (desc),
    fwd_ret_{horizon}. Hari tanpa sinyal -> cash (return 0).
    """
    fwd_col = f"fwd_ret_{horizon}"
    dates = np.sort(df["date"].unique())
    if len(dates) == 0:
        return {}
    rebal_dates = dates[::horizon]

    period_returns, picks_log = [], []
    for d in rebal_dates:
        day = df[(df["date"] == d) & df[signal_col]]
        day = day.dropna(subset=[fwd_col])
        if day.empty:
            period_returns.append(0.0)
            continue
        picks = day.nlargest(top_k, rank_col)
        r = float(picks[fwd_col].mean()) - cost
        period_returns.append(r)
        picks_log.append({"date": str(pd.Timestamp(d).date()),
                          "tickers": picks["ticker"].tolist(),
                          "ret": round(r, 4)})

    rets = np.array(period_returns)
    equity = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(equity)
    max_dd = float((equity / peak - 1).min()) if len(equity) else 0.0
    ann = 252 / horizon
    sharpe = float(rets.mean() / rets.std() * np.sqrt(ann)) if rets.std() > 0 else 0.0
    invested = rets != 0

    trade_df = df[df[signal_col]].dropna(subset=[fwd_col])
    return {
        "periods": len(rets),
        "periods_invested": int(invested.sum()),
        "total_return": round(float(equity[-1] - 1), 4) if len(equity) else 0.0,
        "cagr": round(float(equity[-1] ** (ann / max(len(rets), 1)) - 1), 4) if len(equity) else 0.0,
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "avg_period_ret": round(float(rets[invested].mean()), 4) if invested.any() else 0.0,
        "hit_rate_trades": round(float((trade_df[fwd_col] > 0).mean()), 3) if len(trade_df) else 0.0,
        "avg_trade_ret": round(float(trade_df[fwd_col].mean()), 4) if len(trade_df) else 0.0,
        "n_signals": int(len(trade_df)),
        "picks_sample": picks_log[-6:],
    }


def benchmark_index(horizon: int, dates: np.ndarray) -> dict:
    """Buy & hold IHSG di rentang tanggal test yang sama."""
    from app.ml import data_fetch
    mkt = data_fetch.load_history(data_fetch.INDEX_TICKER)["Close"]
    mkt = mkt[(mkt.index >= pd.Timestamp(dates.min())) &
              (mkt.index <= pd.Timestamp(dates.max()))]
    if len(mkt) < 2:
        return {}
    rets = mkt.pct_change().dropna()
    equity = float(mkt.iloc[-1] / mkt.iloc[0])
    peak = mkt.cummax()
    return {
        "total_return": round(equity - 1, 4),
        "sharpe": round(float(rets.mean() / rets.std() * np.sqrt(252)), 2),
        "max_drawdown": round(float((mkt / peak - 1).min()), 4),
    }


def add_rule_proxy(df: pd.DataFrame) -> pd.DataFrame:
    """Proxy rule-based teknikal (jalur_7 + MA cross) sebagai benchmark."""
    df = df.copy()
    df["rule_signal"] = (
        (df["sma50_sma200"] > 0) & (df["breakout20"] > 0)
        & (df["rsi14"] < 70) & (df["vol_ratio20"] > 1.5)
    )
    return df


# --------------------------------------------------------------------------- #
#  Walk-forward                                                               #
# --------------------------------------------------------------------------- #
def quarter_starts(start: str, end: pd.Timestamp) -> list[pd.Timestamp]:
    q = pd.date_range(start=start, end=end, freq="QS")
    return list(q)


def walk_forward(panel: pd.DataFrame, horizon: int,
                 test_start: str = TEST_START) -> tuple[pd.DataFrame, dict]:
    """Latih ulang per kuartal (expanding window), prediksi kuartal berikutnya."""
    label_col, fwd_col = f"label_{horizon}", f"fwd_ret_{horizon}"
    data = panel.dropna(subset=[label_col]).copy()

    preds = []
    for q_start in quarter_starts(test_start, data["date"].max()):
        q_end = q_start + pd.offsets.QuarterEnd(0)
        # purge: horizon hari bursa ~ horizon*1.6 hari kalender sebelum q_start
        train_cutoff = q_start - pd.Timedelta(days=int(horizon * 1.6) + 2)
        train = data[data["date"] < train_cutoff]
        test = data[(data["date"] >= q_start) & (data["date"] <= q_end)]
        if train.empty or test.empty:
            continue
        engine, model = train_model(train[FEATURE_COLUMNS], train[label_col])
        proba = predict_proba(engine, model, test[FEATURE_COLUMNS])
        chunk = test[["date", "ticker", fwd_col, label_col]].copy()
        chunk["p_sell"], chunk["p_hold"], chunk["p_buy"] = proba.T
        preds.append(chunk)

    pred_df = pd.concat(preds, ignore_index=True)
    pred_df["pred_class"] = pred_df[["p_sell", "p_hold", "p_buy"]].values.argmax(axis=1)

    # metrik klasifikasi mentah
    y_true = pred_df[label_col].map(CLASS_MAP)
    acc = float((pred_df["pred_class"] == y_true).mean())
    buy_mask = pred_df["pred_class"] == 2
    buy_prec = float((pred_df.loc[buy_mask, label_col] == 1).mean()) if buy_mask.any() else 0.0

    # backtest ML: sinyal = P(BUY) tertinggi & di atas ambang
    pred_df["ml_signal"] = (pred_df["pred_class"] == 2) & (pred_df["p_buy"] >= CONF_THRESHOLD)
    bt_ml = simulate(pred_df, horizon, "ml_signal", "p_buy")

    # benchmark rule proxy di tanggal yang sama
    rule_df = add_rule_proxy(panel[panel["date"].isin(pred_df["date"].unique())])
    rule_df = rule_df.dropna(subset=[fwd_col])
    bt_rule = simulate(rule_df, horizon, "rule_signal", "rs_20")

    bt_idx = benchmark_index(horizon, pred_df["date"].unique())

    metrics = {
        "horizon": horizon,
        "threshold_buy_sell": LABEL_THRESHOLDS[horizon],
        "test_range": [str(pred_df['date'].min().date()), str(pred_df['date'].max().date())],
        "n_test_rows": int(len(pred_df)),
        "accuracy": round(acc, 3),
        "baseline_majority": round(float(y_true.value_counts(normalize=True).max()), 3),
        "buy_precision": round(buy_prec, 3),
        "backtest_ml": bt_ml,
        "backtest_rule_proxy": bt_rule,
        "benchmark_ihsg": bt_idx,
    }
    return pred_df, metrics


# --------------------------------------------------------------------------- #
#  Artifact final                                                             #
# --------------------------------------------------------------------------- #
def train_final(panel: pd.DataFrame, horizon: int,
                wf_metrics: dict | None = None, suffix: str = "") -> Path:
    """Latih model final di seluruh data dan simpan artifact + metadata.

    suffix mis. "_screened" = varian yang dilatih pada populasi screening
    konvensional top-10/hari (dipakai alur fokus dua tahap).
    """
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    label_col = f"label_{horizon}"
    data = panel.dropna(subset=[label_col])
    engine, model = train_model(data[FEATURE_COLUMNS], data[label_col])

    if engine == "lightgbm":
        model_path = ARTIFACT_DIR / f"ml_signal_h{horizon}{suffix}.txt"
        model.save_model(str(model_path))
    else:
        import joblib
        model_path = ARTIFACT_DIR / f"ml_signal_h{horizon}{suffix}.joblib"
        joblib.dump(model, model_path)

    meta = {
        "engine": engine,
        "model_file": model_path.name,
        "variant": suffix.lstrip("_") or "global",
        "horizon": horizon,
        "label_threshold": LABEL_THRESHOLDS[horizon],
        "conf_threshold": CONF_THRESHOLD,
        "feature_columns": FEATURE_COLUMNS,
        "class_names": CLASS_NAMES,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "train_rows": int(len(data)),
        "train_range": [str(data["date"].min().date()), str(data["date"].max().date())],
        "feature_importance": feature_importance(engine, model),
        "walkforward_metrics": wf_metrics or {},
    }
    (ARTIFACT_DIR / f"ml_signal_h{horizon}{suffix}.meta.json").write_text(
        json.dumps(meta, indent=1))
    return model_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, choices=list(LABEL_HORIZONS))
    ap.add_argument("--no-eval", action="store_true",
                    help="lewati walk-forward, langsung latih artifact final")
    ap.add_argument("--screened", action="store_true",
                    help="latih varian screened (populasi top-10 konvensional/hari, h5)")
    args = ap.parse_args()

    if args.screened:
        from app.ml.dataset import SCREENED_PATH
        panel = pd.read_parquet(SCREENED_PATH)
        horizons = [args.horizon] if args.horizon else [5]
        suffix = "_screened"
    else:
        panel = pd.read_parquet(DATASET_PATH)
        horizons = [args.horizon] if args.horizon else list(LABEL_HORIZONS)
        suffix = ""

    WALKFWD_DIR.mkdir(parents=True, exist_ok=True)
    for h in horizons:
        wf_metrics = None
        if not args.no_eval:
            pred_df, wf_metrics = walk_forward(panel, h)
            pred_df.to_parquet(WALKFWD_DIR / f"preds_h{h}{suffix}.parquet")
            (WALKFWD_DIR / f"metrics_h{h}{suffix}.json").write_text(
                json.dumps(wf_metrics, indent=1))
            print(f"\n=== Horizon {h} hari {suffix or '(global)'} ===")
            print(json.dumps(wf_metrics, indent=1))
        path = train_final(panel, h, wf_metrics, suffix=suffix)
        print(f"Artifact: {path}")


if __name__ == "__main__":
    main()
