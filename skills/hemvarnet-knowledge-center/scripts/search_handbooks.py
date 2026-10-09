#!/usr/bin/env python3
"""Search the bundled Hemvärnet OCR texts and show page-level evidence."""

import argparse
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "references"
BOOKS = {
    "hemvarn-2018": "Handbok Hemvärn 2018",
    "hemvarnsbataljon-2022": "Handbok Hemvärnsbataljon 2022",
    "hemvarnskompani-del-1-2017": "Handbok Hemvärnskompani del 1 Grunder (2017)",
    "hemvarnskompani-del-2-2017": "Handbok Hemvärnskompani del 2 Objektet (2017)",
    "hemvarnskompani-del-3-2017": "Handbok Hemvärnskompani del 3 Anvisningar (2017)",
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


def load_books(selected):
    for key, title in BOOKS.items():
        if selected and selected not in key:
            continue
        for pdf_page, raw in enumerate((ROOT / (key + ".txt")).read_text(encoding="utf-8").split("\f"), 1):
            if raw.strip():
                yield key, title, pdf_page, printed_page(raw, pdf_page), raw


def excerpt(raw, terms, length=420):
    compact = re.sub(r"\s+", " ", raw).strip()
    positions = [normalize(compact).find(t) for t in terms]
    start = max(0, min((p for p in positions if p >= 0), default=0) - 95)
    return ("…" if start else "") + compact[start:start + length] + ("…" if start + length < len(compact) else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", nargs="?", default="", help="Swedish keywords or phrase")
    ap.add_argument("--book", choices=list(BOOKS), help="Limit to one handbook")
    ap.add_argument("--page", type=int, help="Show full extracted PDF page (requires --book)")
    ap.add_argument("--limit", type=int, default=8, help="Maximum search hits")
    args = ap.parse_args()
    if args.page is not None and not args.book:
        ap.error("--page requires --book")
    terms = [t for t in re.findall(r"[\wåäö]+", normalize(args.query)) if t not in STOP and len(t) > 1]
    if args.page is None and not terms:
        ap.error("enter a search query")
    hits = []
    for key, title, pdf_page, number, raw in load_books(args.book):
        if args.page is not None:
            if args.page == pdf_page:
                print(f"{title} — {'s. ' + number if number else 'PDF-sida ' + str(pdf_page)} (PDF-sida {pdf_page})\n{raw}")
                return
            continue
        body = normalize(raw)
        score = sum(min(8, body.count(t)) for t in terms)
        coverage = sum(t in body for t in terms)
        if score and coverage >= (len(terms) + 1) // 2:
            hits.append((coverage * 20 + score, key, title, pdf_page, number, raw))
    if args.page is not None:
        ap.error("page not found")
    for score, key, title, pdf_page, number, raw in sorted(hits, key=lambda x: -x[0])[:args.limit]:
        label = "s. " + number if number else "PDF-sida " + str(pdf_page)
        print(f"{title} | {key} | {label} (PDF-sida {pdf_page}) | score {score}")
        print(excerpt(raw, terms) + "\n")
    if not hits:
        print("No matches. Try a shorter term, synonym, or abbreviation.")


if __name__ == "__main__":
    main()
