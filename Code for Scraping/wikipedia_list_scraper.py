"""
Wikipedia List of Films Featuring the Deaf and Hard of Hearing — Scraper
=========================================================================
Fetches the Wikipedia list page, extracts every film row (title, year,
description), resolves each film's Wikipedia article title from its wikilink,
then batch-queries the Wikipedia API for Wikidata IDs.

Output columns:
  Film | Year | Description | Wikipedia Article | Wikipedia URL | Wikidata ID

Requirements:  pip install requests
Output:        Wikipedia–List_of_films_featuring_the_deaf_and_hard_of_hearing.tsv
               (saved in the uploads folder next to this script)
"""

import csv, re, time, sys, os, json
import requests

# ── Configuration ─────────────────────────────────────────────────────────────

LIST_PAGE   = "List_of_films_featuring_the_deaf_and_hard_of_hearing"
API_URL     = "https://en.wikipedia.org/w/api.php"
DELAY       = 0.5   # seconds between API calls
BATCH_SIZE  = 50    # titles per pageprops lookup

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(SCRIPT_DIR, "..", "uploads")
OUTPUT_FILE = os.path.join(
    UPLOADS_DIR,
    "Wikipedia–List_of_films_featuring_the_deaf_and_hard_of_hearing.tsv",
)

HEADERS = {"User-Agent": "DeafFilmResearch/1.0 (research project; python-requests)"}

TSV_COLUMNS = [
    "Film", "Year", "Description",
    "Wikipedia Article", "Wikipedia URL", "Wikidata ID",
]


# ── Step 1: Fetch wikitext and extract film rows ───────────────────────────────

def fetch_wikitext(page_title: str) -> str:
    """Return the raw wikitext of a Wikipedia page."""
    r = requests.get(API_URL, params={
        "action":  "parse",
        "page":    page_title,
        "prop":    "wikitext",
        "format":  "json",
    }, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["parse"]["wikitext"]["*"]


def parse_rows(wikitext: str) -> list[dict]:
    """
    Parse a wikitable and return a list of {Film, Year, Description,
    Wikipedia Article} dicts. Handles wikilinks like:
      [[Film Title]]  or  [[Film Title (film)|Film Title]]
    """
    rows = []

    # Each table row starts with "|-" then has cells starting with "|"
    # We split on row separators and handle multi-line cells.
    # Simplified: split on |- and process each chunk.
    chunks = re.split(r"^\|-", wikitext, flags=re.MULTILINE)

    for chunk in chunks:
        # Extract pipe-separated cells (lines starting with |)
        cells = re.findall(r"^\|(.+)", chunk, flags=re.MULTILINE)
        if len(cells) < 2:
            continue

        # Cell 0: film title (may contain a wikilink)
        raw_title = cells[0].strip().strip("|").strip()

        # Extract wikilink: [[Article|Display]] or [[Article]]
        wl = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", raw_title)
        if wl:
            article   = wl.group(1).strip()   # the actual Wikipedia article title
            display   = (wl.group(2) or wl.group(1)).strip()
        else:
            # No wikilink — use plain text as both display and article guess
            display = re.sub(r"'{2,}", "", raw_title).strip()
            article = display

        # Cell 1: year (plain number)
        year = re.sub(r"[^\d]", "", cells[1].strip())[:4]

        # Cell 2: description (optional)
        desc = ""
        if len(cells) >= 3:
            desc = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", cells[2])
            desc = re.sub(r"'{2,}", "", desc)
            desc = re.sub(r"<[^>]+>", "", desc)
            desc = re.sub(r"\{\{[^}]+\}\}", "", desc)
            desc = re.sub(r"\s+", " ", desc).strip()

        if display:
            rows.append({
                "Film":               display,
                "Year":               year,
                "Description":        desc,
                "Wikipedia Article":  article,
                "Wikipedia URL":      "",
                "Wikidata ID":        "",
            })

    return rows


# ── Step 2: Batch-fetch Wikidata IDs via Wikipedia pageprops API ───────────────

def fetch_wikidata_ids(articles: list[str]) -> dict[str, dict]:
    """
    Given a list of Wikipedia article titles, return a dict mapping
    article title → {"wikidata_id": "Q...", "url": "https://..."}
    Uses batched pageprops queries (50 titles per call).
    """
    results = {}
    chunks = [articles[i:i+BATCH_SIZE] for i in range(0, len(articles), BATCH_SIZE)]

    for ci, chunk in enumerate(chunks, 1):
        print(f"  Pageprops batch {ci}/{len(chunks)}  ({len(chunk)} titles) …")
        params = {
            "action":   "query",
            "prop":     "pageprops|info",
            "ppprop":   "wikibase_item",
            "inprop":   "url",
            "titles":   "|".join(chunk),
            "format":   "json",
            "redirects": "1",
        }
        try:
            r = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [warn] batch {ci} failed: {e}", file=sys.stderr)
            time.sleep(5)
            continue

        pages = data.get("query", {}).get("pages", {})

        # Handle redirects: build a map from original title → resolved title
        redirect_map = {}
        for rd in data.get("query", {}).get("redirects", []):
            redirect_map[rd["from"]] = rd["to"]

        for page in pages.values():
            title     = page.get("title", "")
            qid       = page.get("pageprops", {}).get("wikibase_item", "")
            canon_url = page.get("canonicalurl", "")
            if qid:
                results[title] = {"wikidata_id": qid, "url": canon_url}
                # Also store under any redirect sources
                for src, dst in redirect_map.items():
                    if dst == title:
                        results[src] = {"wikidata_id": qid, "url": canon_url}

        time.sleep(DELAY)

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Wikipedia Deaf Film List Scraper")
    print("=" * 60)

    print(f"\nFetching wikitext for: {LIST_PAGE} …")
    wikitext = fetch_wikitext(LIST_PAGE)
    print(f"  Fetched {len(wikitext):,} characters.")

    print("\nParsing film rows …")
    rows = parse_rows(wikitext)
    print(f"  Found {len(rows)} film entries.")

    # Deduplicate article titles for the API call
    articles = list({r["Wikipedia Article"] for r in rows if r["Wikipedia Article"]})
    print(f"\nFetching Wikidata IDs for {len(articles)} Wikipedia articles …")
    wikidata = fetch_wikidata_ids(articles)
    print(f"  Got Wikidata IDs for {len(wikidata)} articles.")

    # Enrich rows
    matched = 0
    for row in rows:
        art = row["Wikipedia Article"]
        if art in wikidata:
            row["Wikidata ID"]      = wikidata[art]["wikidata_id"]
            row["Wikipedia URL"]    = wikidata[art]["url"]
            matched += 1

    print(f"\nMatched {matched}/{len(rows)} films to a Wikidata ID.")

    # Write output
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TSV_COLUMNS, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ Done! Saved to:\n  {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
