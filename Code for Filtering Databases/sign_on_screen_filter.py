"""
Sign on Screen — TV Series Filter
===================================
Reads Sign_on_Screen-Database.tsv and removes any row where the Format
field contains "series", equals "serid" (typo for series), or equals
"video game" (case-insensitive).

Output: Sign_on_Screen-Database-NoTV.tsv  (in the uploads folder)
"""

import csv, os, re

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
RAW_DIR      = os.path.join(SCRIPT_DIR, "..", "..", "Raw database")
FILTERED_DIR = os.path.join(SCRIPT_DIR, "..", "..", "Filtered database")

INPUT  = os.path.join(RAW_DIR,      "Sign_on_Screen-Database.tsv")
OUTPUT = os.path.join(FILTERED_DIR, "Sign_on_Screen-Database-NoTV.tsv")


def should_remove(row: dict) -> bool:
    fmt = row.get("Format", "").strip().lower()
    return "series" in fmt or fmt == "serid" or fmt == "video game"


def main():
    with open(INPUT, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    kept    = [r for r in rows if not should_remove(r)]
    removed = [r for r in rows if should_remove(r)]

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()),
                                delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    print(f"Input:   {len(rows)} rows")
    print(f"Removed: {len(removed)} rows (Format contains 'series')")
    print(f"Kept:    {len(kept)} rows")
    print(f"\nSaved to: {OUTPUT}")


if __name__ == "__main__":
    main()
