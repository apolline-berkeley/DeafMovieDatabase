"""
Deaf Movie Database Scraper
============================
Scrapes all titles from https://deafmovie.org/titlesfromatoz/ and saves
them to a TSV file with all available details.

Requirements:
    pip install requests beautifulsoup4

Output:
    deafmovie_titles.tsv  (saved in the same folder as this script)
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import sys
import os
import re

# ── Configuration ────────────────────────────────────────────────────────────

BASE_URL   = "https://deafmovie.org"
LIST_BASE  = f"{BASE_URL}/titlesfromatoz/"
NUM_PAGES  = 13
DELAY      = 1.0   # seconds between requests (be polite)
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "deafmovie_titles.tsv")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

TSV_COLUMNS = [
    "Title", "Duration", "Genre", "Release Date",
    "Category", "Deaf Actor", "Deaf Director", "Deaf Writer", "Deaf Editor",
    "Language", "Country", "Sign Language %", "Company",
    "Free To Watch", "IMDb ID", "Synopsis", "URL",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch(url, retries=3):
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            wait = attempt * 2
            print(f"  [attempt {attempt}/{retries}] {e} — retrying in {wait}s…",
                  file=sys.stderr)
            time.sleep(wait)
    print(f"  ✗ Failed to fetch {url}", file=sys.stderr)
    return None


def links_text(li_tag) -> str:
    """Return semicolon-joined text of all <a> tags inside a <li>."""
    return "; ".join(a.get_text(strip=True) for a in li_tag.find_all("a"))


# ── Step 1: Collect all detail-page URLs ─────────────────────────────────────

def collect_urls():
    """Scrape all 13 listing pages and return every unique /title/ URL."""
    all_urls: list[str] = []
    seen: set[str] = set()

    for page in range(1, NUM_PAGES + 1):
        url = LIST_BASE if page == 1 else f"{LIST_BASE}page/{page}/"
        print(f"Listing page {page}/{NUM_PAGES}: {url}")
        soup = fetch(url)
        if soup is None:
            continue

        for a in soup.select("a[href*='/title/']"):
            href = a["href"].rstrip("/") + "/"
            if href.startswith(f"{BASE_URL}/title/") and href not in seen:
                seen.add(href)
                all_urls.append(href)

        time.sleep(DELAY)

    print(f"\nFound {len(all_urls)} unique title URLs.\n")
    return all_urls


# ── Step 2: Parse a single detail page ───────────────────────────────────────

# Maps the label text on the page → our TSV column name.
# Order matters: longer/more-specific labels must come before shorter ones
# so "Deaf Director" is checked before "Deaf" alone, etc.
FIELD_LABELS = {
    "Genre":           "Genre",
    "Release":         "Release Date",
    "Category":        "Category",
    "Deaf Actor":      "Deaf Actor",
    "Deaf Director":   "Deaf Director",
    "Deaf Writer":     "Deaf Writer",
    "Deaf Editor":     "Deaf Editor",
    "Language":        "Language",
    "Country":         "Country",
    "Sign Language %": "Sign Language %",
    "Company":         "Company",
    "Free To Watch":   "Free To Watch",
}

DUR_RE = re.compile(
    r"\b(\d{1,2}\s*hours?\s*\d{0,2}\s*minutes?|\d+\s*minutes?|\d+\s*mins?)\b",
    re.IGNORECASE,
)


def is_in_nav(tag) -> bool:
    """Return True if this tag lives inside a navigation or header element."""
    for parent in tag.parents:
        if parent.name in ("nav", "header"):
            return True
        classes = parent.get("class") or []
        if any("nav" in c.lower() or "menu" in c.lower() for c in classes):
            return True
    return False


def parse_detail(url: str, soup: BeautifulSoup) -> dict:
    row = {col: "" for col in TSV_COLUMNS}
    row["URL"] = url

    # Title — prefer the entry-title h1 (WordPress standard class), then
    # fall back to the og:title meta tag so we always get something.
    h1 = (
        soup.find("h1", class_=re.compile(r"entry-title", re.I))
        or soup.find("h1", class_=re.compile(r"post-title",  re.I))
    )
    if h1:
        row["Title"] = h1.get_text(strip=True)
    else:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            # Strip the site suffix "- DEAF MOVIE DATABASE"
            t = og_title.get("content", "").strip()
            row["Title"] = re.sub(r"\s*[-–|]\s*DEAF MOVIE DATABASE\s*$", "", t, flags=re.I)

    # Duration — search the whole body for a time-like string
    body_text = soup.body.get_text(" ") if soup.body else ""
    m = DUR_RE.search(body_text)
    if m:
        row["Duration"] = m.group(1).strip()

    # Structured fields inside <li> elements.
    # We search the ENTIRE page but skip any <li> that lives inside a nav or
    # header element — this prevents navigation links like
    # <li><a href="/deaf-actor/">Deaf Actor</a></li> from polluting data fields.
    for li in soup.find_all("li"):
        if is_in_nav(li):
            continue
        raw = li.get_text(" ", strip=True)
        for label, col in FIELD_LABELS.items():
            if raw.startswith(label):
                val = links_text(li)
                if not val:
                    # Fall back to plain text after the label
                    val = raw[len(label):].lstrip(":").strip()
                # Guard: if the value equals the label exactly, it's a stray
                # nav/category link, not a real data value — skip it.
                if val.lower().strip() == label.lower().strip():
                    break
                row[col] = val
                break

    # IMDb ID — from the IMDb logo link at the bottom of each page
    for a in soup.find_all("a", href=re.compile(r"imdb\.com/title/tt\d+")):
        m = re.search(r"tt\d+", a["href"])
        if m:
            row["IMDb ID"] = m.group(0)
            break

    # Synopsis — paragraph after the "Synopsis" heading, or og:description
    syn_heading = soup.find(
        ["h2", "h3"],
        string=re.compile(r"synopsis", re.I),
    )
    if syn_heading:
        p = syn_heading.find_next_sibling("p") or syn_heading.find_next("p")
        if p:
            row["Synopsis"] = p.get_text(strip=True)
    if not row["Synopsis"]:
        og = soup.find("meta", property="og:description")
        if og:
            row["Synopsis"] = og.get("content", "").strip()

    return row


# ── Step 3: Main scrape loop ──────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Deaf Movie Database Scraper")
    print("=" * 60)

    # -- Collect URLs from listing pages
    urls = collect_urls()

    # -- Open TSV for writing
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TSV_COLUMNS, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()

        total = len(urls)
        for i, url in enumerate(urls, start=1):
            print(f"[{i}/{total}] {url}")
            soup = fetch(url)
            if soup is None:
                # Write a placeholder row so we know it was attempted
                writer.writerow({"Title": "FETCH_ERROR", "URL": url})
                fh.flush()
                time.sleep(DELAY)
                continue

            row = parse_detail(url, soup)
            writer.writerow(row)
            fh.flush()   # save progress after every row

            time.sleep(DELAY)

    print(f"\n✓ Done! {total} titles saved to:\n  {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
