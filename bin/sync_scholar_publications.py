#!/usr/bin/env python3

import re
from pathlib import Path

import bibtexparser
import yaml
from scholarly import scholarly


SOCIALS_FILE = Path("_data/socials.yml")
BIB_FILE = Path("_bibliography/papers.bib")


STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def load_scholar_user_id() -> str:
    if not SOCIALS_FILE.exists():
        raise FileNotFoundError(f"Missing config file: {SOCIALS_FILE}")
    data = yaml.safe_load(SOCIALS_FILE.read_text(encoding="utf-8")) or {}
    scholar_userid = data.get("scholar_userid")
    if not scholar_userid:
        raise ValueError(f"Missing 'scholar_userid' in {SOCIALS_FILE}")
    return scholar_userid.strip()


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def safe_bib_value(value: str) -> str:
    text = (value or "").strip()
    text = text.replace("\\", "\\\\")
    text = text.replace("&", "\\&")
    text = text.replace("%", "\\%")
    text = text.replace("_", "\\_")
    text = text.replace("#", "\\#")
    return text


def first_author_lastname(authors: str) -> str:
    if not authors:
        return "paper"
    first = authors.split(" and ")[0].strip()
    if "," in first:
        return re.sub(r"[^A-Za-z0-9]+", "", first.split(",")[0]).lower() or "paper"
    parts = first.split()
    return re.sub(r"[^A-Za-z0-9]+", "", parts[-1]).lower() if parts else "paper"


def key_from_metadata(authors: str, year: str, title: str, used_keys: set[str]) -> str:
    base_author = first_author_lastname(authors)
    y = re.sub(r"[^0-9]", "", str(year)) or "0000"
    words = [
        w
        for w in re.split(r"[^A-Za-z0-9]+", (title or "").lower())
        if w and w not in STOPWORDS
    ]
    slug = "".join(words[:3])[:24] or "work"
    base = f"{base_author}{y}{slug}"
    candidate = base
    suffix = 2
    while candidate in used_keys:
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def load_existing_bib() -> tuple[list[dict], set[str], set[str]]:
    if not BIB_FILE.exists():
        raise FileNotFoundError(f"Missing bibliography file: {BIB_FILE}")

    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    parser.homogenize_fields = False
    bib_db = bibtexparser.load(BIB_FILE.open(encoding="utf-8"), parser=parser)

    entries = bib_db.entries
    title_set = {normalize_title(e.get("title", "")) for e in entries if e.get("title")}
    key_set = {e.get("ID") for e in entries if e.get("ID")}
    return entries, title_set, key_set


def build_entry_text(
    entry_type: str,
    key: str,
    title: str,
    authors: str,
    year: str,
    scholar_pub_id: str,
    journal: str = "",
    conference: str = "",
    volume: str = "",
    number: str = "",
    pages: str = "",
    publisher: str = "",
    citation: str = "",
) -> str:
    lines = [
        f"@{entry_type}{{{key},",
        "  bibtex_show = {true},",
        f"  title       = {{{safe_bib_value(title)}}},",
        f"  author      = {{{safe_bib_value(authors)}}},",
    ]

    if entry_type == "article" and journal:
        lines.append(f"  journal     = {{{safe_bib_value(journal)}}},")
    if entry_type == "inproceedings" and conference:
        lines.append(f"  booktitle   = {{{safe_bib_value(conference)}}},")
    if volume:
        lines.append(f"  volume      = {{{safe_bib_value(str(volume))}}},")
    if number:
        lines.append(f"  number      = {{{safe_bib_value(str(number))}}},")
    if pages:
        lines.append(f"  pages       = {{{safe_bib_value(str(pages))}}},")
    if publisher:
        lines.append(f"  publisher   = {{{safe_bib_value(publisher)}}},")
    if entry_type == "misc" and citation:
        lines.append(f"  note        = {{{safe_bib_value(citation)}}},")

    lines.append(f"  year        = {{{year}}},")

    if scholar_pub_id and ":" in scholar_pub_id:
        lines.append(f"  google_scholar_id = {{{scholar_pub_id.split(':', 1)[1]}}},")

    lines.append("  from_scholar = {true}")
    lines.append("}")
    return "\n".join(lines)


def main() -> int:
    scholar_user_id = load_scholar_user_id()
    _, existing_titles, existing_keys = load_existing_bib()

    scholarly.set_timeout(20)
    scholarly.set_retries(2)

    author = scholarly.search_author_id(scholar_user_id)
    author_data = scholarly.fill(author, sections=["publications"])
    publications = author_data.get("publications", [])
    if not publications:
        print(f"No publications found for Scholar ID {scholar_user_id}")
        return 1

    new_entries: list[str] = []
    skipped_existing = 0
    skipped_missing = 0

    for pub in publications:
        filled = scholarly.fill(pub)
        bib = filled.get("bib", {}) or {}
        title = (bib.get("title") or "").strip()
        authors = (bib.get("author") or "").strip()
        year = str(bib.get("pub_year") or "").strip()

        if not title or not year:
            skipped_missing += 1
            continue

        normalized = normalize_title(title)
        if normalized in existing_titles:
            skipped_existing += 1
            continue

        journal = (bib.get("journal") or "").strip()
        conference = (bib.get("conference") or "").strip()
        volume = str(bib.get("volume") or "").strip()
        number = str(bib.get("number") or "").strip()
        pages = str(bib.get("pages") or "").strip()
        publisher = str(bib.get("publisher") or "").strip()
        citation = str(bib.get("citation") or "").strip()
        scholar_pub_id = filled.get("author_pub_id", "")

        if journal:
            entry_type = "article"
        elif conference:
            entry_type = "inproceedings"
        else:
            entry_type = "misc"

        key = key_from_metadata(authors, year, title, existing_keys)
        existing_keys.add(key)
        existing_titles.add(normalized)

        new_entries.append(
            build_entry_text(
                entry_type=entry_type,
                key=key,
                title=title,
                authors=authors,
                year=year,
                scholar_pub_id=scholar_pub_id,
                journal=journal,
                conference=conference,
                volume=volume,
                number=number,
                pages=pages,
                publisher=publisher,
                citation=citation,
            )
        )

    if not new_entries:
        print(
            f"No new entries to append. Existing matches: {skipped_existing}, missing metadata: {skipped_missing}."
        )
        return 0

    append_text = "\n\n% ---- Imported from Google Scholar ----\n\n" + "\n\n".join(new_entries) + "\n"
    with BIB_FILE.open("a", encoding="utf-8") as f:
        f.write(append_text)

    print(
        f"Appended {len(new_entries)} new entries to {BIB_FILE}. Existing matches: {skipped_existing}, missing metadata: {skipped_missing}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
