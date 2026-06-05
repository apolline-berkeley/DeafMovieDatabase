"""
Match Deaf Films Against Popular Movie Metadata
=================================================
Reads Deaf-Film-Master-Database.tsv, finds each film's IMDb ID
(preferring the manual column over the auto column), then checks
whether that ID appears in either of the two popular movie metadata
files (1922-1979 and 1980-2025).

Output: Deaf-Films-in-Popular-Metadata.tsv
        One row per deaf film that matched, combining data from both sources.
"""

import csv, os, re

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR     = os.path.join(SCRIPT_DIR, "..")
RAW_DIR      = os.path.join(ROOT_DIR, "Raw databases")

DEAF_DB      = os.path.join(SCRIPT_DIR, "Deaf-Film-Master-Database.tsv")
META_1980    = os.path.join(RAW_DIR, "Movie metadata - Popular 1980-2025.tsv")
META_1922    = os.path.join(RAW_DIR, "Movie metadata - Popular 1922-1979.tsv")
OUTPUT       = os.path.join(ROOT_DIR, "Deaf-Films-in-Popular-Metadata.tsv")


def load_tsv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def clean_imdb(s):
    m = re.search(r"tt\d+", str(s))
    return m.group(0) if m else ""


def main():
    # ── Load metadata files ───────────────────────────────────────────────────
    print("Loading movie metadata files...")
    meta_1980 = load_tsv(META_1980)
    meta_1922 = load_tsv(META_1922)
    print(f"  1980-2025: {len(meta_1980)} rows")
    print(f"  1922-1979: {len(meta_1922)} rows")

    # Build lookup: imdb_id → (metadata_row, source_file_label)
    meta_lookup = {}
    for row in meta_1922:
        iid = clean_imdb(row.get("imdb", ""))
        if iid:
            meta_lookup[iid] = (row, "1922-1979")
    for row in meta_1980:
        iid = clean_imdb(row.get("imdb", ""))
        if iid:
            meta_lookup[iid] = (row, "1980-2025")

    print(f"  Total unique IMDb IDs in metadata: {len(meta_lookup)}\n")

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
        # From metadata
        "Metadata file",
        "Popularity rank",
        "Popularity year",
        "Metadata title",
        "Genre",
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
    matched = 0
    no_id   = 0
    no_match = 0

    for row in deaf_rows:
        # Determine IMDb ID to use: manual first, then auto
        manual_id = clean_imdb(row.get("IMDb ID (manual)", ""))
        auto_id   = clean_imdb(row.get("IMDb ID (auto)", ""))

        if manual_id:
            imdb_id  = manual_id
            id_source = "manual"
        elif auto_id:
            imdb_id  = auto_id
            id_source = "auto"
        else:
            no_id += 1
            continue

        if imdb_id not in meta_lookup:
            no_match += 1
            continue

        meta_row, meta_file = meta_lookup[imdb_id]

        out = {
            "Deaf DB: Title (auto)": row.get("Title (auto)", ""),
            "Deaf DB: Year (auto)":  row.get("Year (auto)", ""),
            "IMDb ID used":          imdb_id,
            "IMDb ID source":        id_source,
            "Metadata file":         meta_file,
            "Popularity rank":       meta_row.get("rank", ""),
            "Popularity year":       meta_row.get("year", ""),
            "Metadata title":        meta_row.get("title", ""),
            "Genre":                 meta_row.get("genre", "") or meta_row.get("Genre", ""),
            "Sources":               row.get("Sources", ""),
            "DMDb: Category":        row.get("DMDb: Category", ""),
            "DMDb: Deaf Actor":      row.get("DMDb: Deaf Actor", ""),
            "DMDb: Deaf Director":   row.get("DMDb: Deaf Director", ""),
            "SoS: Tags":             row.get("SoS: Tags", ""),
            "Wikipedia: Description": row.get("Wikipedia: Description", ""),
            "IMDb HoH: Description": row.get("IMDb HoH: Description", ""),
            "SoS: Summary":          row.get("SoS: Summary", ""),
        }
        matched_rows.append(out)
        matched += 1

    # Sort by metadata file then rank
    matched_rows.sort(key=lambda r: (r["Metadata file"], int(r["Popularity rank"]) if r["Popularity rank"].isdigit() else 9999))

    # ── Write output ──────────────────────────────────────────────────────────
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(matched_rows)

    print(f"Results:")
    print(f"  Matched:          {matched} deaf films found in popular metadata")
    print(f"  No IMDb ID:       {no_id} deaf films skipped (no ID available)")
    print(f"  No metadata match:{no_match} deaf films not in popular metadata")
    print(f"\nSaved to:\n  {OUTPUT}")


if __name__ == "__main__":
    main()
