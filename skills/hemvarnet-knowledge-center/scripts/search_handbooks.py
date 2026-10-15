#!/usr/bin/env python3
"""Search the bundled Hemvärnet OCR texts and show page-level evidence."""

import argparse
import heapq
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "references"
CACHE_ROOT = None  # Defaults to a private directory under the system temp folder.
BOOKS = {
    "hemvarn-2018": "Handbok Hemvärn 2018",
    "hemvarnsbataljon-2022": "Handbok Hemvärnsbataljon 2022",
    "hemvarnskompani-del-1-2017": "Handbok Hemvärnskompani del 1 Grunder (2017)",
    "hemvarnskompani-del-2-2017": "Handbok Hemvärnskompani del 2 Objektet (2017)",
    "hemvarnskompani-del-3-2017": "Handbok Hemvärnskompani del 3 Anvisningar (2017)",
    "transport-farligt-gods-2013": "Reglemente Transport farligt gods 2013",
    "direktiv-hemvarn-2023": "Direktiv Hemvärn 2023",
    "grundlaggande-soldat-och-sjomansutbildningar-2020": "Handbok Grundläggande soldat- och sjömansutbildningar 2020",
    "forplagnadstjanst-2017": "Handbok Förplägnadstjänst 2017",
    "personaltjanst-2024": "Handbok Personaltjänst 2024",
    "stabstjanst-grunder-2016": "Handbok Stabstjänst grunder 2016 (version 1, ändring 2, 2022)",
    "hemvarnspluton-grupp-del-1-2016": "Handbok Hemvärnspluton-grupp del 1 Grunder (2016)",
    "hemvarnspluton-grupp-del-2-2016": "Handbok Hemvärnspluton-grupp del 2 Objektet (2016)",
    "hemvarnspluton-grupp-del-3-2016": "Handbok Hemvärnspluton-grupp del 3 Anvisningar (2016)",
}
STOP = {"och", "eller", "den", "det", "som", "att", "för", "med", "vad", "hur", "en", "ett", "i", "på", "av", "är", "ska", "kan"}


def normalize(s):
    return unicodedata.normalize("NFKC", s).casefold()


def printed_page(page, pdf_page):
    lines = [x.strip() for x in page.splitlines() if x.strip()]
    candidates = []
    for line in list(reversed(lines[-5:])) + lines[:5]:
        m = re.fullmatch(r"(?:[A-ZÅÄÖ /-]+\s*\|\s*)?(\d{1,3})(?:\s*\|\s*[A-ZÅÄÖ /-]+)?", line)
        if m:
            number = int(m.group(1))
            if abs(number - pdf_page) <= 5:
                candidates.append(number)
    return str(min(candidates, key=lambda n: abs(n - pdf_page))) if candidates else None


def load_books(selected, labels=True):
    for key, title in BOOKS.items():
        if selected and selected not in key:
            continue
        for pdf_page, raw in enumerate((ROOT / (key + ".txt")).read_text(encoding="utf-8").split("\f"), 1):
            if raw.strip():
                yield key, title, pdf_page, printed_page(raw, pdf_page) if labels else None, raw


def excerpt(raw, terms, length=420):
    compact = re.sub(r"\s+", " ", raw).strip()
    positions = [normalize(compact).find(t) for t in terms]
    start = max(0, min((p for p in positions if p >= 0), default=0) - 95)
    return ("…" if start else "") + compact[start:start + length] + ("…" if start + length < len(compact) else "")


def source_signature():
    """Invalidate derived data when an edition, title, or extraction changes."""
    import json
    sources = []
    for key, title in BOOKS.items():
        stat = (ROOT / (key + ".txt")).stat()
        sources.append((key, title, stat.st_size, stat.st_mtime_ns))
    return json.dumps([1, str(ROOT.resolve()), sources], ensure_ascii=False)


def open_index():
    """Cache derived page data outside the plugin; publish rebuilds atomically."""
    import hashlib
    import os
    import sqlite3
    import tempfile
    signature = source_signature()
    identity = hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:20]
    user = getattr(os, "getuid", lambda: "local")()
    folder = CACHE_ROOT or Path(tempfile.gettempdir()) / f"hemvarnet-search-{user}"
    folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / (identity + ".sqlite3")
    if target.exists():
        conn = None
        try:
            conn = sqlite3.connect(target)
            if conn.execute("SELECT signature FROM metadata").fetchone() == (signature,):
                return conn
        except sqlite3.DatabaseError:
            pass
        if conn is not None:
            conn.close()
    fd, temporary = tempfile.mkstemp(prefix=identity + "-", suffix=".sqlite3", dir=folder)
    os.close(fd)
    conn = None
    try:
        conn = sqlite3.connect(temporary)
        conn.executescript("""
            CREATE TABLE metadata (signature TEXT NOT NULL);
            CREATE TABLE pages (
                book TEXT, title TEXT, pdf_page INTEGER, printed TEXT,
                raw TEXT, body TEXT, book_order INTEGER,
                PRIMARY KEY (book, pdf_page)
            );
        """)
        order = {key: i for i, key in enumerate(BOOKS)}
        conn.executemany("INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)",
                         ((key, title, page, number, raw, normalize(raw), order[key])
                          for key, title, page, number, raw in load_books(None)))
        conn.execute("INSERT INTO metadata VALUES (?)", (signature,))
        conn.commit()
        conn.close()
        conn = None
        os.replace(temporary, target)
        return sqlite3.connect(target)
    finally:
        if conn is not None:
            conn.close()
        Path(temporary).unlink(missing_ok=True)


def search_rows(conn, selected, terms):
    """Filter in SQLite before loading page text; keep original substring matching."""
    where = " OR ".join("instr(body, ?) > 0" for _ in terms)
    params = list(terms)
    if selected:
        where = f"({where}) AND book = ?"
        params.append(selected)
    yield from conn.execute(
        "SELECT book, title, pdf_page, printed, NULL, body FROM pages WHERE "
        + where + " ORDER BY book_order, pdf_page", params)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", nargs="?", default="", help="Swedish keywords or phrase")
    ap.add_argument("--book", choices=list(BOOKS), help="Limit to one handbook")
    ap.add_argument("--page", type=int, help="Show full extracted PDF page (requires --book)")
    ap.add_argument("--limit", type=int, default=8, help="Maximum search hits")
    ap.add_argument("--context", type=int, default=0, help="Include this many adjacent PDF pages with --page")
    ap.add_argument("--no-cache", action="store_true", help="Read source texts directly without the temporary search index")
    args = ap.parse_args()
    if args.page is not None and not args.book:
        ap.error("--page requires --book")
    if args.context < 0 or (args.context and args.page is None):
        ap.error("--context must be nonnegative and requires --page")
    terms = [t for t in re.findall(r"[\wåäö]+", normalize(args.query)) if t not in STOP and len(t) > 1]
    if args.page is None and not terms:
        ap.error("enter a search query")
    conn = None
    if not args.no_cache and not args.book:
        import sqlite3
        try:
            conn = open_index()
        except (OSError, sqlite3.Error):
            # Read-only or restricted hosts can always search the bundled texts.
            pass
    try:
        run_search(args, terms, conn, ap)
    finally:
        if conn is not None:
            conn.close()


def run_search(args, terms, conn, ap):
    if args.page is not None:
        if conn is None:
            # A page lookup needs only one source file and one page label.
            pages = (ROOT / (args.book + ".txt")).read_text(encoding="utf-8").split("\f")
            rows = [(args.book, BOOKS[args.book], n, printed_page(pages[n-1], n), pages[n-1])
                    for n in range(max(1, args.page - args.context), min(len(pages), args.page + args.context) + 1)
                    if pages[n-1].strip()]
        else:
            rows = conn.execute(
                "SELECT book, title, pdf_page, printed, raw FROM pages "
                "WHERE book = ? AND pdf_page BETWEEN ? AND ? ORDER BY pdf_page",
                (args.book, args.page - args.context, args.page + args.context)).fetchall()
        if not any(row[2] == args.page for row in rows):
            ap.error("page not found")
        for key, title, pdf_page, number, raw in rows:
            print(f"{title} — {'s. ' + number if number else 'PDF-sida ' + str(pdf_page)} (PDF-sida {pdf_page})\n{raw}")
        return
    rows = search_rows(conn, args.book, terms) if conn is not None else (
        (*row, normalize(row[4])) for row in load_books(args.book, labels=False))
    hits = []
    for key, title, pdf_page, number, raw, body in rows:
        score = sum(min(8, body.count(t)) for t in terms)
        coverage = sum(t in body for t in terms)
        if score and coverage >= (len(terms) + 1) // 2:
            hits.append((coverage * 20 + score, key, title, pdf_page, number, raw))
    best = heapq.nlargest(args.limit, hits, key=lambda x: x[0]) if args.limit >= 0 else sorted(hits, key=lambda x: -x[0])[:args.limit]
    for score, key, title, pdf_page, number, raw in best:
        if raw is None:
            raw = conn.execute("SELECT raw FROM pages WHERE book = ? AND pdf_page = ?",
                               (key, pdf_page)).fetchone()[0]
        else:
            number = printed_page(raw, pdf_page)
        label = "s. " + number if number else "PDF-sida " + str(pdf_page)
        print(f"{title} | {key} | {label} (PDF-sida {pdf_page}) | score {score}")
        print(excerpt(raw, terms) + "\n")
    if not hits:
        print("No matches. Try a shorter term, synonym, or abbreviation.")


if __name__ == "__main__":
    main()
