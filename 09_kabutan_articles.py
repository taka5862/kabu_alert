# -*- coding: utf-8 -*-
"""
09_kabutan_articles.py
------------------------
株探（s.kabutan.jp）のニュース一覧から、以下4種類の記事を抜き出し、
docs/articles.json に蓄積します（Webページ表示用）。

  - 決算インパクト（プラス／マイナス）
  - 話題株ダイジェスト
  - ストップ高安（本日の【ストップ高／ストップ安】引け、の記事）

「話題株ダイジェスト」は「特集」カテゴリとは別カテゴリに分類されている
ことがあるため、複数のカテゴリページ＋カテゴリなしの全体一覧の両方を
チェックして、取りこぼしを防いでいます（URLで重複除去するので、同じ
記事が複数ページに出てきても二重登録にはなりません）。

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

# 複数のページをチェックして取りこぼしを防ぐ
# category_org_id: 5=特集, 4=注目株（ページによって分類が違うことがあるため両方見る）
SOURCE_URLS = [
    "https://s.kabutan.jp/market_news/",                     # カテゴリなし（全体）
    "https://s.kabutan.jp/market_news/?category_org_id=5",   # 特集
    "https://s.kabutan.jp/market_news/?category_org_id=4",   # 注目株
]
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
    if "話題株ダイジェスト" in title:
        categories.append(("話題株", None))
    if "ストップ高" in title and "ストップ安" in title:
        # 1つの記事でストップ高・ストップ安の両方を扱っているため、1カテゴリにまとめる
        categories.append(("ストップ高安", None))
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
    found = []
    seen_urls = set()

    for url_page in SOURCE_URLS:
        try:
            res = requests.get(url_page, headers=HEADERS, timeout=20)
            res.raise_for_status()
            res.encoding = res.apparent_encoding
        except Exception as e:
            print(f"  [診断] {url_page}: 取得エラー {e}")
            continue

        all_links = LINK_PATTERN.findall(res.text)
        print(f"  [診断] {url_page} : status={res.status_code}, リンク総数={len(all_links)}")

        for url, year, month, day, title in all_links:
            categories = classify(title)
            if not categories:
                continue
            if url.startswith("/"):
                url = "https://s.kabutan.jp" + url
            if url in seen_urls:
                continue  # 別ページで既に見つけた記事は重複カウントしない
            seen_urls.add(url)
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
    print("株探のニュース一覧を確認しています...")
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
