"""
Weekly scraper — no credentials needed.
Reads public pages of YouTube, Instagram and TikTok and updates data/stats.json.
Run automatically via GitHub Actions every Monday at 08:00 UTC.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests not installed — run: pip install requests")
    sys.exit(1)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

STATS_PATH  = Path(__file__).parent.parent / "data" / "stats.json"
REELS_PATH  = Path(__file__).parent.parent / "data" / "reels.json"

REELS_IDS = [
    "PcrtkQqPCqE",
    "jRj3i07ttBk",
    "oks-lDhRnhs",
    "C3Ms5u9SiFs",
    "BhPRFlRiaRM",
    "o4MDKQYXNC8",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def fmt(n: int) -> str:
    """Format a raw integer as '41.6K', '1.2M', etc."""
    if n >= 1_000_000:
        v = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return v + "M"
    if n >= 1_000:
        v = f"{n / 1_000:.1f}".rstrip("0").rstrip(".")
        return v + "K"
    return str(n)


def parse_k(s: str) -> int:
    """Parse '41.6K' / '1.2M' / '+255K' back to an integer."""
    s = s.replace("+", "").strip()
    m = re.match(r"([\d.]+)([KMB]?)", s)
    if not m:
        return 0
    val = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == "K":
        val *= 1_000
    elif suffix == "M":
        val *= 1_000_000
    elif suffix == "B":
        val *= 1_000_000_000
    return int(val)


def get(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  GET {url} -> {e}")
        return None


# ── scrapers ─────────────────────────────────────────────────────────────────

def scrape_youtube(channel_id: str) -> str | None:
    html = get(f"https://www.youtube.com/channel/{channel_id}")
    if not html:
        return None
    # ytInitialData embeds subscriberCountText in a JSON blob
    m = re.search(r'"subscriberCountText":\{"simpleText":"([^"]+)"', html)
    if not m:
        return None
    raw = m.group(1)  # e.g. "41.6K subscribers"
    nm = re.match(r"([\d.,]+)\s*([KMB])?", raw.replace(",", "."))
    if not nm:
        return None
    num = float(nm.group(1))
    suffix = (nm.group(2) or "").upper()
    if suffix == "K":
        return fmt(int(num * 1_000))
    if suffix == "M":
        return fmt(int(num * 1_000_000))
    # no suffix — might be a raw number like "41600"
    return fmt(int(num))


def scrape_instagram(username: str) -> str | None:
    html = get(f"https://www.instagram.com/{username}/")
    if not html:
        return None
    # Meta description: "98.1K Followers, ..."
    m = re.search(r'([\d,.]+[KMBkmb]?)\s+Followers', html, re.IGNORECASE)
    if m:
        return m.group(1)
    # Embedded JSON (older layout)
    m = re.search(r'"edge_followed_by":\{"count":(\d+)\}', html)
    if m:
        return fmt(int(m.group(1)))
    return None


def scrape_video_views(video_id: str) -> str | None:
    for url in [
        f"https://www.youtube.com/shorts/{video_id}",
        f"https://www.youtube.com/watch?v={video_id}",
    ]:
        html = get(url)
        if not html:
            continue
        m = re.search(r'"viewCount":"(\d+)"', html)
        if m:
            return fmt(int(m.group(1)))
    return None


def scrape_tiktok(username: str) -> str | None:
    html = get(f"https://www.tiktok.com/@{username}")
    if not html:
        return None
    # SIGI_STATE / __UNIVERSAL_DATA_FOR_REHYDRATION__ embed stats
    m = re.search(r'"followerCount":(\d+)', html)
    if m:
        return fmt(int(m.group(1)))
    m = re.search(r'"fans":(\d+)', html)
    if m:
        return fmt(int(m.group(1)))
    return None


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    with open(STATS_PATH) as f:
        current = json.load(f)

    print("Scraping YouTube…")
    yt = scrape_youtube("UCqxE5h9WEkE3XuTQhbCsBDw")
    print(f"  -> {yt or 'failed, keeping ' + current['youtube']}")

    print("Scraping Instagram…")
    ig = scrape_instagram("mamiquedices__")
    print(f"  -> {ig or 'failed, keeping ' + current['instagram']}")

    print("Scraping TikTok…")
    tt = scrape_tiktok("mamiquedices_")
    print(f"  -> {tt or 'failed, keeping ' + current['tiktok']}")

    yt = yt or current["youtube"]
    ig = ig or current["instagram"]
    tt = tt or current["tiktok"]

    total = "+" + fmt(parse_k(yt) + parse_k(ig) + parse_k(tt))

    stats = {
        "youtube":   yt,
        "instagram": ig,
        "tiktok":    tt,
        "total":     total,
        "updated":   date.today().isoformat(),
    }

    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"\nstats.json updated: {stats}")

    # ── Reels view counts ────────────────────────────────────────────────────
    with open(REELS_PATH) as f:
        current_reels = json.load(f)

    current_views = {r["id"]: r["views"] for r in current_reels.get("reels", [])}

    reels = []
    for vid in REELS_IDS:
        print(f"Scraping views for {vid}…")
        v = scrape_video_views(vid)
        print(f"  -> {v or 'failed, keeping ' + current_views.get(vid, '–')}")
        reels.append({"id": vid, "views": v or current_views.get(vid, "–")})

    reels_data = {"reels": reels, "updated": date.today().isoformat()}
    with open(REELS_PATH, "w") as f:
        json.dump(reels_data, f, indent=2, ensure_ascii=False)

    print(f"\nreels.json updated")


if __name__ == "__main__":
    main()
