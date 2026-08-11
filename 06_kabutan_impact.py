# -*- coding: utf-8 -*-
"""
06_kabutan_impact.py
----------------------
株探（s.kabutan.jp）の「特集」カテゴリのニュース一覧から、
「決算プラス・インパクト銘柄」「決算マイナス・インパクト銘柄」の記事だけを
抜き出し、docs/impact.json に蓄積します（Webページ表示用）。

株探の無料枠では直近20件程度しか一覧に出ないため、毎日実行することで
少しずつ蓄積していく想定です（1回で全期間を遡ることはできません）。

使い方：
    python 06_kabutan_impact.py
"""

import re
import os
import json
import requests

CATEGORY_URL = "https://s.kabutan.jp/market_news/?category_org_id=5"  # 特集カテゴリ
IMPACT_FILE = "docs/impact.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# タイトルに含まれていれば対象とみなすキーワード
KEYWORDS = ["決算プラス・インパクト", "決算マイナス・インパクト"]

# <a ... href="...">タイトル</a> を抜き出す（class等の属性がhrefより先にあっても対応）
LINK_PATTERN = re.compile(
    r'<a\b[^>]*\bhref="((?:https?://s\.kabutan\.jp)?/news/n\d+/?)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)


def load_impact() -> list:
    if not os.path.exists(IMPACT_FILE):
        return []
    try:
        with open(IMPACT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_impact(items: list):
    os.makedirs(os.path.dirname(IMPACT_FILE), exist_ok=True)
    with open(IMPACT_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def fetch_impact_links() -> list:
    res = requests.get(CATEGORY_URL, headers=HEADERS, timeout=20)
    res.raise_for_status()
    res.encoding = res.apparent_encoding

    all_links = LINK_PATTERN.findall(res.text)
    print(f"  [診断] status={res.status_code}, 本文長={len(res.text)}")
    print(f"  [診断] LINK_PATTERNで見つかったリンク総数: {len(all_links)}")
    for kw in KEYWORDS:
        idx = res.text.find(kw)
        print(f"  [診断] 「{kw}」: {res.text.count(kw)} 箇所")
        if idx != -1:
            snippet = res.text[max(0, idx - 300):idx + 100]
            print(f"  [診断] 周辺のHTML:\n{snippet}\n  ----")
    if all_links[:3]:
        print(f"  [診断] リンクの例: {all_links[:3]}")

    found = []
    for url, title in all_links:
        if not any(kw in title for kw in KEYWORDS):
            continue
        if url.startswith("/"):
            url = "https://s.kabutan.jp" + url
        kind = "プラス" if "プラス" in title else "マイナス"
        found.append({"title": title.strip(), "url": url, "kind": kind})
    return found


def main():
    print("株探（特集カテゴリ）を確認しています...")
    found = fetch_impact_links()
    print(f"  見つかった対象記事: {len(found)} 件")

    if not found:
        print("  対象記事が見つかりませんでした（ページ構造が変わった可能性があります）。")

    existing = load_impact()
    existing_urls = {item["url"] for item in existing}

    new_items = [item for item in found if item["url"] not in existing_urls]
    print(f"  新規: {len(new_items)} 件")

    if new_items:
        combined = existing + new_items
        # 新しい記事が先頭に来るよう、URL末尾の記事IDで並べ替え（大きいほど新しい）
        combined.sort(key=lambda x: x["url"], reverse=True)
        save_impact(combined)
        print(f"{IMPACT_FILE} を更新しました（合計 {len(combined)} 件）。")
    else:
        print("新しい記事はありませんでした。")


if __name__ == "__main__":
    main()
