# -*- coding: utf-8 -*-
"""
05_backfill.py
----------------
指定した期間（START_DATE〜END_DATE）について、株ドラゴンの過去日付ページから
毎日分をさかのぼって取得し、docs/results.json にまとめて追加します。

【重要な制限】
D（出来高急増×上ひげ陽線）は、始値をみんかぶの「当日ページ」から取得する
仕組みのため、過去日付には対応していません。バックフィルでは A・B・C・E の
4種類のみを埋めます（D は空欄になります）。

時価総額は「その時点の発行済株式数 × その日の終値」を毎回取得して計算する
簡易的なものです（キャッシュはしていません）。そのため同じ銘柄でも、日付に
よって表示される時価総額が多少異なることがあります。

土日・祝日など株ドラゴンにデータが無い日は自動でスキップします。

使い方：
    python 05_backfill.py
"""

import os
import json
import time
from datetime import date, timedelta

import pandas as pd

from kabu_lib import (
    fetch_codes,
    filter_true_stopdaka,
    to_records,
    archived_url,
    parse_trade_date_to_iso,
    enrich_with_market_cap,
)

START_DATE = date(2026, 7, 1)
END_DATE = date.today()

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


def fetch_day(d: date):
    """
    指定日の株ドラゴンデータを取得する。
    その日にデータが無ければ (None, None, None, None) を返す。
    """
    try:
        stopdaka = fetch_codes(archived_url("stopdaka", d))
        if stopdaka.empty:
            return None, None, None, None
        takane = fetch_codes(archived_url("takane", d))
        dekizou = fetch_codes(archived_url("dekizou", d))
        ipo = fetch_codes(archived_url("ipo", d))
        return stopdaka, takane, dekizou, ipo
    except Exception as e:
        print(f"  {d}: 取得エラー（スキップします） {e}")
        return None, None, None, None


def main():
    results = load_results()
    prev_stopdaka_full_codes = set()  # 前の取引日の「本当のストップ高」コード集合

    d = START_DATE
    while d <= END_DATE:
        if d.weekday() >= 5:  # 土(5)・日(6)はスキップ
            d += timedelta(days=1)
            continue

        print(f"{d} を取得中...")
        stopdaka, takane, dekizou, ipo = fetch_day(d)

        if stopdaka is None:
            print(f"  {d}: データなし（休場日の可能性）。スキップします。")
            d += timedelta(days=1)
            time.sleep(0.5)
            continue

        # ページの表示日付が、リクエストした日付と一致するか確認
        # （祝日などで前営業日のデータがそのまま出ている場合は、実際の取引日として扱う）
        actual_trade_date = parse_trade_date_to_iso(stopdaka["trade_date"].iloc[0], d)
        if actual_trade_date != d.isoformat():
            print(f"  {d}: ページの表示は{actual_trade_date}のデータ（休場日と判断しスキップ）。")
            d += timedelta(days=1)
            time.sleep(0.5)
            continue

        stopdaka_full = filter_true_stopdaka(stopdaka)
        dekizou_full = filter_true_stopdaka(dekizou) if dekizou is not None else pd.DataFrame()
        ipo_full = filter_true_stopdaka(ipo) if ipo is not None else pd.DataFrame()

        matched_a = pd.merge(
            takane[["code", "name"]] if takane is not None else pd.DataFrame(columns=["code", "name"]),
            stopdaka_full[["code", "name", "close"]],
            on="code",
            suffixes=("", "_y"),
        )

        matched_e = stopdaka_full[stopdaka_full["code"].isin(prev_stopdaka_full_codes)]

        matched_a = enrich_with_market_cap(matched_a)
        dekizou_full = enrich_with_market_cap(dekizou_full)
        ipo_full = enrich_with_market_cap(ipo_full)
        matched_e = enrich_with_market_cap(matched_e)

        trade_date = d.isoformat()  # 上のチェックで実際のデータ日付と一致していることを確認済み
        results[trade_date] = {
            "A": to_records(matched_a),
            "B": to_records(dekizou_full),
            "C": to_records(ipo_full),
            "D": [],  # 過去日付は始値データが無いため空欄
            "E": to_records(matched_e),
        }
        print(
            f"  {trade_date}: A={len(matched_a)} B={len(dekizou_full)} "
            f"C={len(ipo_full)} E={len(matched_e)}"
        )

        prev_stopdaka_full_codes = set(stopdaka_full["code"])
        d += timedelta(days=1)
        time.sleep(0.5)  # 相手サイトへの配慮

    save_results(results)
    print(f"完了：{RESULTS_FILE} に保存しました。")


if __name__ == "__main__":
    main()
