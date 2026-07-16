"""
store-attendance-tracker / scraper

シティヘブンネットの店舗ページから
  - 本日の出勤人数
  - 直近7日以内の新人登録人数
だけを取得する(個人名・年齢などは保持しない)。

【重要な注意】
このコードはトップページに表示される「週間出勤予定」のHTML構造を元に
組んでいるが、実際に /attend/ 専用ページへアクセスして初めて
確定するセレクタもある。最初の疎通確認(elegance 1店舗)で
実際のレスポンスを見ながら CSS セレクタ / 抽出ロジックを調整すること。

負荷対策として:
  - 店舗ごとに 1〜2秒のランダムインターバル
  - 店舗の処理順序をシャッフル
  - ブラウザ相当の User-Agent
  - タイムアウト・リトライ(簡易バックオフ)
を組み込んでいる。
"""

import json
import random
import time
import re
import sys
from datetime import datetime, timedelta
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

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3


def load_stores():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)["stores"]


def fetch(url: str) -> str | None:
    """簡易リトライ付きGET。失敗時はNoneを返す(その店舗はスキップ)。"""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"}
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            print(f"  GET {url} -> status={resp.status_code} len={len(resp.text)}", file=sys.stderr)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 429):
                # 弾かれた可能性。バックオフして再試行。
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except requests.RequestException as e:
            print(f"  GET {url} -> exception: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return None


def count_today_attendance(html: str) -> int | None:
    """
    「週間出勤予定」の本日列にあたるブロックから人数をカウントする。
    TODO: /attend/ ページの実際のDOM構造を見て、本日列を確実に
    特定するセレクタに差し替える(現状はトップページの1列目=本日、という仮定)。
    """
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    # キャストの個別プロフィールへのリンク(girlid-xxxxx)の出現数を
    # 「出勤人数」の近似値として使う。本日列だけに絞るのは要調整。
    today_links = soup.select('a[href*="/girlid-"]')
    # 重複(同じキャストが複数リンクで出る場合)を除去
    unique_ids = set()
    for a in today_links:
        m = re.search(r"/girlid-(\d+)/", a.get("href", ""))
        if m:
            unique_ids.add(m.group(1))
    print(f"    -> found {len(today_links)} girlid links, {len(unique_ids)} unique", file=sys.stderr)
    return len(unique_ids) if unique_ids else None


def count_recent_newface(html: str, days: int = 7) -> int | None:
    """
    新人一覧(例: 7/9入店 のような表記)から、直近days日以内に
    入店した人数をカウントする。
    """
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")

    today = datetime.now()
    count = 0
    for m in re.finditer(r"(\d{1,2})/(\d{1,2})\s*入店", text):
        month, day = int(m.group(1)), int(m.group(2))
        try:
            entry_date = datetime(today.year, month, day)
        except ValueError:
            continue
        # 年またぎ(1月に前年12月分の表記が出る等)を簡易補正
        if entry_date > today + timedelta(days=1):
            entry_date = entry_date.replace(year=today.year - 1)
        if 0 <= (today - entry_date).days <= days:
            count += 1
    return count


def build_store_urls(store: dict) -> tuple[str, str]:
    base = f"https://www.cityheaven.net/{store['area']}/{store['slug']}/"
    attend_url = base  # TODO: 実測後、必要なら base + "attend/" に変更
    newface_url = base + "girllist/newface/"
    return attend_url, newface_url


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
    stores = load_stores()
    random.shuffle(stores)  # アクセス順序をランダム化

    today_str = datetime.now().strftime("%Y-%m-%d")
    history = load_json(HISTORY_PATH, {})  # { slug: [ {date, attendance, newface}, ... ] }
    latest = {}

    for store in stores:
        slug = store["slug"]
        attend_url, newface_url = build_store_urls(store)

        html_attend = fetch(attend_url)
        time.sleep(random.uniform(1, 2))  # 店舗内の2ページ取得の間にも間隔を空ける
        html_newface = fetch(newface_url)

        attendance = count_today_attendance(html_attend)
        newface = count_recent_newface(html_newface)

        record = {"date": today_str, "attendance": attendance, "newface": newface}
        history.setdefault(slug, [])
        # 同日分がすでにあれば上書き(1日3回実行のうち最新を反映)
        history[slug] = [r for r in history[slug] if r["date"] != today_str]
        history[slug].append(record)

        latest[slug] = {
            "name": store["name"],
            "attendance": attendance,
            "newface": newface,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        print(f"[{slug}] attendance={attendance} newface={newface}", file=sys.stderr)

        # 次の店舗までランダムインターバル(1〜2秒)
        time.sleep(random.uniform(1, 2))

    save_json(HISTORY_PATH, history)
    save_json(LATEST_PATH, latest)


if __name__ == "__main__":
    main()
