import sys
import os
import json
import argparse
from datetime import datetime

# Add script directory to sys.path to enable loading ol_api when run from outside
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ol_api import (
    safe_get, fetch_work_details, fetch_editions, SEARCH_FIELDS, SEARCH_URL, setup_logging, logger
)

def enrich_book_doc(doc: dict) -> dict:
    work_key = doc.get("key", "")
    author_names = doc.get("author_name", []) or []
    author_keys  = doc.get("author_key", []) or []

    book = {
        "work_key":          work_key,
        "title":             doc.get("title", ""),
        "subtitle":          doc.get("subtitle", ""),
        "author_names":      ", ".join(author_names),
        "author_keys":       ", ".join(author_keys),
        "first_publish_year":doc.get("first_publish_year"),
        "crawled_at":        datetime.utcnow().isoformat(),
    }

    # Rich work details
    work_details = fetch_work_details(work_key)
    book.update(work_details)
    book["subjects"] = ", ".join(work_details.get("subjects", []))
    book["subject_places"] = ", ".join(work_details.get("subject_places", []))
    book["subject_people"] = ", ".join(work_details.get("subject_people", []))

    # Edition details (1 English edition)
    edition_info = fetch_editions(work_key)
    book.update(edition_info)
    
    return book

def search_books(title: str = None, isbn: str = None, limit: int = 10) -> list:
    """Search books on OpenLibrary by title or ISBN and return fully enriched details."""
    params = {
        "language": "eng",
        "limit":    limit,
        "fields":   SEARCH_FIELDS,
    }
    if title:
        params["title"] = title
    elif isbn:
        params["isbn"] = isbn
    else:
        logger.error("Must provide either a title or an ISBN to search.")
        return []

    logger.info(f"Querying OpenLibrary Search API with params: {params}")
    data = safe_get(SEARCH_URL, params=params) or {}
    docs = data.get("docs", [])
    results = []

    for doc in docs:
        try:
            logger.info(f"Enriching result: {doc.get('title', '?')} ({doc.get('key', '?')})")
            book = enrich_book_doc(doc)
            results.append(book)
        except Exception as e:
            logger.error(f"Error enriching book '{doc.get('title','?')}': {e}")

    return results

if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    setup_logging()

    parser = argparse.ArgumentParser(description="Search OpenLibrary by Title or ISBN-13 and retrieve fully enriched book metadata.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-t", "--title", type=str, help="Title of the book to search")
    group.add_argument("-i", "--isbn", type=str, help="ISBN-13 of the book to search")
    parser.add_argument("-l", "--limit", type=int, default=5, help="Limit the number of search results (default: 5)")

    args = parser.parse_args()

    results = search_books(title=args.title, isbn=args.isbn, limit=args.limit)
    print(json.dumps(results, ensure_ascii=False, indent=2))
