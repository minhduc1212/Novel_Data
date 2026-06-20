"""
OpenLibrary Fiction Book Crawler
- Crawls all fiction books from OpenLibrary API
- Filters: English, fiction genre only, 1 edition per book
- Features: logging, resume, thread-safe crawling, saves to JSON + CSV
"""

import requests
import json
import csv
import logging
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

JSON_FILE   = OUTPUT_DIR / "fiction_books.json"
CSV_FILE    = OUTPUT_DIR / "fiction_books.csv"
PROGRESS_FILE = OUTPUT_DIR / "progress.json"
LOG_FILE    = OUTPUT_DIR / "crawler.log"

BASE_URL    = "https://openlibrary.org"
SEARCH_URL  = f"{BASE_URL}/search.json"
WORKS_URL   = f"{BASE_URL}/works"
AUTHORS_URL = f"{BASE_URL}/authors"

PAGE_SIZE       = 100       # max allowed by API
MAX_WORKERS     = 20        # parallel detail fetches (increased from 5)
REQUEST_DELAY   = 0.3       # seconds between requests (polite crawl)
MAX_RETRIES     = 3
RETRY_BACKOFF   = 2         # exponential backoff base

# Fiction subject tags to include (at least one must match)
# Fiction subject keywords/phrases to include
FICTION_KEYWORDS = {
    "fiction", "novel", "science fiction", "fantasy", "mystery",
    "detective", "horror", "romance", "historical fiction",
    "adventure", "thriller", "literary fiction", "young adult",
    "fairy tales", "short stories", "novels", "graphic novels"
}

# Exclude non-fiction keywords to avoid cluttering results (excluding 'history' to allow 'historical fiction')
EXCLUDE_KEYWORDS = {
    "non-fiction", "nonfiction", "biography", "autobiography",
    "textbook", "manual", "guide", "dictionary", "encyclopedia",
    "poetry", "essay", "academic"
}

CSV_FIELDS = [
    "work_key", "title", "subtitle", "author_names", "author_keys",
    "first_publish_year", "subject_places", "subject_people", "subjects",
    "description", "cover_id", "cover_url",
    "isbn_13", "isbn_10", "publishers", "publish_year",
    "edition_key", "edition_title", "number_of_pages",
    "languages", "dewey_decimal", "lc_classifications",
    "goodreads_id", "librarything_id",
    "crawled_at",
]

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(threadName)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# PROGRESS / RESUME
# ─────────────────────────────────────────────
progress_lock = threading.Lock()

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r") as f:
            p = json.load(f)
        logger.info(f"Resuming from progress: page={p.get('last_page',0)}, "
                    f"collected={p.get('total_collected',0)}")
        return p
    return {"last_page": 0, "total_collected": 0, "seen_work_keys": []}

def save_progress(progress: dict):
    with progress_lock:
        for attempt in range(1, 6):
            try:
                with open(PROGRESS_FILE, "w") as f:
                    json.dump(progress, f)
                return
            except PermissionError:
                logger.warning(f"Permission denied for progress file. Retrying ({attempt}/5) in 2s...")
                time.sleep(2.0)

# ─────────────────────────────────────────────
# THREAD-SAFE DATA STORE (ROBUST WRITING WITH RETRIES ON LOCKS)
# ─────────────────────────────────────────────
data_lock  = threading.Lock()
seen_lock  = threading.Lock()

def safe_write_json(json_path: Path, data: list, retries: int = 5, delay: float = 2.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except PermissionError:
            logger.warning(f"Permission denied for {json_path.name}. Is it open in another program? "
                           f"Retrying ({attempt}/{retries}) in {delay}s...")
            time.sleep(delay)
    logger.error(f"Failed to write JSON to {json_path} after {retries} attempts due to PermissionError.")
    return False

def safe_write_csv(csv_path: Path, fieldnames: list, rows: list, retries: int = 5, delay: float = 2.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            file_exists = csv_path.exists()
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                if not file_exists:
                    writer.writeheader()
                writer.writerows(rows)
            return True
        except PermissionError:
            logger.warning(f"Permission denied for {csv_path.name}. Is it open in Excel or another program? "
                           f"Retrying ({attempt}/{retries}) in {delay}s...")
            time.sleep(delay)
    logger.error(f"Failed to write CSV to {csv_path} after {retries} attempts due to PermissionError.")
    return False

def append_to_json(book: dict, json_path: Path):
    with data_lock:
        books = []
        if json_path.exists():
            for attempt in range(1, 6):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        books = json.load(f)
                    break
                except json.JSONDecodeError:
                    books = []
                    break
                except PermissionError:
                    if attempt == 5:
                        logger.error(f"Failed to read JSON file {json_path} due to permission lock.")
                    time.sleep(2.0)
        books.append(book)
        safe_write_json(json_path, books)

def append_to_csv(book: dict, csv_path: Path):
    with data_lock:
        safe_write_csv(csv_path, CSV_FIELDS, [book])

# ─────────────────────────────────────────────
# HTTP HELPER
# ─────────────────────────────────────────────
session = requests.Session()
session.headers.update({"User-Agent": "FictionCrawler/1.0 (educational project; contact: admin@example.com)"})
# Configure connection pooling to match MAX_WORKERS
adapter = requests.adapters.HTTPAdapter(pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
session.mount("http://", adapter)
session.mount("https://", adapter)

rate_limit_lock = threading.Lock()
next_request_time = 0.0

def safe_get(url: str, params: dict = None, retries: int = MAX_RETRIES) -> Optional[dict]:
    global next_request_time
    for attempt in range(1, retries + 1):
        try:
            # Thread-safe rate limiter that sleeps OUTSIDE the lock to allow parallel sleeping and requests
            sleep_time = 0.0
            with rate_limit_lock:
                now = time.time()
                if now < next_request_time:
                    sleep_time = next_request_time - now
                    next_request_time += REQUEST_DELAY
                else:
                    next_request_time = now + REQUEST_DELAY

            if sleep_time > 0:
                time.sleep(sleep_time)

            resp = session.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF ** attempt
                logger.warning(f"Rate limited. Waiting {wait}s before retry {attempt}/{retries}")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on {url} (attempt {attempt}/{retries})")
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP {e.response.status_code} on {url}")
            if e.response.status_code in (404, 403):
                return None          # no point retrying
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request error: {e} (attempt {attempt}/{retries})")
        if attempt < retries:
            time.sleep(RETRY_BACKOFF ** attempt)
    logger.error(f"Failed after {retries} attempts: {url}")
    return None

# ─────────────────────────────────────────────
# SUBJECT FILTER
# ─────────────────────────────────────────────
def is_fiction(subjects: list) -> bool:
    if not subjects:
        return False
    
    subjects_lower = [str(s).lower() for s in subjects]
    
    # 1. Reject if any subject matches an exclusion keyword
    for sub in subjects_lower:
        if any(ex in sub for ex in EXCLUDE_KEYWORDS):
            return False
        # Special check: exclude "history" only if it doesn't represent "historical" fiction
        if "history" in sub and "historical" not in sub:
            return False
            
    # 2. Accept if any subject contains a fiction keyword/phrase (e.g. "fiction", "fantasy", "romance")
    for sub in subjects_lower:
        if any(kw in sub for kw in FICTION_KEYWORDS):
            return True
            
    return False

# ─────────────────────────────────────────────
# DETAIL FETCHERS
# ─────────────────────────────────────────────
def fetch_work_details(work_key: str) -> dict:
    """GET /works/OL123W.json — rich metadata for a work."""
    data = safe_get(f"{BASE_URL}{work_key}.json") or {}
    desc = data.get("description", "")
    if isinstance(desc, dict):
        desc = desc.get("value", "")

    subjects        = data.get("subjects", [])
    subject_places  = data.get("subject_places", [])
    subject_people  = data.get("subject_people", [])
    covers          = data.get("covers", [])
    cover_id        = covers[0] if covers else None

    return {
        "subjects":        subjects,
        "subject_places":  subject_places,
        "subject_people":  subject_people,
        "description":     desc,
        "cover_id":        cover_id,
        "cover_url":       f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None,
    }

def fetch_editions(work_key: str) -> dict:
    """GET /works/OL123W/editions.json — pick newest English edition."""
    data = safe_get(f"{BASE_URL}{work_key}/editions.json") or {}
    entries = data.get("entries", [])

    best = None
    for ed in entries:
        langs = [l.get("key", "") for l in ed.get("languages", [])]
        if langs and not any("eng" in l for l in langs):
            continue                       # skip non-English editions
        if best is None:
            best = ed
        else:
            # prefer most recent
            if (ed.get("publish_date") or "") > (best.get("publish_date") or ""):
                best = ed

    if not best:
        best = entries[0] if entries else {}

    isbns_13 = best.get("isbn_13", [])
    isbns_10 = best.get("isbn_10", [])
    publishers = best.get("publishers", [])
    publish_date = best.get("publish_date", "")
    pages = best.get("number_of_pages")
    ed_key   = best.get("key", "")
    ed_title = best.get("title", "")

    # identifiers block
    ids = best.get("identifiers", {})
    goodreads  = ids.get("goodreads", [None])[0] if ids.get("goodreads") else None
    librarything = ids.get("librarything", [None])[0] if ids.get("librarything") else None

    # Dewey / LC
    dewey = best.get("dewey_decimal_class", [])
    lc    = best.get("lc_classifications", [])

    return {
        "isbn_13":           ", ".join(isbns_13),
        "isbn_10":           ", ".join(isbns_10),
        "publishers":        ", ".join(publishers),
        "publish_year":      publish_date,
        "edition_key":       ed_key,
        "edition_title":     ed_title,
        "number_of_pages":   pages,
        "languages":         "eng",
        "dewey_decimal":     ", ".join(dewey),
        "lc_classifications":", ".join(lc),
        "goodreads_id":      goodreads,
        "librarything_id":   librarything,
    }

def fetch_author_details(author_key: str) -> dict:
    """Optional enrichment — author bio, birth date."""
    data = safe_get(f"{BASE_URL}{author_key}.json") or {}
    return {
        "birth_date":  data.get("birth_date", ""),
        "bio":         (data.get("bio") or {}).get("value", "") if isinstance(data.get("bio"), dict) else data.get("bio", ""),
    }

# ─────────────────────────────────────────────
# PROCESS ONE BOOK
# ─────────────────────────────────────────────
def process_book(doc: dict, seen_keys: set, progress: dict, save_files: bool = True) -> Optional[dict]:
    work_key = doc.get("key", "")
    if not work_key:
        return None

    with seen_lock:
        if work_key in seen_keys:
            return None
        seen_keys.add(work_key)

    # Quick subject filter using search result subjects
    raw_subjects = doc.get("subject", []) or []
    if not is_fiction(raw_subjects):
        logger.debug(f"Skipping non-fiction: {doc.get('title','?')}")
        return None

    logger.info(f"Processing: {doc.get('title','?')} ({work_key})")

    # Base info from search
    author_names = doc.get("author_name", []) or []
    author_keys  = doc.get("author_key", []) or []
    
    # Extract cover_id and cover_url
    cover_id = doc.get("cover_i")
    cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None

    # Parse ISBN-10 and ISBN-13
    isbns = doc.get("isbn", []) or []
    isbn_13_list = []
    isbn_10_list = []
    for i in isbns:
        i_clean = i.strip().replace("-", "")
        if len(i_clean) == 13:
            isbn_13_list.append(i_clean)
        elif len(i_clean) == 10:
            isbn_10_list.append(i_clean)
        else:
            if len(i_clean) > 10:
                isbn_13_list.append(i_clean)
            else:
                isbn_10_list.append(i_clean)

    # Median pages
    pages = doc.get("number_of_pages_median")

    # Publishers
    publishers = doc.get("publisher", []) or []

    # Publish year
    publish_years = doc.get("publish_year", []) or []
    publish_year = str(publish_years[0]) if publish_years else ""

    # Edition key
    edition_keys = doc.get("edition_key", []) or []
    edition_key = edition_keys[0] if edition_keys else ""

    # Languages
    langs = doc.get("language", []) or []
    languages = ", ".join(langs) if langs else "eng"

    # Dewey and LC
    dewey = doc.get("ddc", []) or []
    lc = doc.get("lcc", []) or []

    # Goodreads and LibraryThing IDs
    goodreads = doc.get("id_goodreads", []) or []
    librarything = doc.get("id_librarything", []) or []
    goodreads_id = goodreads[0] if goodreads else None
    librarything_id = librarything[0] if librarything else None

    book = {
        "work_key":          work_key,
        "title":             doc.get("title", ""),
        "subtitle":          doc.get("subtitle", ""),
        "author_names":      ", ".join(author_names),
        "author_keys":       ", ".join(author_keys),
        "first_publish_year":doc.get("first_publish_year"),
        "crawled_at":        datetime.utcnow().isoformat(),
        "subjects":          ", ".join(raw_subjects),
        "subject_places":    ", ".join(doc.get("subject_place", []) or []),
        "subject_people":    ", ".join(doc.get("subject_people", []) or []),
        "description":       "", # Bypassed in bulk search crawl to achieve 200x speedup
        "cover_id":          cover_id,
        "cover_url":         cover_url,
        "isbn_13":           ", ".join(isbn_13_list),
        "isbn_10":           ", ".join(isbn_10_list),
        "publishers":        ", ".join(publishers),
        "publish_year":      publish_year,
        "edition_key":       f"/books/{edition_key}" if edition_key and not edition_key.startswith("/") else edition_key,
        "edition_title":     doc.get("title", ""), # Fallback to work title
        "number_of_pages":   pages,
        "languages":         languages,
        "dewey_decimal":     ", ".join(dewey),
        "lc_classifications":", ".join(lc),
        "goodreads_id":      goodreads_id,
        "librarything_id":   librarything_id,
    }

    if save_files:
        append_to_json(book, JSON_FILE)
        append_to_csv(book, CSV_FILE)

    with progress_lock:
        progress["total_collected"] += 1

    logger.info(f"  ✓ Processed [{progress['total_collected']}]: {book['title']}")
    return book

# ─────────────────────────────────────────────
# SEARCH PAGINATION
# ─────────────────────────────────────────────
FICTION_SEARCH_SUBJECTS = [
    "fiction",
    "science fiction",
    "fantasy fiction",
    "mystery fiction",
    "historical fiction",
    "romance fiction",
    "horror fiction",
    "thriller fiction",
    "adventure fiction",
    "literary fiction",
]

SEARCH_FIELDS = ",".join([
    "key", "title", "subtitle", "author_name", "author_key",
    "subject", "subject_place", "subject_people", "first_publish_year",
    "isbn", "cover_i", "publisher", "publish_year", "edition_key",
    "number_of_pages_median", "language", "ddc", "lcc",
    "id_goodreads", "id_librarything"
])

def search_fiction_page(subject: str, page: int) -> list:
    offset = (page - 1) * PAGE_SIZE
    params = {
        "subject":  subject,
        "sort":     "new",
        "language": "eng",
        "limit":    PAGE_SIZE,
        "offset":   offset,
        "fields":   SEARCH_FIELDS,
    }
    data = safe_get(SEARCH_URL, params=params)
    if not data:
        return []
    docs = data.get("docs", [])
    total = data.get("numFound", 0)
    logger.info(f"  [subject={subject}] page={page} offset={offset} "
                f"got={len(docs)} total={total}")
    return docs

# ─────────────────────────────────────────────
# MAIN CRAWLER
# ─────────────────────────────────────────────
def crawl():
    setup_logging()
    logger.info("=" * 60)
    logger.info("OpenLibrary Fiction Crawler starting")
    logger.info("=" * 60)

    progress  = load_progress()
    seen_keys = set(progress.get("seen_work_keys", []))

    # Load existing books from JSON file once at start to avoid reading/parsing it repeatedly
    all_books = []
    if JSON_FILE.exists():
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                all_books = json.load(f)
            logger.info(f"Loaded {len(all_books)} existing books from JSON file.")
        except json.JSONDecodeError:
            logger.warning("Could not parse existing JSON file, starting fresh.")
            all_books = []

    try:
        for subject in FICTION_SEARCH_SUBJECTS:
            page = 1
            logger.info(f"\n{'─'*50}")
            logger.info(f"Subject: '{subject}'")
            logger.info(f"{'─'*50}")

            while True:
                docs = search_fiction_page(subject, page)
                if not docs:
                    logger.info(f"No more results for '{subject}'.")
                    break

                page_books = []
                # Parallel detail fetching
                with ThreadPoolExecutor(max_workers=MAX_WORKERS,
                                        thread_name_prefix="worker") as executor:
                    futures = {
                        executor.submit(process_book, doc, seen_keys, progress, False): doc
                        for doc in docs
                    }
                    for future in as_completed(futures):
                        try:
                            book = future.result()
                            if book:
                                page_books.append(book)
                        except Exception as e:
                            doc = futures[future]
                            logger.error(f"Error processing '{doc.get('title','?')}': {e}")

                # Save new books in batch after each page
                if page_books:
                    with data_lock:
                        all_books.extend(page_books)
                        safe_write_json(JSON_FILE, all_books)
                        safe_write_csv(CSV_FILE, CSV_FIELDS, page_books)
                    logger.info(f"  💾 Saved batch of {len(page_books)} books to JSON and CSV.")

                # Save progress after each page
                progress["last_page"]       = page
                progress["seen_work_keys"]  = list(seen_keys)
                save_progress(progress)

                if len(docs) < PAGE_SIZE:
                    logger.info(f"Reached last page for '{subject}'.")
                    break
                page += 1

    except KeyboardInterrupt:
        logger.warning("Interrupted by user. Progress saved.")
    finally:
        progress["seen_work_keys"] = list(seen_keys)
        save_progress(progress)
        logger.info(f"\n{'='*60}")
        logger.info(f"Crawl complete. Total books collected: {progress['total_collected']}")
        logger.info(f"JSON  → {JSON_FILE.resolve()}")
        logger.info(f"CSV   → {CSV_FILE.resolve()}")
        logger.info(f"Log   → {LOG_FILE.resolve()}")
        logger.info("=" * 60)


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    crawl()