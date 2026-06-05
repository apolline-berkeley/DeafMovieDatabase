"""
Match Deaf Films Against Prestige Movie Metadata
==================================================
Reads Deaf-Film-Master-Database.tsv, finds each film's IMDb ID
(preferring the manual column over the auto column), then checks
whether that ID appears in Movie metadata - Prestige.tsv.

Each prestige row represents one award nomination or win, and can
reference multiple films via the "all movies" JSON array. A single
deaf film may match multiple prestige rows (one per award/nomination).

Output: Deaf-Films-in-Prestige-Metadata.tsv
        One row per (deaf film × award entry) match.
"""

import csv, os, re, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.join(SCRIPT_DIR, "..")
RAW_DIR    = os.path.join(ROOT_DIR, "Raw databases")

DEAF_DB    = os.path.join(SCRIPT_DIR, "Deaf-Film-Master-Database.tsv")
PRESTIGE   = os.path.join(RAW_DIR, "Movie metadata - Prestige.tsv")
OUTPUT     = os.path.join(ROOT_DIR, "Deaf-Films-in-Prestige-Metadata.tsv")


def load_tsv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def clean_imdb(s):
    m = re.search(r"tt\d+", str(s))
    return m.group(0) if m else ""


def extract_imdb_ids(cell):
    """Extract all tt... IDs from a JSON array string like ["tt0019071", "tt0019553"]."""
    return re.findall(r"tt\d+", str(cell))


def main():
    # ── Load prestige file ────────────────────────────────────────────────────
    print("Loading prestige metadata...")
    prestige_rows = load_tsv(PRESTIGE)
    print(f"  {len(prestige_rows)} award entries")

    # Build lookup: imdb_id → list of prestige rows that mention it
    prestige_lookup = {}
    for row in prestige_rows:
        ids = extract_imdb_ids(row.get("all movies", ""))
        for iid in ids:
            if iid not in prestige_lookup:
                prestige_lookup[iid] = []
            prestige_lookup[iid].append(row)

    print(f"  Unique IMDb IDs referenced: {len(prestige_lookup)}\n")

    # ── Load deaf film database ───────────────────────────────────────────────
    print("Loading Deaf-Film-Master-Database...")
    deaf_rows = load_tsv(DEAF_DB)
    print(f"  {len(deaf_rows)} rows\n")

    # ── Match ─────────────────────────────────────────────────────────────────
    out_cols = [
        # Identity
        "Deaf DB: Title (auto)",
        "Deaf DB: Year (auto)",
        "IMDb ID used",
        "IMDb ID source",
        # Award info
        "Award",
        "Award year",
        "Category",
        "Winner",
        "Notes",
        # Key deaf DB columns
        "Sources",
        "DMDb: Category",
        "DMDb: Deaf Actor",
        "DMDb: Deaf Director",
        "SoS: Tags",
        "Wikipedia: Description",
        "IMDb HoH: Description",
        "SoS: Summary",
    ]

    matched_rows = []
    matched_films = set()
    no_id    = 0
    no_match = 0

    for row in deaf_rows:
        manual_id = clean_imdb(row.get("IMDb ID (manual)", ""))
        auto_id   = clean_imdb(row.get("IMDb ID (auto)", ""))

        if manual_id:
            imdb_id   = manual_id
            id_source = "manual"
        elif auto_id:
            imdb_id   = auto_id
            id_source = "auto"
        else:
            no_id += 1
            continue

        if imdb_id not in prestige_lookup:
            no_match += 1
            continue

        matched_films.add(imdb_id)

        for prestige_row in prestige_lookup[imdb_id]:
            out = {
                "Deaf DB: Title (auto)":  row.get("Title (auto)", ""),
                "Deaf DB: Year (auto)":   row.get("Year (auto)", ""),
                "IMDb ID used":           imdb_id,
                "IMDb ID source":         id_source,
                "Award":                  prestige_row.get("award", ""),
                "Award year":             prestige_row.get("year", ""),
                "Category":               prestige_row.get("category", ""),
                "Winner":                 prestige_row.get("winner", ""),
                "Notes":                  prestige_row.get("notes", ""),
                "Sources":                row.get("Sources", ""),
                "DMDb: Category":         row.get("DMDb: Category", ""),
                "DMDb: Deaf Actor":       row.get("DMDb: Deaf Actor", ""),
                "DMDb: Deaf Director":    row.get("DMDb: Deaf Director", ""),
                "SoS: Tags":              row.get("SoS: Tags", ""),
                "Wikipedia: Description": row.get("Wikipedia: Description", ""),
                "IMDb HoH: Description":  row.get("IMDb HoH: Description", ""),
                "SoS: Summary":           row.get("SoS: Summary", ""),
            }
            matched_rows.append(out)

    # Sort by film title then award year
    matched_rows.sort(key=lambda r: (r["Deaf DB: Title (auto)"].lower(), r["Award year"]))

    # ── Write output ──────────────────────────────────────────────────────────
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(matched_rows)

    print(f"Results:")
    print(f"  Matched films:    {len(matched_films)} deaf films found in prestige metadata")
    print(f"  Total rows:       {len(matched_rows)} (one per award nomination/win)")
    print(f"  No IMDb ID:       {no_id} deaf films skipped (no ID available)")
    print(f"  No match:         {no_match} deaf films not in prestige metadata")
    print(f"\nSaved to:\n  {OUTPUT}")


if __name__ == "__main__":
    main()
