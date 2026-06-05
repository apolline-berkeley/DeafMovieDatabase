"""
Apply Manual IDs
=================
Applies manually reviewed IMDb IDs and Wikidata IDs from the manual input
file into the master database columns "IMDb ID (manual)" and
"Wikidata ID (manual)".

Run this script after Database_merger.py to ensure manual IDs are always
present in the master database.

Matching strategy:
  1. IMDb ID match — most reliable
  2. Title + Year match (normalised, case-insensitive)
  3. Original Title + Year match (fallback for non-English titles)
"""

import csv, re, os, unicodedata

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
MASTER_FILE = os.path.join(SCRIPT_DIR, "..", "Master-Database.tsv")
MANUAL_FILE = os.path.join(SCRIPT_DIR, "IMDb_Wikidata_ID_Manual_Input.tsv")


def norm(s):
    s = str(s).lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"^(the|a|an)\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def load_manual(path):
    """Load manual file, handling duplicate 'Wikidata ID' column names."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        headers = next(reader)
        for row in reader:
            d = {}
            for i, (h, v) in enumerate(zip(headers, row)):
                # First "Wikidata ID" column (index 5) has the clean Q number
                if h == "Wikidata ID" and i == 5:
                    d["Wikidata ID"] = v.strip()
                elif h not in d:
                    d[h] = v.strip()
            rows.append(d)
    return rows


def main():
    print("=" * 55)
    print("Apply Manual IDs")
    print("=" * 55)
    print(f"Manual file:   {MANUAL_FILE}")
    print(f"Master file:   {MASTER_FILE}\n")

    # ── Load manual input ─────────────────────────────────────────────────────
    manual_rows = load_manual(MANUAL_FILE)
    print(f"Loaded {len(manual_rows)} rows from manual input file.")

    # Build lookup indexes
    by_imdb      = {}
    by_title_year = {}
    for r in manual_rows:
        imdb  = r.get("IMDb ID", "").strip()
        title = r.get("Title", "").strip()
        orig  = r.get("Original Title", "").strip()
        year  = r.get("Year", "").strip()
        # Index by IMDb ID (including – sentinel)
        if imdb:
            by_imdb[imdb] = r
        # Index by title + year
        if title:
            by_title_year[norm(title) + "|" + year] = r
        if orig and orig != title:
            by_title_year[norm(orig) + "|" + year] = r

    # ── Load master database ──────────────────────────────────────────────────
    with open(MASTER_FILE, newline="", encoding="utf-8") as f:
        master_rows = list(csv.DictReader(f, delimiter="\t"))
    cols = list(master_rows[0].keys())

    # Ensure manual columns exist
    for col in ("IMDb ID (manual)", "Wikidata ID (manual)"):
        if col not in cols:
            cols.append(col)
        for row in master_rows:
            row.setdefault(col, "")

    # ── Match and apply ───────────────────────────────────────────────────────
    matched = 0
    for row in master_rows:
        # Reset manual columns before applying
        row["IMDb ID (manual)"]   = ""
        row["Wikidata ID (manual)"] = ""

        # 1. Match by IMDb ID (auto)
        imdb_auto = row.get("IMDb ID (auto)", "").strip()
        manual = by_imdb.get(imdb_auto)

        # 2. Match by Title (auto) + Year (auto)
        if not manual:
            title = row.get("Title (auto)", "").strip()
            year  = row.get("Year (auto)", "").strip()
            manual = by_title_year.get(norm(title) + "|" + year)

        if manual:
            row["IMDb ID (manual)"]    = manual.get("IMDb ID", "")
            row["Wikidata ID (manual)"] = manual.get("Wikidata ID", "")
            matched += 1

    print(f"Matched {matched} / {len(master_rows)} rows in master database.")
    print(f"Unmatched manual entries: {len(manual_rows) - matched} "
          f"(may be title differences or films not yet in the master database)\n")

    # ── Save ──────────────────────────────────────────────────────────────────
    with open(MASTER_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(master_rows)

    print(f"Done. Saved to:\n  {MASTER_FILE}")


if __name__ == "__main__":
    main()
