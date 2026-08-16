# -*- coding: utf-8 -*-
"""
09_kabutan_articles.py
------------------------
株探（s.kabutan.jp）の「特集」カテゴリのニュース一覧から、以下4種類の
記事を抜き出し、docs/articles.json に蓄積します（Webページ表示用）。

  - 決算インパクト（プラス／マイナス）
  - 話題株ダイジェスト
  - ストップ高（本日の【ストップ高／ストップ安】引け、の記事）
  - ストップ安（同上。1つの記事で両方を扱っているため、ストップ高と
    同じ記事がここにも入ります）

記事のURL（例："n202608100927"）に日付が埋め込まれているので、そこから
日付を割り出してカレンダー表示に使えるようにしています。

株探の無料枠では直近20件程度しか一覧に出ないため、毎日実行することで
少しずつ蓄積していく想定です（1回で全期間を遡ることはできません）。

使い方：
    python 09_kabutan_articles.py
"""

import re
import os
import json
import requests

CATEGORY_URL = "https://s.kabutan.jp/market_news/?category_org_id=5"  # 特集カテゴリ
ARTICLES_FILE = "docs/articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

LINK_PATTERN = re.compile(
    r'<a\b[^>]*\bhref="((?:https?://s\.kabutan\.jp)?/news/n(\d{4})(\d{2})(\d{2})\d+/?)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)


def classify(title: str):
    """タイトルから、記事の分類（複数になりうる）を返す"""
    categories = []
    if "決算プラス・インパクト" in title:
        categories.append(("決算インパクト", "プラス"))
    if "決算マイナス・インパクト" in title:
        categories.append(("決算インパクト", "マイナス"))
    if "今週の話題株ダイジェスト" in title:
        categories.append(("話題株", None))
    if "ストップ高" in title and "ストップ安" in title:
        # 1つの記事でストップ高・ストップ安の両方を扱っている
        categories.append(("ストップ高", None))
        categories.append(("ストップ安", None))
    return categories


def load_articles() -> list:
    if not os.path.exists(ARTICLES_FILE):
        return []
    try:
        with open(ARTICLES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_articles(items: list):
    os.makedirs(os.path.dirname(ARTICLES_FILE), exist_ok=True)
    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2, allow_nan=False)


def fetch_articles() -> list:
    res = requests.get(CATEGORY_URL, headers=HEADERS, timeout=20)
    res.raise_for_status()
    res.encoding = res.apparent_encoding

    all_links = LINK_PATTERN.findall(res.text)
    print(f"  [診断] status={res.status_code}, リンク総数={len(all_links)}")

    found = []
    for url, year, month, day, title in all_links:
        categories = classify(title)
        if not categories:
            continue
        if url.startswith("/"):
            url = "https://s.kabutan.jp" + url
        date_iso = f"{year}-{month}-{day}"
        for category, kind in categories:
            found.append({
                "date": date_iso,
                "title": title.strip(),
                "url": url,
                "category": category,
                "kind": kind,
            })
    return found


def main():
    print("株探（特集カテゴリ）を確認しています...")
    found = fetch_articles()
    print(f"  見つかった対象記事: {len(found)} 件")

    if not found:
        print("  対象記事が見つかりませんでした（ページ構造が変わった可能性があります）。")

    existing = load_articles()
    existing_keys = {(item["url"], item["category"]) for item in existing}

    new_items = [item for item in found if (item["url"], item["category"]) not in existing_keys]
    print(f"  新規: {len(new_items)} 件")

    if new_items:
        combined = existing + new_items
        combined.sort(key=lambda x: (x["date"], x["url"]), reverse=True)
        save_articles(combined)
        print(f"{ARTICLES_FILE} を更新しました（合計 {len(combined)} 件）。")
    else:
        print("新しい記事はありませんでした。")


if __name__ == "__main__":
    main()
