# -*- coding: utf-8 -*-
"""
07_alert_early.py
--------------------
17時ごろ（市場が閉まった直後）に実行する、速報版のスクリプトです。
株ドラゴンは21時頃まで更新されないため、Yahoo!ファイナンスのランキング
ページ（ほぼリアルタイム更新）を使って「A：年初来高値×ストップ高」だけを
先出しします。

B〜E（出来高急増・IPO・上ひげ陽線・2連続ストップ高）は株ドラゴンの
データが必要なため、これまで通り21:15の本実行（03_alert_kabudragon.py）
で埋まります。21:15になると、Aもより正確な株ドラゴンベースの判定結果で
上書きされます。

使い方：
    python 07_alert_early.py
"""

import os
import json
from datetime import date

import pandas as pd

from kabu_lib import fetch_yahoo_ranking, enrich_with_market_cap, to_records

STOPHIGH_URL = "https://finance.yahoo.co.jp/stocks/ranking/stopHigh?market=all"
YEARHIGH_URL = "https://finance.yahoo.co.jp/stocks/ranking/yearToDateHigh?market=all"

RESULTS_FILE = "docs/results.json"


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
    print("Yahoo!ファイナンスのデータを取得しています（速報版）...")
    stophigh = fetch_yahoo_ranking(STOPHIGH_URL)
    yearhigh = fetch_yahoo_ranking(YEARHIGH_URL)
    print(f"  ストップ高: {len(stophigh)} 銘柄 / 年初来高値更新: {len(yearhigh)} 銘柄")

    matched = pd.merge(stophigh, yearhigh, on="code", suffixes=("", "_y"))
    matched = enrich_with_market_cap(matched)
    print(f"  [A・速報] 年初来高値×ストップ高: {len(matched)} 銘柄")

    trade_date = date.today().isoformat()

    results = load_results()
    day = results.get(trade_date, {})
    # 21:15の本実行が既にAを埋めていれば、速報版で上書きしない
    # （株ドラゴンベースの正確な判定を優先する）
    if not day.get("A"):
        day["A"] = to_records(matched)
    results[trade_date] = day
    save_results(results)
    print(f"{trade_date} の速報データを {RESULTS_FILE} に保存しました。")


if __name__ == "__main__":
    main()
