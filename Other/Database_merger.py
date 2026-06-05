"""
Deaf Film Master Database — Merger
====================================
Merges 7 source TSV files into one master database.

Design principles:
  - Every source keeps its own prefixed columns (e.g. "DMDb: Deaf Actor",
    "SoS: Tags", "Wikipedia: Description"). No field values are blended
    across sources — you always know exactly where each piece of data came from.
  - The canonical identity columns (Title, Year, IMDb ID, Wikidata ID) are
    shared and resolved from the most reliable source available.
  - Deduplication uses IMDb ID first, then title + year + director, then
    title + year. Title-only matching is disabled to prevent remakes from
    collapsing into one row.

Output columns:
  Identity:      Title | Year | IMDb ID | Wikidata ID | Sources
  DMDb:          DMDb: Title | DMDb: Duration | DMDb: Genre | DMDb: Release Date |
                 DMDb: Category | DMDb: Deaf Actor | DMDb: Deaf Director |
                 DMDb: Deaf Writer | DMDb: Deaf Editor | DMDb: Language |
                 DMDb: Country | DMDb: Sign Language % | DMDb: Company |
                 DMDb: Free To Watch | DMDb: IMDb ID | DMDb: Synopsis | DMDb: URL
  Sign on Screen: SoS: Title | SoS: Original Title | SoS: Director/Creator |
                 SoS: Year | SoS: Format | SoS: Languages | SoS: Countries |
                 SoS: Platforms | SoS: Summary | SoS: Tags | SoS: IMDb ID
  Wikipedia:     Wikipedia: Title | Wikipedia: Year | Wikipedia: Description |
                 Wikipedia: Article | Wikipedia: URL | Wikipedia: Wikidata ID
  IMDb HoH:      IMDb HoH: Title | IMDb HoH: Year | IMDb HoH: IMDb ID |
                 IMDb HoH: IMDb URL | IMDb HoH: Description | IMDb HoH: Notes
  IMDb Deaf Movies: IMDb Deaf Movies: Title | IMDb Deaf Movies: Year |
                 IMDb Deaf Movies: IMDb ID | IMDb Deaf Movies: IMDb URL |
                 IMDb Deaf Movies: Description
  IMDb Deaf Characters: IMDb Deaf Characters: Title | IMDb Deaf Characters: Year |
                 IMDb Deaf Characters: IMDb ID | IMDb Deaf Characters: IMDb URL |
                 IMDb Deaf Characters: Description
  Hollywood Speaks: HollywoodSpeaks: Title | HollywoodSpeaks: Year |
                 HollywoodSpeaks: Studio/Producer | HollywoodSpeaks: Deaf Characters |
                 HollywoodSpeaks: Length | HollywoodSpeaks: Page |
                 HollywoodSpeaks: Synopsis
"""

import csv, re, os, unicodedata

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
RAW_DIR        = os.path.join(SCRIPT_DIR, "..", "Raw databases")
FILTERED_DIR   = os.path.join(SCRIPT_DIR, "..", "Filtered Databases")
OUTPUT         = os.path.join(SCRIPT_DIR, "..", "Master-Database.tsv")

# ── Output columns ─────────────────────────────────────────────────────────────

OUT_COLS = [
    # ── Titles (all sources) ──────────────────────────────────────────────────
    # "Title" is the best available title, taken from the first non-empty title
    # across all sources in load order (DMDb → SoS → Wikipedia → IMDb → HS).
    "Title (auto)",
    "DMDb: Title", "SoS: Title", "SoS: Original Title",
    "Wikipedia: Title", "IMDb HoH: Title", "IMDb Deaf Movies: Title",
    "IMDb Deaf Characters: Title", "HollywoodSpeaks: Title",

    # ── Years (all sources) ───────────────────────────────────────────────────
    # "Year" is the best available 4-digit year across all sources.
    "Year (auto)",
    "DMDb: Release Date", "SoS: Year", "Wikipedia: Year",
    "IMDb HoH: Year", "IMDb Deaf Movies: Year",
    "IMDb Deaf Characters: Year", "HollywoodSpeaks: Year",

    # ── IMDb IDs (all sources) ────────────────────────────────────────────────
    # "IMDb ID" is the best available tt-number across all sources.
    "IMDb ID (auto)",
    "DMDb: IMDb ID", "SoS: IMDb ID",
    "IMDb HoH: IMDb ID", "IMDb HoH: IMDb URL",
    "IMDb Deaf Movies: IMDb ID", "IMDb Deaf Movies: IMDb URL",
    "IMDb Deaf Characters: IMDb ID", "IMDb Deaf Characters: IMDb URL",

    # ── Wikidata / Wikipedia ──────────────────────────────────────────────────
    "Wikidata ID (auto)", "Wikipedia: Wikidata ID",
    "Wikipedia: Article", "Wikipedia: URL",

    # ── Sources ───────────────────────────────────────────────────────────────
    "Sources",

    # ── Auto-filled by fill_missing_ids.py ───────────────────────────────────
    "IMDb URL (auto)", "Wikipedia URL (auto)", "Lookup Notes (auto)",

    # ── Manually reviewed and entered ────────────────────────────────────────
    "IMDb ID (manual)", "Wikidata ID (manual)",

    # ── Descriptions / Synopses ───────────────────────────────────────────────
    "Wikipedia: Description",
    "IMDb HoH: Description", "IMDb HoH: Notes",
    "IMDb Deaf Movies: Description",
    "IMDb Deaf Characters: Description",
    "DMDb: Synopsis", "SoS: Summary", "HollywoodSpeaks: Synopsis",

    # ── Deaf roles ────────────────────────────────────────────────────────────
    "DMDb: Deaf Actor", "DMDb: Deaf Director",
    "DMDb: Deaf Writer", "DMDb: Deaf Editor",
    "HollywoodSpeaks: Deaf Characters",

    # ── Categories / Tags ─────────────────────────────────────────────────────
    "DMDb: Category", "SoS: Tags",

    # ── Format / Genre / Duration ─────────────────────────────────────────────
    "SoS: Format", "DMDb: Genre", "DMDb: Duration", "HollywoodSpeaks: Length",

    # ── Language ──────────────────────────────────────────────────────────────
    "DMDb: Language", "SoS: Languages",

    # ── Country ───────────────────────────────────────────────────────────────
    "DMDb: Country", "SoS: Countries",

    # ── Sign Language ─────────────────────────────────────────────────────────
    "DMDb: Sign Language %",

    # ── Director / Creator ────────────────────────────────────────────────────
    "SoS: Director/Creator",

    # ── Other ─────────────────────────────────────────────────────────────────
    "DMDb: Company", "DMDb: Free To Watch", "DMDb: URL",
    "SoS: Platforms", "HollywoodSpeaks: Studio/Producer", "HollywoodSpeaks: Page",
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def norm(s):
    """Normalise a string for fuzzy matching."""
    s = str(s).lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"^(the|a|an)\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()

def clean_imdb(s):
    m = re.search(r"tt\d+", str(s))
    return m.group(0) if m else ""

def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def empty_row():
    return {c: "" for c in OUT_COLS}

# ── Deduplication key store ────────────────────────────────────────────────────
#
# Matching priority:
#   1. IMDb ID (most reliable)
#   2. norm(title) + year + norm(director)  — same-year remakes with known director
#   3. norm(title) + year                   — only if directors are compatible
#   4. Title-only matching is DISABLED to prevent different adaptations collapsing
#
# "Compatible directors" means: at least one record has no director, OR they match.

records  = {}   # key → OUT_COLS dict
by_imdb  = {}   # imdb_id → key
by_tyd   = {}   # norm(title)+"|"+year+"|"+norm(director) → key
by_ty    = {}   # norm(title)+"|"+year → key
_counter = [0]

def new_key():
    _counter[0] += 1
    return f"__SYN_{_counter[0]}__"

def find_key(imdb_id, title, year, director=""):
    # 1. IMDb ID
    if imdb_id and imdb_id in by_imdb:
        return by_imdb[imdb_id]
    # 2. Title + year + director
    if year and director:
        tyd = norm(title) + "|" + year + "|" + norm(director)
        if tyd in by_tyd:
            return by_tyd[tyd]
    # 3. Title + year — only if directors are compatible
    if year:
        ty = norm(title) + "|" + year
        if ty in by_ty:
            key = by_ty[ty]
            existing_dir = records[key].get("SoS: Director/Creator", "").strip()
            if director and existing_dir and norm(director) != norm(existing_dir):
                pass  # different directors → different films
            else:
                return key
    return None

def register_keys(key, imdb_id, title, year, director=""):
    if imdb_id:
        by_imdb[imdb_id] = key
    nt = norm(title)
    yr = str(year).strip()
    if nt and yr:
        ty = nt + "|" + yr
        if ty not in by_ty:
            by_ty[ty] = key
        dr = norm(director)
        if dr:
            tyd = ty + "|" + dr
            if tyd not in by_tyd:
                by_tyd[tyd] = key

def add_source(key, source):
    row = records[key]
    existing = [s.strip() for s in row["Sources"].split(";") if s.strip()]
    if source not in existing:
        row["Sources"] = "; ".join(existing + [source])

def upsert(imdb_id, title, year, source_data: dict, source: str, director=""):
    """Find or create a record, then write source_data into it."""
    key = find_key(imdb_id, title, year, director)

    if key is None:
        key = imdb_id if imdb_id else new_key()
        row = empty_row()
        row["Title (auto)"]   = title
        row["Year (auto)"]    = str(year).strip()
        row["IMDb ID (auto)"] = imdb_id
        row["Sources"]        = source
        records[key]   = row
        register_keys(key, imdb_id, title, year, director)
    else:
        row = records[key]
        # Upgrade synthetic key to real IMDb ID
        if imdb_id and key.startswith("__SYN_") and imdb_id not in records:
            records[imdb_id] = row
            del records[key]
            for d in (by_ty, by_tyd):
                for k2, v2 in list(d.items()):
                    if v2 == key:
                        d[k2] = imdb_id
            by_imdb[imdb_id] = imdb_id
            key = imdb_id
        # Fill canonical identity if missing
        if imdb_id and not row["IMDb ID (auto)"]:
            row["IMDb ID (auto)"] = imdb_id
            by_imdb[imdb_id] = key
        if not row["Year (auto)"] and year:
            row["Year (auto)"] = str(year).strip()
        add_source(key, source)
        register_keys(key, imdb_id, title, year, director)

    # Write source-specific fields (never overwrite an already-filled field)
    row = records[key]
    for col, val in source_data.items():
        if col in OUT_COLS and val and not row[col]:
            row[col] = val

    # Keep canonical Title updated — fall back through all source title fields
    if not row["Title (auto)"]:
        for title_col in ["DMDb: Title", "SoS: Title", "SoS: Original Title",
                          "Wikipedia: Title", "IMDb HoH: Title",
                          "IMDb Deaf Movies: Title", "IMDb Deaf Characters: Title",
                          "HollywoodSpeaks: Title"]:
            candidate = row.get(title_col, "").strip()
            if candidate:
                row["Title (auto)"] = candidate
                break

    # Keep canonical Wikidata ID updated
    wdid = source_data.get("Wikipedia: Wikidata ID", "")
    if wdid and not row["Wikidata ID (auto)"]:
        row["Wikidata ID (auto)"] = wdid


# ── Load each source ───────────────────────────────────────────────────────────

print("Loading DMDb...")
for r in read_tsv(os.path.join(FILTERED_DIR, "DMDb-Database-NoTV.tsv")):
    title   = r.get("Title", "").strip()
    year    = re.search(r"\d{4}", r.get("Release Date", "") or "")
    year    = year.group(0) if year else ""
    imdb_id = clean_imdb(r.get("IMDb ID", ""))
    data = {
        "DMDb: Title":         title,
        "DMDb: Duration":      r.get("Duration", ""),
        "DMDb: Genre":         r.get("Genre", ""),
        "DMDb: Release Date":  r.get("Release Date", ""),
        "DMDb: Category":      r.get("Category", ""),
        "DMDb: Deaf Actor":    r.get("Deaf Actor", ""),
        "DMDb: Deaf Director": r.get("Deaf Director", ""),
        "DMDb: Deaf Writer":   r.get("Deaf Writer", ""),
        "DMDb: Deaf Editor":   r.get("Deaf Editor", ""),
        "DMDb: Language":      r.get("Language", ""),
        "DMDb: Country":       r.get("Country", ""),
        "DMDb: Sign Language %": r.get("Sign Language %", ""),
        "DMDb: Company":       r.get("Company", ""),
        "DMDb: Free To Watch": r.get("Free To Watch", ""),
        "DMDb: IMDb ID":       imdb_id,
        "DMDb: Synopsis":      r.get("Synopsis", ""),
        "DMDb: URL":           r.get("URL", ""),
    }
    upsert(imdb_id, title, year, data, "DMDb")

print("Loading Sign on Screen...")
for r in read_tsv(os.path.join(FILTERED_DIR, "Sign_on_Screen-Database-No_Series_VideoGames_.tsv")):
    title    = r.get("English Title", "").strip() or r.get("Original Title", "").strip()
    year     = r.get("Year", "").strip()
    imdb_id  = clean_imdb(r.get("IMDb Tag Number", ""))
    if not title and not imdb_id:
        continue  # skip completely blank rows
    director = r.get("Director/Creator", "").strip()
    data = {
        "SoS: Title":           title,
        "SoS: Original Title":  r.get("Original Title", ""),
        "SoS: Director/Creator": director,
        "SoS: Year":            year,
        "SoS: Format":          r.get("Format", ""),
        "SoS: Languages":       r.get("Languages", ""),
        "SoS: Countries":       r.get("Countries", ""),
        "SoS: Platforms":       r.get("Platforms", ""),
        "SoS: Summary":         r.get("Summary", ""),
        "SoS: Tags":            r.get("Tags", ""),
        "SoS: IMDb ID":         imdb_id,
    }
    upsert(imdb_id, title, year, data, "Sign on Screen", director=director)

print("Loading Wikipedia...")
for r in read_tsv(os.path.join(RAW_DIR, "Wikipedia–List_of_films_featuring_the_deaf_and_hard_of_hearing-June9.tsv")):
    title   = r.get("Film", "").strip()
    year    = r.get("Year", "").strip()
    imdb_id = ""
    data = {
        "Wikipedia: Title":       title,
        "Wikipedia: Year":        year,
        "Wikipedia: Description": r.get("Description", ""),
        "Wikipedia: Article":     r.get("Wikipedia Article", ""),
        "Wikipedia: URL":         r.get("Wikipedia URL", ""),
        "Wikipedia: Wikidata ID": r.get("Wikidata ID", ""),
    }
    upsert(imdb_id, title, year, data, "Wikipedia")

print("Loading IMDb — Deaf & HoH / Sign Language...")
for r in read_tsv(os.path.join(RAW_DIR, "IMDb-List_d_Deaf_and_HoH_characters_people_culture_and_or_featuring_sign_language-May27.tsv")):
    title    = r.get("Title", "").strip()
    year     = r.get("Year", "").strip()
    imdb_id  = clean_imdb(r.get("IMDb ID", ""))
    imdb_url = r.get("IMDb URL", "").strip() or (f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "")
    data = {
        "IMDb HoH: Title":       title,
        "IMDb HoH: Year":        year,
        "IMDb HoH: IMDb ID":     imdb_id,
        "IMDb HoH: IMDb URL":    imdb_url,
        "IMDb HoH: Description": r.get("Description", ""),
        "IMDb HoH: Notes":       r.get("Notes", ""),
    }
    upsert(imdb_id, title, year, data, "IMDb HoH")

print("Loading IMDb — Deaf Movies / Deaf Films...")
for r in read_tsv(os.path.join(RAW_DIR, "IMDb-List_Deaf_Movies_Deaf_Films-May26.tsv")):
    title    = r.get("Title", "").strip()
    year     = r.get("Year", "").strip()
    imdb_id  = clean_imdb(r.get("IMDb ID", ""))
    imdb_url = r.get("IMDb URL", "").strip() or (f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "")
    data = {
        "IMDb Deaf Movies: Title":       title,
        "IMDb Deaf Movies: Year":        year,
        "IMDb Deaf Movies: IMDb ID":     imdb_id,
        "IMDb Deaf Movies: IMDb URL":    imdb_url,
        "IMDb Deaf Movies: Description": r.get("Description", ""),
    }
    upsert(imdb_id, title, year, data, "IMDb Deaf Movies")

print("Loading IMDb — Deaf Characters in Movies...")
for r in read_tsv(os.path.join(RAW_DIR, "IMDb_List-Deaf_characters_in_movies-May26.tsv")):
    title    = r.get("Title", "").strip()
    year     = r.get("Year", "").strip()
    imdb_id  = clean_imdb(r.get("IMDb ID", ""))
    imdb_url = r.get("IMDb URL", "").strip() or (f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "")
    data = {
        "IMDb Deaf Characters: Title":       title,
        "IMDb Deaf Characters: Year":        year,
        "IMDb Deaf Characters: IMDb ID":     imdb_id,
        "IMDb Deaf Characters: IMDb URL":    imdb_url,
        "IMDb Deaf Characters: Description": r.get("Description", ""),
    }
    upsert(imdb_id, title, year, data, "IMDb Deaf Characters")

print("Loading Hollywood Speaks...")
for r in read_tsv(os.path.join(RAW_DIR, "HollywoodSpeaks-Filmography.tsv")):
    title = r.get("Title", "").strip()
    year  = r.get("Year", "").strip()
    data = {
        "HollywoodSpeaks: Title":           title,
        "HollywoodSpeaks: Year":            year,
        "HollywoodSpeaks: Studio/Producer": r.get("Studio/Producer", ""),
        "HollywoodSpeaks: Deaf Characters": r.get("Deaf Character(s) Played By", ""),
        "HollywoodSpeaks: Length":          r.get("Length", ""),
        "HollywoodSpeaks: Page":            r.get("Page in Filmography", ""),
        "HollywoodSpeaks: Synopsis":        r.get("Synopsis (as written in Filmography)", ""),
    }
    upsert("", title, year, data, "Hollywood Speaks")

# ── Write output ───────────────────────────────────────────────────────────────

sorted_rows = sorted(records.values(), key=lambda r: norm(r.get("Title (auto)", "")))

print(f"\nTotal unique titles: {len(sorted_rows)}")
print(f"Writing to {OUTPUT} ...")

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=OUT_COLS, delimiter="\t",
                            extrasaction="ignore")
    writer.writeheader()
    writer.writerows(sorted_rows)

# ── Stats ──────────────────────────────────────────────────────────────────────

from collections import Counter
source_counts = Counter()
multi = 0
for row in sorted_rows:
    srcs = [s.strip() for s in row["Sources"].split(";") if s.strip()]
    for s in srcs:
        source_counts[s] += 1
    if len(srcs) > 1:
        multi += 1

print("\n── Titles per source ──")
for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
    print(f"  {cnt:>4}  {src}")
print(f"\n  {multi} titles appear in more than one source")
print(f"\nDone! Saved to:\n  {OUTPUT}")
