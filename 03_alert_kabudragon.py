# -*- coding: utf-8 -*-
"""
03_alert_kabudragon.py
------------------------
株ドラゴンのランキングページを取得し、以下5つの組み合わせに該当する銘柄を
docs/results.json に書き出します（Webページ表示用）。

  A) 年初来高値 × ストップ高
  B) 出来高急増 × ストップ高
  C) IPO銘柄 × ストップ高
  D) 出来高急増 × 上ひげ陽線（上ひげの長さが始値の10%以上のもののみ）
  E) 2営業日連続ストップ高

前提：
- 株ドラゴンは毎日21時頃に更新されるので、このスクリプトも21時以降に
  実行してください（21時前に実行すると前日のデータのままです）。
- 同じフォルダに kabu_lib.py が必要です。

使い方：
    python 03_alert_kabudragon.py
"""

import os
import json
import time
from datetime import date, timedelta

import pandas as pd

from kabu_lib import (
    fetch_codes,
    filter_true_stopdaka,
    fetch_open_price,
    fetch_shares_outstanding,
    to_records,
    archived_url,
    parse_trade_date_to_iso,
    enrich_with_market_cap,
    format_market_cap,
)

STOPDAKA_URL = "https://www.kabudragon.com/ranking/stopdaka200.html"  # 200件表示
TAKANE_URL = "https://www.kabudragon.com/ranking/takane200.html"      # 200件表示
DEKIZOU_URL = "https://www.kabudragon.com/ranking/dekizou200.html"    # 出来高急増 200件表示
IPO_URL = "https://www.kabudragon.com/ranking/ipo200.html"            # 新規上場IPO株 200件表示
DEKIZOU_UWAHIGE_URL = (
    "https://www.kabudragon.com/ranking/dekizou200.html?candle=uwahigeyousen"
)  # 出来高急増 × 上ひげ陽線（株ドラゴン側で既に絞り込み済み）
UWAHIGE_MIN_RATIO = 0.10  # 上ひげの長さ判定：(高値-始値)/始値 がこの値以上のみ残す

RESULTS_FILE = "docs/results.json"  # Webページが読み込むデータファイル


def find_previous_trading_day_stopdaka(today: date) -> pd.DataFrame:
    """
    今日より前の直近の取引日（土日・休場日はスキップ）の
    「本当にストップ高で引けた」銘柄一覧を、株ドラゴンの過去日付ページから取得する
    """
    d = today - timedelta(days=1)
    for _ in range(7):  # 最大7日さかのぼる（連休対策）
        url = archived_url("stopdaka", d)
        try:
            df = fetch_codes(url)
            if not df.empty:
                return filter_true_stopdaka(df)
        except Exception:
            pass
        d -= timedelta(days=1)
    return pd.DataFrame(columns=["code", "name", "trade_date"])


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
    from kabu_lib import JQUANTS_API_KEY
    print(f"  [診断] JQUANTS_API_KEY 読み込み状態: {'あり（' + str(len(JQUANTS_API_KEY)) + '文字）' if JQUANTS_API_KEY else 'なし（未設定）'}")
    shares_session_cache = {}  # この実行の中だけで使い回す（保存はしない）

    # ---- ストップ高・年初来高値の基本データ ----
    stopdaka = fetch_codes(STOPDAKA_URL)
    takane = fetch_codes(TAKANE_URL)
    stopdaka_full = filter_true_stopdaka(stopdaka)
    print(f"  ストップ高候補: {len(stopdaka)} 銘柄 / 本当のストップ高: {len(stopdaka_full)} 銘柄")
    print(f"  年初来高値更新: {len(takane)} 銘柄")

    # 「今日」ではなく、サイトが実際に表示しているデータの日付を使う
    # （休日でサイトが未更新の場合、前営業日のデータがそのまま出ているため）
    if not stopdaka.empty:
        trade_date = parse_trade_date_to_iso(stopdaka["trade_date"].iloc[0], date.today())
    else:
        trade_date = date.today().isoformat()
    data_date = date.fromisoformat(trade_date)

    # ---- A) 年初来高値 × ストップ高 ----
    matched_a = pd.merge(
        takane[["code", "name"]],
        stopdaka_full[["code", "name", "trade_date", "close"]],
        on="code",
        suffixes=("", "_y"),
    )
    matched_a = enrich_with_market_cap(matched_a, shares_session_cache)
    cap_filled = matched_a["cap_label"].notna().sum() if "cap_label" in matched_a.columns else 0
    print(f"  [A] 年初来高値×ストップ高: {len(matched_a)} 銘柄（うち時価総額が埋まった数: {cap_filled}）")

    # ---- B) 出来高急増 × ストップ高 ----
    dekizou = fetch_codes(DEKIZOU_URL)
    dekizou_full = filter_true_stopdaka(dekizou)
    dekizou_full = enrich_with_market_cap(dekizou_full, shares_session_cache)
    print(f"  [B] 出来高急増候補: {len(dekizou)} 銘柄 / うち本当のストップ高: {len(dekizou_full)} 銘柄")

    # ---- C) IPO銘柄 × ストップ高 ----
    ipo = fetch_codes(IPO_URL)
    ipo_full = filter_true_stopdaka(ipo)
    ipo_full = enrich_with_market_cap(ipo_full, shares_session_cache)
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
                code = row["code"]
                if code in shares_session_cache:
                    shares = shares_session_cache[code]
                else:
                    shares = fetch_shares_outstanding(code)
                    shares_session_cache[code] = shares
                cap = format_market_cap(shares * row["close"]) if shares and pd.notna(row["close"]) else None
                long_wick_rows.append({"code": code, "name": row["name"], "cap": cap})
        time.sleep(0.3)
    print(f"  [D] うちヒゲ{int(UWAHIGE_MIN_RATIO*100)}%以上: {len(long_wick_rows)} 銘柄")

    # ---- E) 2営業日連続ストップ高 ----
    prev_stopdaka_full = find_previous_trading_day_stopdaka(data_date)
    prev_codes = set(prev_stopdaka_full["code"]) if not prev_stopdaka_full.empty else set()
    matched_e = stopdaka_full[stopdaka_full["code"].isin(prev_codes)]
    matched_e = enrich_with_market_cap(matched_e, shares_session_cache)
    print(f"  [E] 2営業日連続ストップ高: {len(matched_e)} 銘柄")

    # ---- 結果をJSONにまとめて保存 ----
    results = load_results()
    results[trade_date] = {
        "A": to_records(matched_a),
        "B": to_records(dekizou_full),
        "C": to_records(ipo_full),
        "D": long_wick_rows,
        "E": to_records(matched_e),
    }
    save_results(results)
    print(f"{trade_date} の結果を {RESULTS_FILE} に保存しました。")


if __name__ == "__main__":
    main()
