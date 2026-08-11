# -*- coding: utf-8 -*-
"""
03_alert_kabudragon.py
------------------------
株ドラゴンのランキングページを取得し、以下3つの組み合わせに該当する
新しい銘柄が見つかったらDiscordに通知します。

  A) ストップ高 × 年初来高値
  B) 出来高急増 × ストップ高
  C) IPO銘柄 × ストップ高
  D) 出来高急増 × 上ひげ陽線（上ひげの長さが始値の10%以上のもののみ）

前提：
- 株ドラゴンは毎日21時頃に更新されるので、このスクリプトも21時以降に
  実行してください（21時前に実行すると前日のデータのままです）。
- 事前に Discord の「ウェブフックURL」を取得し、下の WEBHOOK_URL に貼り付けてください。

使い方：
    python 03_alert_kabudragon.py
"""

import re
import os
import io
import time
import requests
import pandas as pd

# ==== ここを書き換えてください ====
WEBHOOK_URL = "https://discord.com/api/webhooks/1536566128107716698/UORTZr3KAgMqh5tiX3Yo8HWWDQkYhP1ttJPHZoeNaTi-pnSeNz6OumjWmYpVpK_SmQRM"
# ===================================

STOPDAKA_URL = "https://www.kabudragon.com/ranking/stopdaka200.html"  # 200件表示
TAKANE_URL = "https://www.kabudragon.com/ranking/takane200.html"      # 200件表示
DEKIZOU_URL = "https://www.kabudragon.com/ranking/dekizou200.html"    # 出来高急増 200件表示
IPO_URL = "https://www.kabudragon.com/ranking/ipo200.html"            # 新規上場IPO株 200件表示
DEKIZOU_UWAHIGE_URL = (
    "https://www.kabudragon.com/ranking/dekizou200.html?candle=uwahigeyousen"
)  # 出来高急増 × 上ひげ陽線（株ドラゴン側で既に絞り込み済み）
UWAHIGE_MIN_RATIO = 0.10  # 上ひげの長さ判定：(高値-始値)/始値 がこの値以上のみ残す

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

ALERTED_FILE = "alerted_history.csv"  # 通知済み銘柄を記録するファイル（重複通知防止）

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


def load_alerted() -> set:
    if not os.path.exists(ALERTED_FILE):
        return set()
    df = pd.read_csv(ALERTED_FILE, dtype=str)
    return set(df["key"].tolist())


def save_alerted(keys: set):
    pd.DataFrame({"key": sorted(keys)}).to_csv(ALERTED_FILE, index=False, encoding="utf-8-sig")


def send_discord(message: str):
    if "ここにDiscord" in WEBHOOK_URL:
        print("!! WEBHOOK_URL が未設定です。Discord通知はスキップします。")
        print(message)
        return
    res = requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)
    if res.status_code >= 300:
        print(f"Discord通知に失敗しました: {res.status_code} {res.text}")
    else:
        print("Discordに通知しました。")


def alert_group(
    key_prefix: str,
    title: str,
    df: pd.DataFrame,
    already: set,
    always_notify: bool = False,
    fallback_date: str = "",
) -> set:
    """
    df（code, name, trade_date列を含む）の中から、まだ通知していない銘柄を
    Discordに通知する。通知した銘柄の管理キーの集合を返す（保存は呼び出し側で行う）。

    always_notify=True の場合、該当銘柄が0件でも「該当なし」というメッセージを
    Discordに送る（fallback_date はその場合に表示する日付）。
    """
    if df.empty:
        print(f"[{title}] 該当銘柄はありませんでした。")
        if always_notify:
            msg = f"📈 **{fallback_date} {title}**\n該当銘柄なし"
            send_discord(msg)
        return set()

    df = df.copy()
    df["key"] = key_prefix + "_" + df["trade_date"] + "_" + df["code"]
    new_hits = df[~df["key"].isin(already)]

    if new_hits.empty:
        print(f"[{title}] 該当銘柄はありましたが、すべて通知済みでした。")
        return set()

    trade_date = new_hits["trade_date"].iloc[0]
    lines = [f"📈 **{trade_date} {title}**"]
    for _, row in new_hits.iterrows():
        chart_url = f"https://kabutan.jp/stock/chart?code={row['code']}"
        lines.append(f"・{row['code']} {row['name']}\n  {chart_url}")
    message = "\n".join(lines)

    print(message)
    send_discord(message)
    return set(new_hits["key"].tolist())


def main():
    print("株ドラゴンのデータを取得しています...")
    already = load_alerted()
    all_new_keys = set()

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
    all_new_keys |= alert_group("A", "ストップ高×年初来高値 該当銘柄", matched_a, already)

    # ---- B) 出来高急増 × ストップ高 ----
    dekizou = fetch_codes(DEKIZOU_URL)
    dekizou_full = filter_true_stopdaka(dekizou)
    print(f"  [B] 出来高急増候補: {len(dekizou)} 銘柄 / うち本当のストップ高: {len(dekizou_full)} 銘柄")
    all_new_keys |= alert_group(
        "B", "出来高急増×ストップ高 該当銘柄", dekizou_full[["code", "name", "trade_date"]], already
    )

    # ---- C) IPO銘柄 × ストップ高 ----
    ipo = fetch_codes(IPO_URL)
    ipo_full = filter_true_stopdaka(ipo)
    ipo_date = ipo["trade_date"].iloc[0] if not ipo.empty else ""
    print(f"  [C] IPO銘柄候補: {len(ipo)} 銘柄 / うち本当のストップ高: {len(ipo_full)} 銘柄")
    all_new_keys |= alert_group(
        "C",
        "IPO銘柄×ストップ高 該当銘柄",
        ipo_full[["code", "name", "trade_date"]],
        already,
        always_notify=True,
        fallback_date=ipo_date,
    )

    # ---- D) 出来高急増 × 上ひげ陽線（ヒゲの長さが10%以上のみ）----
    dekizou_uwahige = fetch_codes(DEKIZOU_UWAHIGE_URL)
    print(f"  [D] 出来高急増×上ひげ陽線候補: {len(dekizou_uwahige)} 銘柄（始値を個別に確認中...）")
    long_wick_rows = []
    for _, row in dekizou_uwahige.iterrows():
        open_price = fetch_open_price(row["code"])
        if open_price and open_price > 0 and pd.notna(row["high"]):
            wick_ratio = (row["high"] - open_price) / open_price
            if wick_ratio >= UWAHIGE_MIN_RATIO:
                long_wick_rows.append(
                    {
                        "code": row["code"],
                        "name": row["name"],
                        "trade_date": row["trade_date"],
                        "wick_ratio": wick_ratio,
                    }
                )
        time.sleep(0.3)  # 相手サイトへの配慮（連続アクセスを避ける）
    dekizou_uwahige_long = pd.DataFrame(long_wick_rows)
    print(f"  [D] うちヒゲ{int(UWAHIGE_MIN_RATIO*100)}%以上: {len(dekizou_uwahige_long)} 銘柄")
    all_new_keys |= alert_group(
        "D",
        f"出来高急増×上ひげ陽線(ヒゲ{int(UWAHIGE_MIN_RATIO*100)}%以上) 該当銘柄",
        dekizou_uwahige_long[["code", "name", "trade_date"]] if not dekizou_uwahige_long.empty else dekizou_uwahige_long,
        already,
    )

    if all_new_keys:
        already.update(all_new_keys)
        save_alerted(already)


if __name__ == "__main__":
    main()
