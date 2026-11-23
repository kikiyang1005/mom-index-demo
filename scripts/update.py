"""Build the public snapshot from ETF forum listings; publish aggregates only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from html import unescape
import json
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

from index_calculator import compute_sector_index
from llm_analyzer import analyze_sector

BOARDS = {"nasdaq": "159941", "gold": "518880", "cpo": "515880", "semiconductor": "512480"}


def in_sample_window(timestamp, now):
    start = now - timedelta(hours=24)
    for day in (start, now):
        if timestamp[:5] == day.strftime("%m-%d"):
            hour, minute = map(int, timestamp[6:].split(":"))
            updated = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return start <= updated <= now
    return False


def collect(item, now):
    sector, code = item
    page = subprocess.check_output(
        ["curl", "-fsSL", "--max-time", "25", f"https://guba.eastmoney.com/list,of{code}.html"],
        text=True, encoding="utf-8",
    )
    posts = {}
    for row in re.findall(r'<div class="articleh normal_post[^"]*">(.*?)</div>', page, re.S):
        date = re.search(r'<span class="l5">(\d{2}-\d{2} \d{2}:\d{2})</span>', row)
        link = re.search(r'<a href="(/news,[^"]+)" title="([^"]+)"', row)
        if not date or not link or not in_sample_window(date[1], now):
            continue
        title = unescape(link[2]).strip()
        if len(re.sub(r'\W', '', title)) < 2 or re.fullmatch(r'\$[^$]+\$', title):
            continue
        posts[link[1]] = {"id": link[1], "title": title, "platform": "guba"}
    if not posts:
        raise RuntimeError(f"{sector}: no usable listings updated in the past 24 hours")
    result = compute_sector_index(analyze_sector(list(posts.values()), sector))
    details = result["details"]
    if not details["valid_posts"]:
        raise RuntimeError(f"{sector}: no valid title samples")
    print(f"{sector}: {result['index']} ({details['valid_posts']} titles)")
    return sector, {
        "index": result["index"],
        "details": {key: details[key] for key in ("valid_posts", "newbie_posts", "buy_count", "sell_count")},
    }


def main():
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(second=0, microsecond=0)
    with ThreadPoolExecutor(max_workers=len(BOARDS)) as executor:
        sectors = dict(executor.map(lambda item: collect(item, now), BOARDS.items()))
    output = Path(sys.argv[1])
    output.write_text(json.dumps({
        "latest": {"date": now.date().isoformat(), "sampled_at": now.isoformat(timespec="minutes"), "sectors": sectors}
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
