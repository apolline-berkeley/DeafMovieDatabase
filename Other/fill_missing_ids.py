"""
Deaf Film Database — IMDb ID & Wikidata ID Filler
==================================================
Fills empty "IMDb ID" and "Wikidata ID" cells in the master database TSV.

HOW IT READS EACH CELL:
  – (em dash)  = user manually verified not found → SKIP, never overwrite
  empty string = not yet looked up              → attempt lookup
  tt1234567    = valid IMDb ID, already filled  → skip IMDb lookup
  Q12345       = valid Wikidata ID, already filled → skip Wikidata lookup

LOOKUP STRATEGY (four passes):

  Pass 1 — Rows that HAVE a Wikidata ID but missing IMDb ID
            Quick reverse lookup: wd:QXXXXX → wdt:P345 (IMDb title ID)
            One batch query for all such rows.

  Pass 2 — Rows that HAVE an IMDb ID but missing Wikidata ID
            Proven batch SPARQL: wdt:P345 → Wikidata item + Wikipedia link
            Up to IMDB_BATCH rows per query.

  Pass 3 — Rows missing BOTH: search Wikidata by title + year
            Individual SPARQL per film using rdfs:label + P31 film-type filter.
            If found: fills IMDb ID (from Wikidata's P345) + Wikidata ID.
            Limitation: only finds films that have a Wikidata entry.

  Pass 4 — Fallback for rows still missing IMDb ID after Pass 3
            Queries IMDb's own suggestion/autocomplete JSON endpoint directly.
            This is the same API IMDb's search bar uses — no key required,
            returns structured JSON (not HTML scraping).
            Finds IMDb IDs even for films with NO Wikidata entry at all.
            Does NOT fill Wikidata ID (run the script again after this pass
            to fill Wikidata for any newly found IMDb IDs via Pass 2).

IMPORTANT — IMDb ID format:
  Only tt... IDs are accepted (film/title IDs).
  nm... (people) and co... (companies) are rejected at both the SPARQL
  level (FILTER clause) and in Python, so incorrect IDs cannot be stored.

OUTPUT:
  Adds / updates columns:  IMDb ID,  Wikidata ID,  Wikipedia URL
  Adds new column:         Lookup Notes  (explains every outcome)

CONFIGURATION — edit the values in the block just below this docstring.
"""

import csv
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import requests

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — safe to edit
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))

# Input file — the master database produced by Database_merger.py
INPUT_FILE  = os.path.join(SCRIPT_DIR, "..", "Master-Database.tsv")

# Output file — overwrites the master database with IDs filled in
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "Master-Database.tsv")

SENTINEL      = "–"   # em dash — the "manually verified: not found" marker
IMDB_BATCH    = 200   # rows per IMDb-batch SPARQL query (Pass 2)
TITLE_DELAY   = 5     # seconds to wait between Pass 3 title queries
SPARQL_TIMEOUT = 60   # seconds before a SPARQL request is considered timed out

# ══════════════════════════════════════════════════════════════════════════════


SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "DeafFilmResearch/2.0 (research; python-requests)",
    "Accept": "application/sparql-results+json",
}


# ──────────────────────────────────────────────────────────────────────────────
# VALUE CLASSIFICATION HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def is_sentinel(val: str) -> bool:
    """True when the user has marked this cell as 'manually verified not found'."""
    return val.strip() == SENTINEL

def is_valid_imdb(val: str) -> bool:
    return bool(re.match(r"^tt\d+$", val.strip()))

def is_valid_wikidata(val: str) -> bool:
    return bool(re.match(r"^Q\d+$", val.strip()))

def needs_lookup(val: str) -> bool:
    """True when the cell is empty — i.e. not yet tried."""
    return not val.strip()


# ──────────────────────────────────────────────────────────────────────────────
# SPARQL HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def sparql_str(s: str) -> str:
    """Escape a value for use inside a SPARQL double-quoted string literal."""
    s = str(s)
    s = s.replace("\\", "\\\\")
    s = s.replace('"',  '\\"')
    s = s.replace("\n", " ").replace("\r", " ")
    return s

def run_sparql(query: str, retries: int = 4) -> list:
    """
    Execute a SPARQL query against Wikidata.
    Returns a list of result bindings, or [] on failure.
    """
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                SPARQL_URL,
                params={"query": query, "format": "json"},
                headers=HEADERS,
                timeout=SPARQL_TIMEOUT,
            )
            if resp.status_code == 429:
                wait = 40 * attempt
                print(f"    [429 rate-limit] waiting {wait}s …", file=sys.stderr)
                time.sleep(wait)
                continue
            if resp.status_code in (400, 500):
                # Bad query or server error — no point retrying
                print(f"    [HTTP {resp.status_code}] bad query — skipping this lookup.",
                      file=sys.stderr)
                return []
            if not resp.ok:
                print(f"    [HTTP {resp.status_code}] attempt {attempt}/{retries}", file=sys.stderr)
                time.sleep(10 * attempt)
                continue
            return resp.json().get("results", {}).get("bindings", [])
        except requests.exceptions.Timeout:
            wait = 20 * attempt
            print(f"    [timeout] attempt {attempt}/{retries} — waiting {wait}s …",
                  file=sys.stderr)
            time.sleep(wait)
        except Exception as exc:
            wait = 10 * attempt
            print(f"    [error] {exc} — waiting {wait}s …", file=sys.stderr)
            time.sleep(wait)
    return []

def make_wp_url(title: str) -> str:
    if not title:
        return ""
    return "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")


# ──────────────────────────────────────────────────────────────────────────────
# PASS 1 — Wikidata ID → IMDb ID  (reverse lookup for rows with QID but no tt)
# ──────────────────────────────────────────────────────────────────────────────

def pass1_qid_to_imdb(qids: list) -> dict:
    """
    Given a list of Wikidata QIDs, return {qid: imdb_id}.
    Uses a single batch query.
    Only returns tt... IDs (film/title IDs). nm... (people) and co... (companies)
    are explicitly filtered out both in SPARQL and in Python.
    """
    print(f"  [Pass 1] Reverse lookup: {len(qids)} Wikidata IDs → IMDb IDs …")
    values = " ".join(f"wd:{q}" for q in qids)
    query = f"""
SELECT ?item ?imdb WHERE {{
  VALUES ?item {{ {values} }}
  ?item wdt:P345 ?imdb .
  FILTER(STRSTARTS(STR(?imdb), "tt"))
}}"""
    results = {}
    for b in run_sparql(query):
        qid  = b["item"]["value"].split("/")[-1]
        imdb = b.get("imdb", {}).get("value", "")
        # Python-side safety net: only accept tt... IDs
        if imdb and re.match(r"^tt\d+$", imdb) and qid not in results:
            results[qid] = imdb
    time.sleep(3)
    print(f"  → matched {len(results)} QIDs to IMDb title IDs")
    return results


# ──────────────────────────────────────────────────────────────────────────────
# PASS 2 — IMDb ID → Wikidata ID + Wikipedia URL  (batch, proven reliable)
# ──────────────────────────────────────────────────────────────────────────────

def pass2_imdb_to_wikidata(imdb_ids: list) -> dict:
    """
    Given a list of IMDb IDs, return {imdb_id: {"qid": "Q...", "wp": "https://..."}}.
    """
    results = {}
    chunks  = [imdb_ids[i:i+IMDB_BATCH] for i in range(0, len(imdb_ids), IMDB_BATCH)]
    for ci, chunk in enumerate(chunks, 1):
        print(f"  [Pass 2] IMDb batch {ci}/{len(chunks)} ({len(chunk)} IDs) …")
        values = " ".join(f'"{x}"' for x in chunk)
        query  = f"""
SELECT ?item ?imdb ?wpTitle WHERE {{
  VALUES ?imdb {{ {values} }}
  ?item wdt:P345 ?imdb .
  OPTIONAL {{
    ?wp schema:about ?item ;
        schema:isPartOf <https://en.wikipedia.org/> ;
        schema:name ?wpTitle .
  }}
}}"""
        for b in run_sparql(query):
            iid = b["imdb"]["value"]
            qid = b["item"]["value"].split("/")[-1]
            wpt = b.get("wpTitle", {}).get("value", "")
            if iid not in results:
                results[iid] = {"qid": qid, "wp": make_wp_url(wpt)}
            elif not results[iid]["wp"] and wpt:
                results[iid]["wp"] = make_wp_url(wpt)
        time.sleep(3)
    print(f"  → matched {len(results)} IMDb IDs in Wikidata")
    return results


# ──────────────────────────────────────────────────────────────────────────────
# PASS 3 — Title + year → IMDb ID + Wikidata ID  (individual queries)
# ──────────────────────────────────────────────────────────────────────────────

# Wikidata "instance of" (P31) values that represent film types.
# Items that don't match at least one of these are silently ignored — this
# prevents Wikidata junk entries (people, albums, books, etc. with the same
# title) from being returned.
#
# Add more QIDs here if you find film types that are being missed.
FILM_TYPES = [
    "wd:Q11424",    # film (general)
    "wd:Q24862",    # short film
    "wd:Q506240",   # television film (TV movie)
    "wd:Q229390",   # documentary film
    "wd:Q1259759",  # animated film
    "wd:Q202866",   # animated short film
    "wd:Q7378303",  # short documentary film
    "wd:Q93204",    # television special
    "wd:Q1261214",  # animated television film
    "wd:Q63952888", # animated documentary film
    "wd:Q20443052", # documentary short film
    "wd:Q592002",   # silent film
    "wd:Q226730",   # experimental film
    "wd:Q15398782", # film series (rarely needed, but safe to include)
]

def _wikidata_label_query(label: str, film_type_values: str) -> list:
    """Run a Wikidata label search for a single title string. Returns raw bindings."""
    query = f"""
SELECT DISTINCT ?item ?imdb ?wpTitle ?releaseYear WHERE {{
  VALUES ?filmType {{
    {film_type_values}
  }}
  ?item wdt:P31 ?filmType .
  ?item rdfs:label "{sparql_str(label)}"@en .
  OPTIONAL {{
    ?item wdt:P345 ?imdb .
    FILTER(STRSTARTS(STR(?imdb), "tt"))
  }}
  OPTIONAL {{
    ?item wdt:P577 ?releaseDate .
    BIND(STR(YEAR(?releaseDate)) AS ?releaseYear)
  }}
  OPTIONAL {{
    ?wp schema:about ?item ;
        schema:isPartOf <https://en.wikipedia.org/> ;
        schema:name ?wpTitle .
  }}
}}
LIMIT 10"""
    return run_sparql(query)


def pass3_title_year(title: str, year: str, original_title: str = "") -> tuple:
    """
    Search Wikidata for a FILM matching the English label and optional year.
    Uses wdt:P31 (instance of) to filter results to known film types only.

    If the English title finds nothing, automatically retries with the
    Original Title (useful when the original-language title is what Wikidata
    uses as its English label, e.g. 'Abang Adik', 'Stalker', etc.)

    Returns:
        (imdb_id, qid, wp_url, note_string)

    DIAGNOSIS TIPS:
    - "no film-type item with English label" → film may be absent from Wikidata,
      use a different title there, or have an unlisted P31 type (add it above)
    - "year mismatch"    → Wikidata release year differs; result returned but flagged
    - "N candidates"     → multiple films share the title; best match taken
    - "timeout"          → Wikidata was slow; re-run to retry
    """
    if not title:
        return "", "", "", "Skipped: no title in this row"

    film_type_values = "\n    ".join(FILM_TYPES)

    # Try English/display title first
    bindings   = _wikidata_label_query(title, film_type_values)
    used_title = title

    # Fallback: try Original Title if it differs and English title found nothing
    if not bindings and original_title and original_title.strip() != title.strip():
        time.sleep(1)
        bindings   = _wikidata_label_query(original_title.strip(), film_type_values)
        used_title = original_title.strip()

    if not bindings:
        tried = f"'{title}'"
        if original_title and original_title.strip() != title.strip():
            tried += f" and original title '{original_title.strip()}'"
        return "", "", "", (
            f"Not found in Wikidata: searched {tried} — "
            f"film may be absent, use a different title there, or have an unlisted P31 type"
        )

    # ── Year filtering ────────────────────────────────────────────────────────
    year_str  = str(year).strip()
    year_note = ""
    if year_str:
        year_matches = [
            b for b in bindings
            if b.get("releaseYear", {}).get("value", "")[:4] == year_str
        ]
        if year_matches:
            bindings = year_matches
        else:
            found_years = sorted({
                b.get("releaseYear", {}).get("value", "")[:4]
                for b in bindings
            })
            year_note = (
                f"; year mismatch: TSV says {year_str}, "
                f"Wikidata has {', '.join(y for y in found_years if y) or 'no year'}"
            )

    # ── Candidate selection ───────────────────────────────────────────────────
    # Prefer a candidate that already has a valid tt... IMDb ID attached.
    # Python-side safety net: re-check that the value is tt... even though
    # the SPARQL FILTER already enforces this. nm... (people) and co...
    # (companies) must never be stored as a film's IMDb ID.
    with_imdb = [
        b for b in bindings
        if re.match(r"^tt\d+$", b.get("imdb", {}).get("value", ""))
    ]
    best = with_imdb[0] if with_imdb else bindings[0]

    qid  = best["item"]["value"].split("/")[-1]
    imdb = best.get("imdb", {}).get("value", "")
    # Final guard — if somehow a non-tt value slipped through, discard it
    if not re.match(r"^tt\d+$", imdb):
        imdb = ""
    wpt  = best.get("wpTitle", {}).get("value", "")
    wp   = make_wp_url(wpt)

    multi_note = ""
    if len(bindings) > 1:
        all_qids = ", ".join(b["item"]["value"].split("/")[-1] for b in bindings)
        multi_note = (
            f"; {len(bindings)} film candidates ({all_qids}) — "
            f"took best match, verify manually if wrong"
        )

    orig_note = f" [searched as '{used_title}']" if used_title != title else ""
    note = f"Found via title SPARQL (Pass 3){orig_note}{year_note}{multi_note}"
    return imdb, qid, wp, note


# ──────────────────────────────────────────────────────────────────────────────
# PASS 4 — IMDb suggestion API fallback (for films with no Wikidata entry)
# ──────────────────────────────────────────────────────────────────────────────

IMDB_SUGGESTION_URL = "https://v3.sg.media-imdb.com/suggestion/{first}/{query}.json"
IMDB_DELAY = 2   # seconds between IMDb suggestion API calls (be polite)

# Minimum Jaccard word-overlap between the searched title and a returned title
# for the result to be accepted. 1.0 = exact word match, 0.0 = no overlap.
# "Birmingham Made Me" vs "Birmingham Massive" scores 0.25 → rejected.
# "Fuzz" vs "Fuzz" scores 1.0 → accepted.
# Lower this value if valid films are being missed; raise it to reduce false positives.
TITLE_MATCH_THRESHOLD = 0.5

def title_jaccard(a: str, b: str) -> float:
    """
    Jaccard similarity of word sets between two titles.
    Strips punctuation, lowercases, and removes leading articles (the/a/an).
    Returns a float from 0.0 (no shared words) to 1.0 (identical word sets).
    """
    def word_set(s):
        s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
        s = s.lower()
        s = re.sub(r"[^\w\s]", "", s)
        s = re.sub(r"^(the|a|an)\s+", "", s.strip())
        return set(s.split())
    wa, wb = word_set(a), word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)

# Prints full IMDb API response details for every Pass 4 lookup.
# Leave True so you can paste the terminal output for diagnosis.
# Set to False once everything is working to reduce noise.
IMDB_VERBOSE = True

def _imdb_suggestion_search(search_title: str, year: str) -> tuple:
    """
    Core IMDb suggestion API call for a single title string.
    Returns (candidates_after_tt_filter, all_results, raw_url, error_note).
    'error_note' is non-empty if the search failed entirely.
    """
    first = urllib.parse.quote(search_title[0].lower())
    query = urllib.parse.quote(search_title.lower())
    url   = IMDB_SUGGESTION_URL.format(first=first, query=query)

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=15,
        )
        if IMDB_VERBOSE:
            print(f"\n    [IMDB DEBUG] search_title={search_title!r}  year={year!r}")
            print(f"    [IMDB DEBUG] URL: {url}")
            print(f"    [IMDB DEBUG] HTTP status: {resp.status_code}")
        if not resp.ok:
            if IMDB_VERBOSE:
                print(f"    [IMDB DEBUG] response body: {resp.text[:300]}")
            return [], [], url, f"IMDb suggestion API HTTP {resp.status_code}"
        data = resp.json()
        if IMDB_VERBOSE:
            print(f"    [IMDB DEBUG] raw JSON: {resp.text}")
    except Exception as exc:
        if IMDB_VERBOSE:
            print(f"    [IMDB DEBUG] exception: {exc}")
        return [], [], url, f"IMDb suggestion API error: {exc}"

    all_results = data.get("d", [])
    if IMDB_VERBOSE:
        print(f"    [IMDB DEBUG] {len(all_results)} total result(s):")
        for r in all_results:
            print(f"      id={r.get('id','?')}  label={r.get('l','?')!r}"
                  f"  year={r.get('y','?')}  q={r.get('q','?')!r}"
                  f"  qid={r.get('qid','?')!r}  all_keys={list(r.keys())}")

    tt_candidates = [
        item for item in all_results
        if re.match(r"^tt\d+$", item.get("id", ""))
    ]
    return tt_candidates, all_results, url, ""


def pass4_imdb_suggestion(title: str, year: str, original_title: str = "") -> tuple:
    """
    Query IMDb's own suggestion/autocomplete JSON endpoint to find a tt... ID.

    This is the same JSON API IMDb's search bar uses — no HTML scraping,
    no API key required. Finds films that exist ONLY on IMDb with no Wikidata.

    HOW FILTERING WORKS:
      - Only tt... IDs are accepted. This alone excludes people (nm...) and
        companies (co...) — we do NOT filter by a "type" field because the
        IMDb API uses different field names/values across versions and any
        type-based filter risks silently dropping valid results.
      - Year matching narrows the list when the year is known.
      - If multiple tt... candidates remain, we take the top-ranked one
        (IMDb orders by popularity) and flag it for manual review.

    Returns:
        (imdb_id, note_string)
        imdb_id is "" if nothing suitable was found.

    DIAGNOSIS TIPS:
    - "no tt... results"    → API returned results, but all had nm.../co... IDs
                              (e.g. only a person with that name on IMDb, no film)
    - "empty response"      → IMDb returned no suggestions at all for this title;
                              the film may use a different title on IMDb
    - "year mismatch"       → found a tt... entry but year differs; result is
                              still returned and flagged — check manually
    - "multiple candidates" → more than one film matched; best taken by popularity
    - Set IMDB_VERBOSE=True above to print raw API responses for debugging
    """
    if not title:
        return "", "Skipped: no title"

    used_title = title

    # ── Search with display/English title ─────────────────────────────────────
    tt_candidates, all_results, _, err = _imdb_suggestion_search(title, year)

    if err:
        return "", err

    # ── If no tt... results, try Original Title as fallback ───────────────────
    if not tt_candidates and original_title and original_title.strip() != title.strip():
        if IMDB_VERBOSE:
            print(f"    [IMDB DEBUG] No tt... results for display title — "
                  f"retrying with original title {original_title.strip()!r}")
        time.sleep(IMDB_DELAY)
        tt_candidates, all_results, _, err2 = _imdb_suggestion_search(
            original_title.strip(), year
        )
        if tt_candidates:
            used_title = original_title.strip()
        elif err2:
            return "", err2

    if not tt_candidates:
        if all_results:
            non_tt = [r.get("id", "?") for r in all_results]
            return "", (
                f"Not found: IMDb returned result(s) but none had a tt... ID "
                f"(found: {', '.join(non_tt[:5])})"
            )
        tried = f"'{title}'"
        if original_title and original_title.strip() != title.strip():
            tried += f" and '{original_title.strip()}'"
        return "", f"Not found: IMDb returned no suggestions for {tried}"

    if IMDB_VERBOSE:
        print(f"    [IMDB DEBUG] after tt... filter: {len(tt_candidates)} candidate(s): "
              f"{[c.get('id') for c in tt_candidates]}")

    # ── Step 2: title similarity filter ───────────────────────────────────────
    # Reject results whose title doesn't resemble what we searched for.
    # This prevents "Birmingham Massive" being accepted when we searched
    # "Birmingham Made Me" just because it was the top IMDb suggestion.
    scored = [
        (title_jaccard(title, c.get("l", "")), c)
        for c in tt_candidates
    ]
    if IMDB_VERBOSE:
        for score, c in scored:
            print(f"    [IMDB DEBUG] title similarity {score:.2f}: "
                  f"{c.get('id')} {c.get('l','?')!r}")

    title_matches = [(s, c) for s, c in scored if s >= TITLE_MATCH_THRESHOLD]

    if not title_matches:
        rejected = ", ".join(
            f"{c.get('id')} {c.get('l','?')!r} (sim={s:.2f})"
            for s, c in sorted(scored, reverse=True)[:3]
        )
        return "", (
            f"Not found: IMDb results didn't match title closely enough "
            f"(threshold={TITLE_MATCH_THRESHOLD}) — closest were: {rejected}"
        )

    # Sort by similarity descending so the best title match comes first
    title_matches.sort(key=lambda x: x[0], reverse=True)
    candidates = [c for _, c in title_matches]

    # ── Step 3: year filter ───────────────────────────────────────────────────
    year_str  = str(year).strip()
    year_note = ""
    if year_str:
        year_matches = [c for c in candidates if str(c.get("y", "")) == year_str]
        if IMDB_VERBOSE:
            print(f"    [IMDB DEBUG] after year filter ({year_str}): "
                  f"{len(year_matches)} match(es): {[c.get('id') for c in year_matches]}")
        if year_matches:
            candidates = year_matches
        else:
            # Title matched but year didn't — still return but flag clearly.
            # We do NOT fall back to results that failed title similarity.
            found_years = sorted({str(c.get("y", "?")) for c in candidates})
            year_note = (
                f"; year mismatch: TSV says {year_str}, "
                f"IMDb has {', '.join(found_years)} — verify this is the correct entry"
            )

    # ── Step 4: final selection ───────────────────────────────────────────────
    best = candidates[0]

    if IMDB_VERBOSE:
        print(f"    [IMDB DEBUG] selected: {best.get('id')} "
              f"({best.get('l','?')!r}, {best.get('y','?')})")

    multi_note = ""
    if len(candidates) > 1:
        all_ids = ", ".join(
            f"{c['id']} ({c.get('l','?')} {c.get('y','')})" for c in candidates
        )
        multi_note = (
            f"; {len(candidates)} title-matching candidates: {all_ids} — "
            f"took best match, verify manually if wrong"
        )

    orig_note = f" [searched as '{used_title}']" if used_title != title else ""
    note = f"IMDb ID found via IMDb suggestion API (Pass 4){orig_note}{year_note}{multi_note}"
    return best["id"], note


# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# SAVE HELPER — called after each pass so a crash never loses progress
# ──────────────────────────────────────────────────────────────────────────────

def _save(rows, cols, label=""):
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ Progress saved {label}: {OUTPUT_FILE}")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Deaf Film DB — IMDb + Wikidata ID Filler")
    print("=" * 60 + "\n")
    print(f"Input:  {INPUT_FILE}")
    print(f"Output: {OUTPUT_FILE}\n")

    # ── Load ──────────────────────────────────────────────────────────────────
    with open(INPUT_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    print(f"Loaded {len(rows)} rows.\n")

    # Add new columns if not present
    existing_cols = list(rows[0].keys()) if rows else []
    for col in ("IMDb URL (auto)", "Lookup Notes (auto)"):
        if col not in existing_cols:
            existing_cols.append(col)
    for row in rows:
        row.setdefault("IMDb URL (auto)", "")
        row.setdefault("Lookup Notes (auto)", "")

    # ── Classify rows ─────────────────────────────────────────────────────────
    # Lists of row indices for each pass
    pass1_rows = []  # have Wikidata ID, missing IMDb ID
    pass2_rows = []  # have IMDb ID, missing Wikidata ID
    pass3_rows = []  # missing both

    counts = {"complete": 0, "sentinel_only": 0}

    for i, row in enumerate(rows):
        imdb = row.get("IMDb ID (auto)", "").strip()
        wiki = row.get("Wikidata ID (auto)", "").strip()

        imdb_s = is_sentinel(imdb)
        wiki_s = is_sentinel(wiki)
        imdb_v = is_valid_imdb(imdb)
        wiki_v = is_valid_wikidata(wiki)

        # Build a base note from any existing sentinels
        sentinel_parts = []
        if imdb_s:
            sentinel_parts.append("IMDb ID: manually verified not found (–)")
        if wiki_s:
            sentinel_parts.append("Wikidata ID: manually verified not found (–)")

        # Does the row still need any lookups?
        need_imdb = needs_lookup(imdb) and not imdb_s
        need_wiki = needs_lookup(wiki) and not wiki_s

        if not need_imdb and not need_wiki:
            # Nothing to do
            if sentinel_parts:
                row["Lookup Notes (auto)"] = "; ".join(sentinel_parts)
                counts["sentinel_only"] += 1
            else:
                row["Lookup Notes (auto)"] = "Already filled"
                counts["complete"] += 1
            continue

        # Carry sentinel notes forward; lookups may add more
        if sentinel_parts:
            row["Lookup Notes (auto)"] = "; ".join(sentinel_parts)

        if wiki_v and need_imdb:
            pass1_rows.append(i)          # QID known → get tt
        elif imdb_v and need_wiki:
            pass2_rows.append(i)          # tt known → get QID
        else:
            pass3_rows.append(i)          # neither known → title search

    print(f"Already complete (both filled):   {counts['complete']}")
    print(f"Sentinel only (–):                {counts['sentinel_only']}")
    print(f"Pass 1 — QID → IMDb:              {len(pass1_rows)}")
    print(f"Pass 2 — IMDb → Wikidata batch:   {len(pass2_rows)}")
    print(f"Pass 3 — title+year search:       {len(pass3_rows)}")
    print()

    # ── Pass 1: QID → IMDb ────────────────────────────────────────────────────
    # Rows that Pass 1 can't fill (Wikidata item has no wdt:P345) are collected
    # into still_need_imdb so Pass 4 can try the IMDb suggestion API directly.
    # Initialized here; Pass 3 also appends to it.
    still_need_imdb = []

    if pass1_rows:
        qids = [rows[i]["Wikidata ID (auto)"].strip() for i in pass1_rows]
        p1_results = pass1_qid_to_imdb(qids)
        for i in pass1_rows:
            row  = rows[i]
            qid  = row["Wikidata ID (auto)"].strip()
            imdb = p1_results.get(qid, "")
            existing_note = row.get("Lookup Notes (auto)", "").strip()
            if imdb:
                row["IMDb ID (auto)"] = imdb
                note = "IMDb ID found via Wikidata reverse lookup (Pass 1)"
            else:
                note = "Not found in Pass 1: Wikidata item has no IMDb ID (wdt:P345 missing) — will try IMDb directly (Pass 4)"
                # Schedule for Pass 4 — IMDb may have this film even without a Wikidata P345
                still_need_imdb.append(i)
            row["Lookup Notes (auto)"] = (existing_note + "; " + note) if existing_note else note
        _save(rows, existing_cols, "after Pass 1")
        print()

    # ── Pass 2: IMDb → Wikidata (batch) ───────────────────────────────────────
    if pass2_rows:
        imdb_ids = [rows[i]["IMDb ID (auto)"].strip() for i in pass2_rows]
        p2_results = pass2_imdb_to_wikidata(imdb_ids)
        for i in pass2_rows:
            row    = rows[i]
            iid    = row["IMDb ID (auto)"].strip()
            result = p2_results.get(iid)
            existing_note = row.get("Lookup Notes (auto)", "").strip()
            if result:
                row["Wikidata ID (auto)"] = result["qid"]
                if not row.get("Wikipedia URL (auto)", "").strip() and result["wp"]:
                    row["Wikipedia URL (auto)"] = result["wp"]
                note = "Wikidata ID found via IMDb batch SPARQL (Pass 2)"
            else:
                note = (
                    f"Not found: IMDb ID {iid} exists but no Wikidata item "
                    f"links to it via wdt:P345 — film may not be in Wikidata"
                )
            row["Lookup Notes (auto)"] = (existing_note + "; " + note) if existing_note else note
        _save(rows, existing_cols, "after Pass 2")
        print()

    # ── Pass 3: IMDb suggestion API ───────────────────────────────────────────
    # Search IMDb directly by title+year for rows missing both IDs.
    # IMDb has broader film coverage than Wikidata, so we try it first.
    # After this pass, any newly found IMDb IDs are immediately used to fetch
    # their Wikidata IDs via a batch SPARQL query.

    still_need_wikidata = []  # rows that got an IMDb ID but no Wikidata ID yet

    if pass3_rows:
        total   = len(pass3_rows)
        est_min = total * IMDB_DELAY // 60
        print(f"Pass 3: {total} IMDb suggestion API lookups — est. ~{est_min} min at {IMDB_DELAY}s delay")
        print("        (Ctrl-C at any time — progress is saved at the end)\n")

        for seq, i in enumerate(pass3_rows, 1):
            row            = rows[i]
            title          = row.get("Title (auto)", "").strip()
            year           = row.get("Year (auto)", "").strip()
            original_title = row.get("SoS: Original Title", "").strip()

            print(f"  [{seq:>4}/{total}] {title!r} ({year or '?'}) … ", end="", flush=True)

            try:
                imdb, note = pass4_imdb_suggestion(title, year, original_title)
            except KeyboardInterrupt:
                print("\n\n[Interrupted by user — saving progress so far …]")
                still_need_imdb.extend(pass3_rows[seq:])
                break
            except Exception as exc:
                imdb = ""
                note = f"Error during IMDb suggestion lookup: {exc}"

            if imdb and needs_lookup(row.get("IMDb ID (auto)", "")):
                row["IMDb ID (auto)"] = imdb

            existing_note = row.get("Lookup Notes (auto)", "").strip()
            row["Lookup Notes (auto)"] = (existing_note + "; " + note) if existing_note else note

            print(f"IMDb={imdb or '—'}")

            if is_valid_imdb(row.get("IMDb ID (auto)", "")):
                if needs_lookup(row.get("Wikidata ID (auto)", "")):
                    still_need_wikidata.append(i)
            else:
                still_need_imdb.append(i)

            time.sleep(IMDB_DELAY)

        # Immediately fetch Wikidata IDs for newly found IMDb IDs
        if still_need_wikidata:
            new_imdb_ids = [rows[i]["IMDb ID (auto)"].strip() for i in still_need_wikidata]
            print(f"\n  Fetching Wikidata IDs for {len(new_imdb_ids)} newly found IMDb IDs …")
            p3_wikidata = pass2_imdb_to_wikidata(new_imdb_ids)
            for i in still_need_wikidata:
                row  = rows[i]
                iid  = row["IMDb ID (auto)"].strip()
                result = p3_wikidata.get(iid)
                if result:
                    row["Wikidata ID (auto)"] = result["qid"]
                    if not row.get("Wikipedia URL (auto)", "").strip() and result["wp"]:
                        row["Wikipedia URL (auto)"] = result["wp"]
                    existing_note = row.get("Lookup Notes (auto)", "").strip()
                    row["Lookup Notes (auto)"] = (existing_note + "; Wikidata ID found via IMDb batch SPARQL (Pass 3 follow-up)") if existing_note else "Wikidata ID found via IMDb batch SPARQL (Pass 3 follow-up)"

        _save(rows, existing_cols, "after Pass 3")
        print()

    # ── Pass 4: Wikidata title+year search ────────────────────────────────────
    # For rows still missing both IDs after the IMDb search, try Wikidata's
    # label search. This catches films that are in Wikidata but hard to find
    # on IMDb (e.g. foreign-language films, obscure titles).

    if still_need_imdb:
        total   = len(still_need_imdb)
        est_min = total * TITLE_DELAY // 60
        print(f"Pass 4: {total} Wikidata title+year queries — est. ~{est_min} min at {TITLE_DELAY}s delay")
        print("        (Ctrl-C at any time — progress is saved at the end)\n")

        for seq, i in enumerate(still_need_imdb, 1):
            row            = rows[i]
            title          = row.get("Title (auto)", "").strip()
            year           = row.get("Year (auto)", "").strip()
            original_title = row.get("SoS: Original Title", "").strip()

            print(f"  [{seq:>4}/{total}] {title!r} ({year or '?'}) … ", end="", flush=True)

            try:
                imdb, qid, wp, note = pass3_title_year(title, year, original_title)
            except KeyboardInterrupt:
                print("\n\n[Interrupted by user — saving progress so far …]")
                break
            except Exception as exc:
                imdb = qid = wp = ""
                note = f"Error during Wikidata title SPARQL: {exc}"

            if imdb and needs_lookup(row.get("IMDb ID (auto)", "")):
                row["IMDb ID (auto)"] = imdb
            if qid and needs_lookup(row.get("Wikidata ID (auto)", "")):
                row["Wikidata ID (auto)"] = qid
            if wp and not row.get("Wikipedia URL (auto)", "").strip():
                row["Wikipedia URL (auto)"] = wp

            existing_note = row.get("Lookup Notes (auto)", "").strip()
            row["Lookup Notes (auto)"] = (existing_note + "; " + note) if existing_note else note

            print(f"IMDb={imdb or '—'}  QID={qid or '—'}")
            time.sleep(TITLE_DELAY)

        _save(rows, existing_cols, "after Pass 4")
        print()

    # ── Populate IMDb URL for all rows that have a valid IMDb ID ─────────────
    # This covers both pre-existing IDs and any newly filled ones.
    for row in rows:
        iid = row.get("IMDb ID (auto)", "").strip()
        if is_valid_imdb(iid) and not row.get("IMDb URL (auto)", "").strip():
            row["IMDb URL (auto)"] = f"https://www.imdb.com/title/{iid}/"

    # ── Save ──────────────────────────────────────────────────────────────────
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=existing_cols, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved to:\n  {OUTPUT_FILE}\n")

    # ── Stats ─────────────────────────────────────────────────────────────────
    total          = len(rows)
    filled_imdb    = sum(1 for r in rows if is_valid_imdb(r.get("IMDb ID (auto)", "")))
    filled_wiki    = sum(1 for r in rows if is_valid_wikidata(r.get("Wikidata ID (auto)", "")))
    sentinel_imdb  = sum(1 for r in rows if is_sentinel(r.get("IMDb ID (auto)", "")))
    sentinel_wiki  = sum(1 for r in rows if is_sentinel(r.get("Wikidata ID (auto)", "")))
    empty_imdb     = total - filled_imdb - sentinel_imdb
    empty_wiki     = total - filled_wiki - sentinel_wiki

    print("── Final counts ──────────────────────────────────────────")
    print(f"  Total rows:                    {total}")
    print(f"  IMDb ID   — filled (tt…):      {filled_imdb}")
    print(f"  IMDb ID   — manual '–':        {sentinel_imdb}")
    print(f"  IMDb ID   — still empty:       {empty_imdb}")
    print(f"  Wikidata  — filled (Q…):       {filled_wiki}")
    print(f"  Wikidata  — manual '–':        {sentinel_wiki}")
    print(f"  Wikidata  — still empty:       {empty_wiki}")
    print()
    print("  TIP: Open the output TSV and filter the 'Lookup Notes'")
    print("  column to understand every 'still empty' case.")
    print()
    print("Done!")


if __name__ == "__main__":
    main()
