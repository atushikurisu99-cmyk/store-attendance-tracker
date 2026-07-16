"""
store-attendance-tracker / scraper (fuzoku.jp版)

fuzoku.jp のエリア一覧ページから、監視対象店舗の
  - 本日の出勤人数
だけを取得する(個人名・年齢などは保持しない)。

【重要な設計】
fuzoku.jp はエリア一覧ページ自体に各店舗の「本日◯人出勤」が
表示されているため、店舗ごとに個別アクセスする必要がなく、
1回のページ取得で監視対象店舗すべての人数が同時に取れる。
これによりリクエスト数を最小化でき、ヘブンネットで起きた
IPブロック(403)のリスクも下げられる。

新人数については、このエリア一覧ページ内に各店舗のキャスト
サムネイルが一部表示されており、「(新人)」のようなラベルが
名前に含まれる場合があるため、それを簡易的にカウントしている。
ただし「直近7日以内」のような正確な入店日判定はできないため、
"現在新人ラベルが付いているキャストの人数"という近似値である点に注意。

負荷対策として:
  - リクエスト自体が1回で済むため、店舗単位のインターバルは不要
  - ブラウザ相当の User-Agent
  - タイムアウト・リトライ(簡易バックオフ)
を組み込んでいる。
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "stores.json"
DATA_DIR = BASE_DIR / "data"
HISTORY_PATH = DATA_DIR / "history.json"
LATEST_PATH = DATA_DIR / "latest.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

SESSION = requests.Session()
SESSION.headers.update(DEFAULT_HEADERS)

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def fetch(url: str) -> str | None:
    """簡易リトライ付きGET。失敗時はNoneを返す。"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            print(f"  GET {url} -> status={resp.status_code} len={len(resp.text)}", file=sys.stderr, flush=True)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 429):
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except requests.RequestException as e:
            print(f"  GET {url} -> exception: {e}", file=sys.stderr, flush=True)
            time.sleep(3 * (attempt + 1))
    return None


def parse_area_listing(html: str) -> dict:
    """
    エリア一覧ページから { fuzoku_slug: {attendance, newface} } を作る。

    出勤人数: href が "/{slug}/schedule/" になっているリンクのテキストから
              「本日N人出勤」の数字を抜き出す。
    新人数(近似値): 同じ店舗のカード内にあるキャスト画像のalt属性のうち
              「新人」を含むものの数をカウントする。
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    schedule_links = soup.select('a[href*="/schedule/"]')
    print(f"  found {len(schedule_links)} schedule links", file=sys.stderr, flush=True)

    for a in schedule_links:
        href = a.get("href", "")
        m = re.search(r"fuzoku\.jp/([a-zA-Z0-9_-]+)/schedule/", href)
        if not m:
            continue
        slug = m.group(1)

        text = a.get_text(strip=True)
        count_m = re.search(r"(\d+)", text)
        attendance = int(count_m.group(1)) if count_m else None

        # 店舗カードの範囲を大まかに推定するため、直近の親要素から
        # 新人ラベル付きの画像を探す(近似値)。
        newface = None
        card = a.find_parent("li") or a.find_parent("div")
        if card:
            imgs = card.find_all("img", alt=True)
            newface = sum(1 for img in imgs if "新人" in img.get("alt", ""))

        result[slug] = {"attendance": attendance, "newface": newface}

    return result


def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    config = load_config()
    stores = config["stores"]
    listing_url = config["area_listing_url"]
    print(f"Loaded {len(stores)} stores: {[s['fuzoku_slug'] for s in stores]}", file=sys.stderr, flush=True)

    html = fetch(listing_url)
    parsed = parse_area_listing(html) if html else {}

    today_str = datetime.now().strftime("%Y-%m-%d")
    history = load_json(HISTORY_PATH, {})
    latest = {}

    for store in stores:
        slug = store["fuzoku_slug"]
        info = parsed.get(slug, {"attendance": None, "newface": None})
        attendance = info["attendance"]
        newface = info["newface"]

        record = {"date": today_str, "attendance": attendance, "newface": newface}
        history.setdefault(slug, [])
        history[slug] = [r for r in history[slug] if r["date"] != today_str]
        history[slug].append(record)

        latest[slug] = {
            "name": store["name"],
            "attendance": attendance,
            "newface": newface,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        print(f"[{slug}] attendance={attendance} newface={newface}", file=sys.stderr, flush=True)

    save_json(HISTORY_PATH, history)
    save_json(LATEST_PATH, latest)


if __name__ == "__main__":
    print(f"Python: {sys.version}", file=sys.stderr, flush=True)
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
