# -*- coding: utf-8 -*-
"""
05_backfill.py
----------------
指定した期間（START_DATE〜END_DATE）について、株ドラゴンの過去日付ページから
毎日分をさかのぼって取得し、docs/results.json にまとめて追加します。

【重要な制限】
F（出来高急増×上ひげ陽線）は、始値をみんかぶの「当日ページ」から取得する
仕組みのため、過去日付には対応していません。バックフィルでは A・B・C・D・E の
5種類のみを埋めます（F は空欄になります）。

時価総額は「発行済株式数 × その日の終値」で計算します。発行済株式数は
このバックフィル実行全体で使い回す一時的なキャッシュを使うため（ファイルには
保存されません）、同じ銘柄については取得した時点の株式数がその後の日付にも
使われます（頻繁に変わる情報ではないため、実用上は問題ありません）。

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
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)


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
    shares_session_cache = {}  # このバックフィル実行全体で使い回す（保存はしない）

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

        stopdaka_plain = stopdaka_full[["code", "name", "close"]].copy()

        matched_c = pd.merge(
            takane[["code", "name"]] if takane is not None else pd.DataFrame(columns=["code", "name"]),
            stopdaka_full[["code", "name", "close"]],
            on="code",
            suffixes=("", "_y"),
        )

        matched_b = stopdaka_full[stopdaka_full["code"].isin(prev_stopdaka_full_codes)]

        stopdaka_plain = enrich_with_market_cap(stopdaka_plain, shares_session_cache)
        matched_b = enrich_with_market_cap(matched_b, shares_session_cache)
        matched_c = enrich_with_market_cap(matched_c, shares_session_cache)
        dekizou_full = enrich_with_market_cap(dekizou_full, shares_session_cache)
        ipo_full = enrich_with_market_cap(ipo_full, shares_session_cache)

        trade_date = d.isoformat()  # 上のチェックで実際のデータ日付と一致していることを確認済み
        results[trade_date] = {
            "A": to_records(stopdaka_plain),
            "B": to_records(matched_b),
            "C": to_records(matched_c),
            "D": to_records(dekizou_full),
            "E": to_records(ipo_full),
            "F": [],  # 過去日付は始値データが無いため空欄
        }
        print(
            f"  {trade_date}: A={len(stopdaka_plain)} B={len(matched_b)} "
            f"C={len(matched_c)} D={len(dekizou_full)} E={len(ipo_full)}"
        )

        prev_stopdaka_full_codes = set(stopdaka_full["code"])
        d += timedelta(days=1)
        time.sleep(0.5)  # 相手サイトへの配慮

    save_results(results)
    print(f"完了：{RESULTS_FILE} に保存しました。")


if __name__ == "__main__":
    main()
