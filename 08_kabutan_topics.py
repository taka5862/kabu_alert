# -*- coding: utf-8 -*-
"""
08_kabutan_topics.py
----------------------
株探（s.kabutan.jp）の「特集」カテゴリのニュース一覧から、
「今週の話題株ダイジェスト」「本日の【ストップ高／ストップ安】引け」の
記事だけを抜き出し、docs/topics.json に蓄積します（Webページ表示用）。

株探の無料枠では直近20件程度しか一覧に出ないため、毎日実行することで
少しずつ蓄積していく想定です（1回で全期間を遡ることはできません）。

使い方：
    python 08_kabutan_topics.py
"""

import re
import os
import json
import requests

CATEGORY_URL = "https://s.kabutan.jp/market_news/?category_org_id=5"  # 特集カテゴリ
TOPICS_FILE = "docs/topics.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# タイトルに含まれていれば対象とみなすキーワードと、その種別名
KEYWORD_KIND_MAP = {
    "今週の話題株ダイジェスト": "話題株ダイジェスト",
    "ストップ高": "ストップ高／安 引け",
    "ストップ安": "ストップ高／安 引け",
}

LINK_PATTERN = re.compile(
    r'<a\b[^>]*\bhref="((?:https?://s\.kabutan\.jp)?/news/n\d+/?)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)


def load_topics() -> list:
    if not os.path.exists(TOPICS_FILE):
        return []
    try:
        with open(TOPICS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_topics(items: list):
    os.makedirs(os.path.dirname(TOPICS_FILE), exist_ok=True)
    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2, allow_nan=False)


def classify(title: str):
    for kw, kind in KEYWORD_KIND_MAP.items():
        if kw in title:
            return kind
    return None


def fetch_topic_links() -> list:
    res = requests.get(CATEGORY_URL, headers=HEADERS, timeout=20)
    res.raise_for_status()
    res.encoding = res.apparent_encoding

    all_links = LINK_PATTERN.findall(res.text)
    print(f"  [診断] status={res.status_code}, リンク総数={len(all_links)}")

    found = []
    for url, title in all_links:
        kind = classify(title)
        if not kind:
            continue
        if url.startswith("/"):
            url = "https://s.kabutan.jp" + url
        found.append({"title": title.strip(), "url": url, "kind": kind})
    return found


def main():
    print("株探（特集カテゴリ）を確認しています...")
    found = fetch_topic_links()
    print(f"  見つかった対象記事: {len(found)} 件")

    if not found:
        print("  対象記事が見つかりませんでした（ページ構造が変わった可能性があります）。")

    existing = load_topics()
    existing_urls = {item["url"] for item in existing}

    new_items = [item for item in found if item["url"] not in existing_urls]
    print(f"  新規: {len(new_items)} 件")

    if new_items:
        combined = existing + new_items
        combined.sort(key=lambda x: x["url"], reverse=True)
        save_topics(combined)
        print(f"{TOPICS_FILE} を更新しました（合計 {len(combined)} 件）。")
    else:
        print("新しい記事はありませんでした。")


if __name__ == "__main__":
    main()
