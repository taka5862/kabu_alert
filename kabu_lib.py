# -*- coding: utf-8 -*-
"""
kabu_lib.py
------------
株ドラゴン・みんかぶからのデータ取得や、ストップ高判定など、
複数のスクリプトで共通して使う処理をまとめたファイルです。
このファイル単体では実行しません（他のスクリプトから import して使います）。
"""

import re
import io
import time
import requests
import pandas as pd

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


def archived_url(name: str, d) -> str:
    """株ドラゴンの過去日付ページのURLを組み立てる（例：2026/08/07 → .../2026/08/07/stopdaka200.html）"""
    return f"https://www.kabudragon.com/ranking/{d.year}/{d.month:02d}/{d.day:02d}/{name}200.html"


def fetch_codes(url: str) -> pd.DataFrame:
    """株ドラゴンのランキングページから コード・名称・取引値（終値）・前日比額・高値 を取り出す"""
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    res.encoding = res.apparent_encoding

    tables = pd.read_html(io.StringIO(res.text))
    main_table = max(tables, key=len)

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
    """みんかぶの個別銘柄チャートページから、その日の「始値」を取得する（当日分のみ有効）"""
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


def parse_trade_date_to_iso(raw: str, reference) -> str:
    """
    株ドラゴンの日付表示（例："8/10(月)"）を、reference（基準日）の年を使って
    ISO形式（例："2026-08-10"）に変換する。年をまたぐ場合も一応考慮する。
    """
    from datetime import date as _date

    m = re.search(r"(\d{1,2})/(\d{1,2})", str(raw))
    if not m:
        return reference.isoformat()
    month, day = int(m.group(1)), int(m.group(2))
    year = reference.year
    if reference.month == 1 and month == 12:
        year -= 1
    elif reference.month == 12 and month == 1:
        year += 1
    try:
        return _date(year, month, day).isoformat()
    except ValueError:
        return reference.isoformat()


def to_records(df: pd.DataFrame) -> list:
    """
    DataFrame（code, name列を含む。cap_label列があれば含める）を、
    Webページ用の [{"code":.., "name":.., "cap":..}, ...] に変換
    """
    if df.empty:
        return []
    cols = ["code", "name"]
    if "cap_label" in df.columns:
        cols.append("cap_label")
    records = df[cols].to_dict("records")
    for r in records:
        if "cap_label" in r:
            r["cap"] = r.pop("cap_label")
    return records


# ==== 時価総額（毎回、その時点の終値ベースで計算）====


def fetch_shares_outstanding(code: str) -> int:
    """Yahoo!ファイナンスの個別銘柄ページから「発行済株式数」を取得する（1回だけリトライする）"""
    url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    for attempt in range(2):
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            res.raise_for_status()
            m = re.search(r"発行済株式数[^0-9]*([\d,]+)\s*株", res.text)
            if m:
                return int(m.group(1).replace(",", ""))
            print(f"    [発行済株式数] {code}: パターンが見つかりませんでした（status={res.status_code}, 本文長={len(res.text)}）")
            return None
        except Exception as e:
            if attempt == 0:
                time.sleep(2)  # 一時的なエラーの可能性があるので少し待って1回だけ再試行
                continue
            print(f"    [発行済株式数] {code}: 取得エラー（リトライ後も失敗） {e}")
    return None


def format_market_cap(yen: float) -> str:
    """円換算の時価総額を、見やすい「◯◯億円」「◯.◯兆円」形式にする"""
    oku = yen / 100_000_000  # 億円換算
    if oku >= 10000:
        return f"{oku/10000:.2f}兆円"
    elif oku >= 1:
        return f"{oku:,.0f}億円"
    else:
        return f"{yen/10000:,.0f}万円"


def enrich_with_market_cap(df: pd.DataFrame, session_cache: dict = None) -> pd.DataFrame:
    """
    df（code, close列を含む）に、時価総額の表示用ラベル "cap_label" 列を追加する。
    その時点の発行済株式数 × その日の終値、で計算する。
    session_cache を渡すと、同じ実行の中で同じ銘柄への重複アクセスを避けられる
    （ファイルには保存されず、実行が終われば消える一時的なものです）。
    """
    if df.empty:
        df = df.copy()
        df["cap_label"] = []
        return df

    if session_cache is None:
        session_cache = {}

    df = df.copy()
    labels = []
    for _, row in df.iterrows():
        code = row["code"]
        if code in session_cache:
            shares = session_cache[code]
        else:
            shares = fetch_shares_outstanding(code)
            session_cache[code] = shares
            time.sleep(0.3)  # 相手サイトへの配慮
        close = row.get("close")
        if shares and pd.notna(close):
            labels.append(format_market_cap(shares * close))
        else:
            labels.append(None)
    df["cap_label"] = labels
    return df
