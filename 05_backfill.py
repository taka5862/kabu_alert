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

土日・祝日など株ドラゴンにデータが無い日は自動でスキップします。

使い方：
    python 05_backfill.py
"""

import os
import json
import time
from datetime import date, timedelta

import pandas as pd

from kabu_lib import fetch_codes, filter_true_stopdaka, to_records, archived_url

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

        stopdaka_full = filter_true_stopdaka(stopdaka)
        dekizou_full = filter_true_stopdaka(dekizou) if dekizou is not None else pd.DataFrame()
        ipo_full = filter_true_stopdaka(ipo) if ipo is not None else pd.DataFrame()

        matched_a = pd.merge(
            takane[["code", "name"]] if takane is not None else pd.DataFrame(columns=["code", "name"]),
            stopdaka_full[["code", "name"]],
            on="code",
            suffixes=("", "_y"),
        )

        matched_e = stopdaka_full[stopdaka_full["code"].isin(prev_stopdaka_full_codes)]

        trade_date = d.isoformat()  # 例: "2026-08-07"（サイトの表示揺れに依存しない固定形式）
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
