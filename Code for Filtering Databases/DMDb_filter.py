"""
DMDb — TV Episodes Filter
==========================
Reads DMDb-Database.tsv and removes any row where the Category field
contains "TV Episode" (case-insensitive). TV Movies are kept.

Output: DMDb-Database-NoTV.tsv  (in the uploads folder)
"""

import csv, os

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
RAW_DIR      = os.path.join(SCRIPT_DIR, "..", "..", "Raw database")
FILTERED_DIR = os.path.join(SCRIPT_DIR, "..", "..", "Filtered database")

INPUT  = os.path.join(RAW_DIR,      "DMDb-Database.tsv")
OUTPUT = os.path.join(FILTERED_DIR, "DMDb-Database-NoTV.tsv")


def is_tv_episode(row: dict) -> bool:
    category = row.get("Category", "").strip().lower()
    return "tv episode" in category


def main():
    with open(INPUT, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    kept    = [r for r in rows if not is_tv_episode(r)]
    removed = [r for r in rows if is_tv_episode(r)]

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()),
                                delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    print(f"Input:   {len(rows)} rows")
    print(f"Removed: {len(removed)} rows (Category contains 'TV Episode')")
    print(f"Kept:    {len(kept)} rows")
    print(f"\nSaved to: {OUTPUT}")


if __name__ == "__main__":
    main()
