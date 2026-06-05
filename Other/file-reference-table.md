# Deaf Film Master Database — File Reference

This document explains what each file in the project is for, ordered by process step so the workflow can be traced.

---

## Project Overview

This project builds a **Deaf Film Master Database** by aggregating film data from multiple sources (several IMDb lists, Wikipedia, Sign on Screen, Hollywood Speaks, and DMDb), and enriching records with IMDb IDs and Wikidata IDs.

---

## Folder Structure

```
Claude Files copy/
├── Raw databases/          — original unmodified source files
├── Filtered Databases/     — source files with unwanted entries removed
├── Code for Scraping/      — scripts that fetch data from the web
├── Code for Filtering Databases/ — scripts that filter source files
├── outputs/                — scripts that build and enrich the master database
├── Deaf-Film-Master-Database.tsv  — the final master database output
├── IMDb_and_Wikidata_ID-Manual_Input.tsv — manually reviewed IDs
└── file-reference-table.md — this document
```

---

## File Reference (in process order)

| Step | Folder | File | What It Does |
|---|---|---|---|
| 1 — Gather source data | Raw databases | `IMDb_List-Deaf_characters_in_movies-May26.tsv` | IMDb list of films featuring deaf characters, exported May 26. |
| 1 — Gather source data | Raw databases | `IMDb-List_Deaf_Movies_Deaf_Films-May26.tsv` | IMDb list of films categorized as "Deaf Movies / Deaf Films", exported May 26. |
| 1 — Gather source data | Raw databases | `IMDb-List_d_Deaf_and_HoH_characters_people_culture_and_or_featuring_sign_language-May27.tsv` | Broader IMDb list covering deaf/HoH characters, deaf culture, and sign language films, exported May 27. |
| 1 — Gather source data | Raw databases | `Wikipedia–List_of_films_featuring_the_deaf_and_hard_of_hearing-June9.tsv` | Wikipedia's list of films featuring deaf/HoH representation, scraped June 9. Includes Wikipedia article name, Wikipedia URL, and Wikidata ID for each film. |
| 1 — Gather source data | Raw databases | `HollywoodSpeaks-Filmography.tsv` | Filmography from the Hollywood Speaks organization — a curated list of films featuring deaf/HoH characters. |
| 1 — Gather source data | Raw databases | `DMDb-Database.tsv` | Full raw export from the Deaf Movie Database (deafmovie.org), including all entry types. |
| 1 — Gather source data | Raw databases | `Sign_on_Screen-Database.tsv` | Raw Sign on Screen dataset including all entry types (features, shorts, documentaries, TV series, video games). |
| 1 — Gather source data | Root | `IMDb_and_Wikidata_ID-Manual_Input.tsv` | Manually reviewed and verified IMDb IDs and Wikidata IDs. Used by `apply_manual_ids.py` to add `IMDb ID (manual)` and `Wikidata ID (manual)` columns to the master database. |
| 2 — Scrape web sources | Code for Scraping | `dmdb_website_scraper.py` | Scrapes all title pages on deafmovie.org. Captures Title, Genre, Release Date, Category, Deaf Actor, Deaf Director, Deaf Writer, Deaf Editor, Language, Country, Sign Language %, Company, Free To Watch, IMDb ID, and Synopsis. Run this to refresh `DMDb-Database.tsv`. |
| 2 — Scrape web sources | Code for Scraping | `wikipedia_list_scraper.py` | Fetches the Wikipedia list page, extracts all film entries with their wikilinks, then batch-queries the Wikipedia API for Wikidata IDs and Wikipedia URLs. Run this to refresh the Wikipedia TSV in Raw databases. |
| 3 — Filter source files | Code for Filtering Databases | `sign_on_screen_filter.py` | Removes rows from `Sign_on_Screen-Database.tsv` where Format contains "series", equals "Serid" (typo), or equals "Video Game". Writes `Sign_on_Screen-Database-No_Series_VideoGames_.tsv` to Filtered Databases. |
| 3 — Filter source files | Code for Filtering Databases | `DMDb_filter.py` | Removes rows from `DMDb-Database.tsv` where Category contains "TV Episode". Writes `DMDb-Database-NoTV.tsv` to Filtered Databases. |
| 3 — Filter source files | Filtered Databases | `Sign_on_Screen-Database-No_Series_VideoGames_.tsv` | Sign on Screen data with TV series, "Serid" entries, and video games removed — only films, shorts, and documentaries. |
| 3 — Filter source files | Filtered Databases | `DMDb-Database-NoTV.tsv` | DMDb data with TV episodes removed — only films, shorts, and documentaries. |
| 4 — Merge all sources | outputs | `Database_merger.py` | Merges all 7 source files into one master database. Each source gets its own prefixed columns (e.g. `DMDb: Deaf Actor`, `SoS: Tags`, `Wikipedia: Description`). Deduplicates using IMDb ID first, then title + year + director. Writes `Deaf-Film-Master-Database.tsv`. |
| 5 — Apply manual IDs | outputs | `apply_manual_ids.py` | Re-applies manually reviewed IMDb and Wikidata IDs from `IMDb_and_Wikidata_ID-Manual_Input.tsv` into the master database columns `IMDb ID (manual)` and `Wikidata ID (manual)`. Run this after every `Database_merger.py` run. |
| 6 — Fetch missing IDs | outputs | `fill_missing_ids.py` | Fills missing `IMDb ID (auto)` and `Wikidata ID (auto)` in the master database using 4 passes: (1) Wikidata ID → IMDb via SPARQL, (2) IMDb ID → Wikidata via batch SPARQL, (3) title + year → both IDs via Wikidata label search, (4) IMDb suggestion API fallback. Adds `Lookup Notes (auto)` explaining each result. |
| 7 — Final output | Root | `Deaf-Film-Master-Database.tsv` | The master database — 1,755 unique titles from 7 sources, with 62 columns. Each source's data is in its own prefixed columns. Auto-generated columns are marked `(auto)`, manually reviewed columns are marked `(manual)`. |
