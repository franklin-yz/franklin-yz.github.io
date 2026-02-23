#!/usr/bin/env python3
import html
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote

import bibtexparser
import requests

BIB_FILE = Path('_bibliography/papers.bib')
ORCID_ID = '0000-0002-6997-735X'

SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'codex-publication-reconciler/1.0'})


PREFERRED_FIELD_ORDER = [
    'abbr', 'bibtex_show', 'title', 'author', 'journal', 'booktitle', 'volume', 'number', 'pages', 'publisher',
    'year', 'doi', 'pmid', 'note', 'award', 'award_name', 'selected', 'google_scholar_id', 'from_scholar',
    'abstract', 'website', 'html', 'pdf', 'code', 'poster', 'slides', 'video', 'blog', 'supp'
]


def log(*args):
    print(*args, file=sys.stderr)


def normalize_title(text: str) -> str:
    text = html.unescape(text or '')
    text = re.sub(r'<[^>]+>', '', text)
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = text.replace('’', "'").replace('“', '"').replace('”', '"')
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^a-z0-9]+', '', text)
    return text


def clean_crossref_text(text: str) -> str:
    text = html.unescape(text or '')
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def get_orcid_title_to_doi() -> dict[str, str]:
    url = f'https://pub.orcid.org/v3.0/{ORCID_ID}/works'
    r = SESSION.get(url, headers={'Accept': 'application/json'}, timeout=30)
    r.raise_for_status()
    data = r.json()
    mapping: dict[str, str] = {}
    for group in data.get('group', []):
        summaries = group.get('work-summary', []) or []
        chosen_doi = None
        chosen_title = None
        # Prefer non-preprint DOI in a group; otherwise first DOI.
        for ws in summaries:
            title = (((ws.get('title') or {}).get('title') or {}).get('value') or '').strip()
            dois = []
            for ex in (ws.get('external-ids') or {}).get('external-id', []):
                if (ex.get('external-id-type') or '').lower() == 'doi':
                    val = (ex.get('external-id-value') or '').strip().lower()
                    if val:
                        dois.append(val)
            if not title or not dois:
                continue
            non_pre = [d for d in dois if 'preprints.' not in d]
            doi = non_pre[0] if non_pre else dois[0]
            chosen_title = title
            chosen_doi = doi
            if non_pre:
                break
        if chosen_title and chosen_doi:
            mapping[normalize_title(chosen_title)] = chosen_doi
    return mapping


def crossref_search_doi(title: str) -> str | None:
    q = quote(title)
    url = f'https://api.crossref.org/works?rows=5&query.title={q}'
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    items = r.json().get('message', {}).get('items', [])
    target = normalize_title(title)
    for item in items:
        ctitle = clean_crossref_text((item.get('title') or [''])[0])
        if ctitle and normalize_title(ctitle) == target:
            doi = (item.get('DOI') or '').lower().strip()
            if doi:
                return doi
    return None


def fetch_crossref_by_doi(doi: str) -> dict | None:
    url = f'https://api.crossref.org/works/{quote(doi)}'
    r = SESSION.get(url, timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get('message')


def first_nonempty(*vals):
    for v in vals:
        if v:
            return v
    return None


def crossref_year(msg: dict) -> str | None:
    for k in ['published-print', 'published-online', 'issued', 'created']:
        dp = ((msg.get(k) or {}).get('date-parts') or [])
        if dp and dp[0] and dp[0][0]:
            return str(dp[0][0])
    return None


def crossref_authors(msg: dict) -> str | None:
    authors = msg.get('author') or []
    out = []
    for a in authors:
        family = clean_crossref_text(a.get('family') or '')
        given = clean_crossref_text(a.get('given') or '')
        name = clean_crossref_text(a.get('name') or '')
        if family or given:
            if family and given:
                out.append(f'{family}, {given}')
            else:
                out.append(family or given)
        elif name:
            out.append(name)
    return ' and '.join(out) if out else None


def escape_bib_value(val: str, field: str | None = None) -> str:
    s = str(val)
    s = s.replace('\r\n', ' ').replace('\n', ' ')
    if field == 'award_name':
        s = s.replace(r'\&', '&')
    if field == 'google_scholar_id':
        s = s.replace(r'\_', '_')
    # avoid double escaping existing sequences
    if field not in {'award_name'}:
        s = re.sub(r'(?<!\\)&', r'\\&', s)
    s = re.sub(r'(?<!\\)%', r'\\%', s)
    if field not in {'google_scholar_id'}:
        s = re.sub(r'(?<!\\)_', r'\\_', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def serialize_entry(entry: dict) -> str:
    etype = entry.get('ENTRYTYPE', 'article')
    eid = entry.get('ID', 'entry')
    lines = [f'@{etype}{{{eid},']
    used = {'ENTRYTYPE', 'ID'}

    def add_field(k):
        if k in entry and entry[k] not in (None, ''):
            lines.append(f'  {k.ljust(11)} = {{{escape_bib_value(entry[k], k)}}},')
            used.add(k)

    for k in PREFERRED_FIELD_ORDER:
        add_field(k)

    for k in sorted(entry.keys()):
        if k in used or k in {'ENTRYTYPE', 'ID'}:
            continue
        v = entry[k]
        if v in (None, ''):
            continue
        lines.append(f'  {k.ljust(11)} = {{{escape_bib_value(v, k)}}},')

    if lines[-1].endswith(','):
        lines[-1] = lines[-1][:-1]
    lines.append('}')
    return '\n'.join(lines)


def main() -> int:
    if not BIB_FILE.exists():
        print(f'Missing {BIB_FILE}', file=sys.stderr)
        return 1

    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    parser.homogenize_fields = False
    bib_db = bibtexparser.load(BIB_FILE.open(encoding='utf-8'), parser=parser)
    entries = bib_db.entries

    title_to_orcid_doi = get_orcid_title_to_doi()
    log('Loaded ORCID title->DOI matches:', len(title_to_orcid_doi))

    crossref_cache: dict[str, dict | None] = {}
    changed = 0
    added_doi = 0
    unresolved = []

    for e in entries:
        entry_id = e.get('ID')
        title = clean_crossref_text(e.get('title', ''))
        if not title:
            continue

        doi = (e.get('doi') or '').strip().lower()
        if not doi:
            doi = title_to_orcid_doi.get(normalize_title(title)) or ''
            if not doi:
                try:
                    doi = crossref_search_doi(title) or ''
                except Exception as ex:
                    log('Crossref search failed for', entry_id, ex)
            if doi:
                e['doi'] = doi
                added_doi += 1
                changed += 1
                log('Added DOI', entry_id, doi)

        if not doi:
            unresolved.append(entry_id)
            continue

        if doi not in crossref_cache:
            try:
                crossref_cache[doi] = fetch_crossref_by_doi(doi)
            except Exception as ex:
                log('Crossref fetch failed for DOI', doi, ex)
                crossref_cache[doi] = None
        msg = crossref_cache.get(doi)
        if not msg:
            continue

        updates = {}
        ctitle = clean_crossref_text((msg.get('title') or [''])[0])
        if ctitle:
            updates['title'] = ctitle
        auth = crossref_authors(msg)
        if auth:
            updates['author'] = auth
        yr = crossref_year(msg)
        if yr:
            updates['year'] = yr

        container = clean_crossref_text(((msg.get('container-title') or ['']) or [''])[0])
        if container:
            if e.get('ENTRYTYPE') in {'inproceedings', 'incollection'}:
                updates['booktitle'] = container
            else:
                # Keep misc entries as misc, but still fill journal if present for future use.
                updates['journal'] = container

        volume = clean_crossref_text(str(msg.get('volume') or ''))
        issue = clean_crossref_text(str(msg.get('issue') or ''))
        page = clean_crossref_text(str(msg.get('page') or msg.get('article-number') or ''))
        publisher = clean_crossref_text(str(msg.get('publisher') or ''))
        if volume:
            updates['volume'] = volume
        if issue:
            updates['number'] = issue
        if page:
            updates['pages'] = page.replace('-', '--') if '--' not in page and re.search(r'\d-\d', page) else page
        if publisher:
            updates['publisher'] = publisher

        for k, v in updates.items():
            if e.get(k) != v:
                e[k] = v
                changed += 1

    # Keep curated entries first, imported scholar entries after, preserving relative order.
    curated = [e for e in entries if str(e.get('from_scholar', '')).lower() != 'true']
    imported = [e for e in entries if str(e.get('from_scholar', '')).lower() == 'true']

    out = ['---', '---', '']
    for idx, e in enumerate(curated):
        out.append(serialize_entry(e))
        out.append('')
    if imported:
        out.append('% ---- Imported from Google Scholar ----')
        out.append('')
        for e in imported:
            out.append(serialize_entry(e))
            out.append('')

    BIB_FILE.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')

    print(json.dumps({
        'entries': len(entries),
        'changed_fields': changed,
        'added_doi': added_doi,
        'unresolved_no_doi_entries': unresolved,
        'crossref_cached': len([k for k,v in crossref_cache.items() if v]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
