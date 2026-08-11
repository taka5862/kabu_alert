# -*- coding: utf-8 -*-
"""
03_alert_kabudragon.py
------------------------
株ドラゴンのランキングページを取得し、以下4つの組み合わせに該当する銘柄を
docs/results.json に書き出します（Webページ表示用）。

  A) ストップ高 × 年初来高値
  B) 出来高急増 × ストップ高
  C) IPO銘柄 × ストップ高
  D) 出来高急増 × 上ひげ陽線（上ひげの長さが始値の10%以上のもののみ）

前提：
- 株ドラゴンは毎日21時頃に更新されるので、このスクリプトも21時以降に
  実行してください（21時前に実行すると前日のデータのままです）。

使い方：
    python 03_alert_kabudragon.py
"""

import re
import os
import io
import json
import time
import requests
import pandas as pd

STOPDAKA_URL = "https://www.kabudragon.com/ranking/stopdaka200.html"  # 200件表示
TAKANE_URL = "https://www.kabudragon.com/ranking/takane200.html"      # 200件表示
DEKIZOU_URL = "https://www.kabudragon.com/ranking/dekizou200.html"    # 出来高急増 200件表示
IPO_URL = "https://www.kabudragon.com/ranking/ipo200.html"            # 新規上場IPO株 200件表示
DEKIZOU_UWAHIGE_URL = (
    "https://www.kabudragon.com/ranking/dekizou200.html?candle=uwahigeyousen"
)  # 出来高急増 × 上ひげ陽線（株ドラゴン側で既に絞り込み済み）
UWAHIGE_MIN_RATIO = 0.10  # 上ひげの長さ判定：(高値-始値)/始値 がこの値以上のみ残す

RESULTS_FILE = "docs/results.json"  # Webページが読み込むデータファイル

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 東証公式「制限値幅」テーブル（2026/08/10時点）
# (基準値段の上限（未満）, その価格帯の制限値幅)
PRICE_LIMIT_TABLE = [
    (100, 30), (200, 50), (500, 80), (700, 100), (1000, 150),
    (1500, 300), (2000, 400), (3000, 500), (5000, 700), (7000, 1000),
    (10000, 1500), (15000, 3000), (20000, 4000), (30000, 5000),
    (50000, 7000), (70000, 10000), (100000, 15000), (150000, 30000),
    (200000, 40000), (300000, 50000), (500000, 70000), (700000, 100000),
    (1000000, 150000), (1500000, 300000), (2000000, 400000),
    (3000000, 500000), (5000000, 700000), (7000000, 1000000),
    (10000000, 1500000), (15000000, 3000000), (20000000, 4000000),
    (30000000, 5000000), (50000000, 7000000),
]


def price_limit_width(base_price: float) -> float:
    """前日終値（基準値段）から、その日の制限値幅（上下の値幅）を返す"""
    for upper, width in PRICE_LIMIT_TABLE:
        if base_price < upper:
            return width
    return 10000000  # 50,000,000円以上


def fetch_codes(url: str) -> pd.DataFrame:
    """株ドラゴンのランキングページから コード・名称・取引値（終値）・前日比額・高値 を取り出す"""
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    res.encoding = res.apparent_encoding

    tables = pd.read_html(io.StringIO(res.text))
    # 一番大きい（行数が多い）表が銘柄一覧のはず
    main_table = max(tables, key=len)

    # 列名がページによって少し違うので、位置で拾う
    # 想定：0=順位, 1=コード, 2=名称, 3=市場, 4=日付, 5=取引値(終値), 6=前日比額,
    #       ... 出来高, 高値, 安値（高値・安値は必ず最後の2列）
    main_table = main_table.dropna(how="all")
    main_table.columns = [str(c) for c in main_table.columns]

    def to_num(series):
        return pd.to_numeric(
            series.astype(str).str.replace(",", "").str.replace("−", "-"),
            errors="coerce",
        )

    df = pd.DataFrame()
    df["code"] = main_table.iloc[:, 1].astype(str)
    df["name"] = main_table.iloc[:, 2].astype(str)
    df["trade_date"] = main_table.iloc[:, 4].astype(str)  # 例："8/7(金)"
    df["close"] = to_num(main_table.iloc[:, 5])       # 取引値（終値）
    df["change_amt"] = to_num(main_table.iloc[:, 6])  # 前日比額
    df["high"] = to_num(main_table.iloc[:, -2])       # 高値（後ろから2列目）
    # コード列に数字4桁+英数字のものだけ残す（ヘッダ行などを除外）
    df = df[df["code"].str.match(r"^\d{3,4}[A-Z0-9]?$")]
    return df.reset_index(drop=True)


def filter_true_stopdaka(df: pd.DataFrame) -> pd.DataFrame:
    """
    df（close, change_amt列を含む）から、東証の制限値幅テーブルで計算した
    「本当のストップ高価格」と終値が一致する行だけを残す
    """
    df = df.copy()
    df["prev_close"] = df["close"] - df["change_amt"]
    df["stop_high_price"] = df["prev_close"].apply(
        lambda p: p + price_limit_width(p) if pd.notna(p) else None
    )
    return df[
        (df["stop_high_price"].notna())
        & ((df["close"] - df["stop_high_price"]).abs() <= 3)
    ]


def fetch_open_price(code: str) -> float:
    """みんかぶの個別銘柄チャートページから、その日の「始値」を取得する"""
    url = f"https://minkabu.jp/stock/{code}/chart"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        m = re.search(r"始値[：:]\s*([\d,]+\.?\d*)円", res.text)
        if m:
            return float(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


def to_records(df: pd.DataFrame) -> list:
    """DataFrame（code, name列を含む）を、Webページ用の [{"code":.., "name":..}, ...] に変換"""
    if df.empty:
        return []
    return df[["code", "name"]].to_dict("records")


def load_results() -> dict:
    if not os.path.exists(RESULTS_FILE):
        return {}
    with open(RESULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_results(data: dict):
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("株ドラゴンのデータを取得しています...")

    # ---- A) ストップ高 × 年初来高値 ----
    stopdaka = fetch_codes(STOPDAKA_URL)
    takane = fetch_codes(TAKANE_URL)
    stopdaka_full = filter_true_stopdaka(stopdaka)
    print(f"  [A] ストップ高候補: {len(stopdaka)} 銘柄 / 本当のストップ高: {len(stopdaka_full)} 銘柄")
    print(f"  [A] 年初来高値更新: {len(takane)} 銘柄")
    matched_a = pd.merge(
        stopdaka_full[["code", "name", "trade_date"]],
        takane[["code", "name"]],
        on="code",
        suffixes=("", "_y"),
    )

    trade_date = stopdaka["trade_date"].iloc[0] if not stopdaka.empty else "unknown"

    # ---- B) 出来高急増 × ストップ高 ----
    dekizou = fetch_codes(DEKIZOU_URL)
    dekizou_full = filter_true_stopdaka(dekizou)
    print(f"  [B] 出来高急増候補: {len(dekizou)} 銘柄 / うち本当のストップ高: {len(dekizou_full)} 銘柄")

    # ---- C) IPO銘柄 × ストップ高 ----
    ipo = fetch_codes(IPO_URL)
    ipo_full = filter_true_stopdaka(ipo)
    print(f"  [C] IPO銘柄候補: {len(ipo)} 銘柄 / うち本当のストップ高: {len(ipo_full)} 銘柄")

    # ---- D) 出来高急増 × 上ひげ陽線（ヒゲの長さが10%以上のみ）----
    dekizou_uwahige = fetch_codes(DEKIZOU_UWAHIGE_URL)
    print(f"  [D] 出来高急増×上ひげ陽線候補: {len(dekizou_uwahige)} 銘柄（始値を個別に確認中...）")
    long_wick_rows = []
    for _, row in dekizou_uwahige.iterrows():
        open_price = fetch_open_price(row["code"])
        if open_price and open_price > 0 and pd.notna(row["high"]):
            wick_ratio = (row["high"] - open_price) / open_price
            if wick_ratio >= UWAHIGE_MIN_RATIO:
                long_wick_rows.append({"code": row["code"], "name": row["name"]})
        time.sleep(0.3)  # 相手サイトへの配慮（連続アクセスを避ける）
    print(f"  [D] うちヒゲ{int(UWAHIGE_MIN_RATIO*100)}%以上: {len(long_wick_rows)} 銘柄")

    # ---- 結果をJSONにまとめて保存 ----
    results = load_results()
    results[trade_date] = {
        "A": to_records(matched_a),
        "B": to_records(dekizou_full),
        "C": to_records(ipo_full),
        "D": long_wick_rows,
    }
    save_results(results)
    print(f"{trade_date} の結果を {RESULTS_FILE} に保存しました。")


if __name__ == "__main__":
    main()
