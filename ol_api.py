"""
OpenLibrary Fiction Book Crawler — OPTIMIZED
- Full async I/O with aiohttp (no GIL bottleneck, no thread overhead)
- In-memory batch accumulation; JSON written atomically per page (not per book)
- CSV streamed in append mode; header written once
- Rate limiter uses token-bucket per-host, not a global serial lock
- seen_keys stored as a set in memory; only count/page saved to progress (not full key list)
- Single persistent aiohttp session with connection pooling
- Configurable concurrency: page fetches + per-page doc processing run fully async
- Resume: re-seeds seen_keys from existing JSON on startup (no separate seen list in progress)
"""

import asyncio
import aiohttp
import json
import csv
import logging
import time
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
OUTPUT_DIR    = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

JSON_FILE     = OUTPUT_DIR / "fiction_books.json"
CSV_FILE      = OUTPUT_DIR / "fiction_books.csv"
PROGRESS_FILE = OUTPUT_DIR / "progress.json"
LOG_FILE      = OUTPUT_DIR / "crawler.log"

BASE_URL      = "https://openlibrary.org"
SEARCH_URL    = f"{BASE_URL}/search.json"

PAGE_SIZE     = 100          # max allowed by API
# How many docs to process concurrently within a page (pure CPU/memory, no extra HTTP)
PROCESS_CONCURRENCY = 200    # semaphore on doc processing coroutines
# Max simultaneous HTTP connections to openlibrary.org
TCP_LIMIT     = 50           # aiohttp total connection limit
TCP_LIMIT_HOST= 50           # per-host limit (we only hit one host)
# Minimum seconds between HTTP requests (token-bucket style, not serial lock)
REQUEST_DELAY = 0.05         # 20 req/s sustained; burst allowed
MAX_RETRIES   = 4
RETRY_BACKOFF = 1.5

FICTION_KEYWORDS = {
    "fiction", "novel", "science fiction", "fantasy", "mystery",
    "detective", "horror", "romance", "historical fiction",
    "adventure", "thriller", "literary fiction", "young adult",
    "fairy tales", "short stories", "novels", "graphic novels",
    "dystopian", "suspense", "crime", "western", "gothic",
    "classic", "classics", "humor", "humorous", "satire", "drama",
    "literature", "magic", "mystery and detective stories", "plays", "play",
    "poetry", "poem", "poems"
}

EXCLUDE_KEYWORDS = {
    "non-fiction", "nonfiction", "biography", "autobiography",
    "textbook", "manual", "guide", "dictionary", "encyclopedia",
    "essay", "academic"
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
    "novel",
    "novels",
    "short stories",
    "graphic novels",
    "fantasy",
    "mystery",
    "romance",
    "horror",
    "thriller",
    "adventure",
    "detective",
    "fairy tales",
    "young adult",
    "dystopian",
    "suspense",
    "crime",
    "western",
    "gothic",
    "classics",
    "humor",
    "satire",
    "drama",
    "literature",
    "magic",
    "mystery and detective stories",
]

SEARCH_FIELDS = ",".join([
    "key", "title", "subtitle", "author_name", "author_key",
    "subject", "subject_place", "subject_people", "first_publish_year",
    "isbn", "cover_i", "publisher", "publish_year", "edition_key",
    "number_of_pages_median", "language", "ddc", "lcc",
    "id_goodreads", "id_librarything"
])

# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────
def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

logger = logging.getLogger("fiction_crawler")

# ─────────────────────────────────────────────────────────────
# PROGRESS (no more full seen_key list — rebuild from JSON on resume)
# ─────────────────────────────────────────────────────────────
def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            p = json.load(f)
        logger.info(
            f"Resuming: subject={p.get('current_subject','fiction')}, "
            f"page={p.get('last_page',1)}, collected={p.get('total_collected',0)}"
        )
        return p
    return {"current_subject": "fiction", "last_page": 1, "total_collected": 0}

def save_progress(progress: dict):
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        # Never store seen_work_keys here (can be millions of entries — too slow)
        slim = {k: v for k, v in progress.items() if k != "seen_work_keys"}
        json.dump(slim, f)
    os.replace(str(tmp), str(PROGRESS_FILE))

def rebuild_seen_keys_from_json() -> set:
    """Re-read existing JSON to populate seen_keys on resume. O(n) once at startup."""
    if not JSON_FILE.exists():
        return set()
    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            books = json.load(f)
        keys = {b["work_key"] for b in books if b.get("work_key")}
        logger.info(f"Loaded {len(keys)} seen keys from existing JSON.")
        return keys
    except (json.JSONDecodeError, KeyError):
        logger.warning("Could not parse existing JSON; starting fresh.")
        return set()

# ─────────────────────────────────────────────────────────────
# I/O — batch writes, no per-book file access
# ─────────────────────────────────────────────────────────────
_json_lock = asyncio.Lock()    # protects JSON file during async writes
_all_books: list = []          # in-memory accumulator (rebuilt on resume)
_pending_books_count = 0       # track how many books are unsaved to JSON

async def batch_save(new_books: list, force: bool = False):
    """Append new_books to in-memory list, write to JSON periodically, stream CSV rows."""
    global _all_books, _pending_books_count
    if not new_books and not force:
        return

    # CSV: always append immediately to prevent data loss on crash
    if new_books:
        await asyncio.get_event_loop().run_in_executor(None, _append_csv_sync, new_books)

    async with _json_lock:
        if new_books:
            _all_books.extend(new_books)
            _pending_books_count += len(new_books)

        # Flush to JSON if buffer has >= 1000 items, or force is True (e.g. exit/interrupt)
        if _pending_books_count >= 1000 or force:
            if _all_books:
                tmp = JSON_FILE.with_suffix(".tmp")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _write_json_sync, tmp, _all_books)
                os.replace(str(tmp), str(JSON_FILE))
                logger.info(f"  💾 Flushed {len(_all_books)} books to JSON (saved {_pending_books_count} new).")
                _pending_books_count = 0

def _write_json_sync(path: Path, data: list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _append_csv_sync(rows: list):
    file_exists = CSV_FILE.exists() and CSV_FILE.stat().st_size > 0
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

# ─────────────────────────────────────────────────────────────
# TOKEN-BUCKET RATE LIMITER (non-blocking, allows burst)
# ─────────────────────────────────────────────────────────────
class TokenBucket:
    """Async token bucket: allows burst up to `capacity`, refills at `rate` tokens/sec."""
    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
            # Need to wait for next token
            wait = (1 - self._tokens) / self.rate
            self._tokens = 0
            self._last = now + wait
        await asyncio.sleep(wait)

# ─────────────────────────────────────────────────────────────
# ASYNC HTTP CLIENT
# ─────────────────────────────────────────────────────────────
class AsyncHTTPClient:
    def __init__(self, rate: float, burst: float):
        self.bucket = TokenBucket(rate=rate, capacity=burst)
        connector = aiohttp.TCPConnector(
            limit=TCP_LIMIT,
            limit_per_host=TCP_LIMIT_HOST,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(total=20, connect=5)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "FictionCrawler/2.0 (educational; contact: admin@example.com)"},
        )

    async def get(self, url: str, params: dict = None) -> Optional[dict]:
        for attempt in range(1, MAX_RETRIES + 1):
            await self.bucket.acquire()
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 429:
                        wait = RETRY_BACKOFF ** attempt * 2
                        logger.warning(f"Rate limited {url} — waiting {wait:.1f}s")
                        await asyncio.sleep(wait)
                        continue
                    if resp.status in (404, 403):
                        return None
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout {url} (attempt {attempt}/{MAX_RETRIES})")
            except aiohttp.ClientResponseError as e:
                logger.warning(f"HTTP {e.status} {url}")
                if e.status in (404, 403):
                    return None
            except aiohttp.ClientError as e:
                logger.warning(f"Client error {url}: {e} (attempt {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF ** attempt)
        logger.error(f"Failed after {MAX_RETRIES} attempts: {url}")
        return None

    async def close(self):
        await self.session.close()

# ─────────────────────────────────────────────────────────────
# SUBJECT FILTER (unchanged logic, pure CPU — fast)
# ─────────────────────────────────────────────────────────────
def is_fiction(subjects: list) -> bool:
    if not subjects:
        return False
    subs = [str(s).lower() for s in subjects]
    for sub in subs:
        if any(ex in sub for ex in EXCLUDE_KEYWORDS):
            return False
        if "history" in sub and "historical" not in sub:
            return False
    for sub in subs:
        if any(kw in sub for kw in FICTION_KEYWORDS):
            return True
    return False

# ─────────────────────────────────────────────────────────────
# PROCESS ONE DOC (pure CPU, no I/O)
# ─────────────────────────────────────────────────────────────
def is_english_or_untagged(doc: dict) -> bool:
    langs = doc.get("language", []) or []
    if langs:
        return any("eng" in l.lower() for l in langs)
    title = doc.get("title", "")
    if not title:
        return False
    try:
        title.encode("ascii")
        return True
    except UnicodeEncodeError:
        latin_chars = sum(1 for c in title if ord(c) < 0x024F)
        return (latin_chars / len(title)) > 0.8

def process_doc(doc: dict) -> Optional[dict]:
    """Transform a raw search doc into a book record. Returns None if non-fiction or foreign."""
    work_key = doc.get("key", "")
    if not work_key:
        return None

    if not is_english_or_untagged(doc):
        return None

    raw_subjects = doc.get("subject", []) or []
    if not is_fiction(raw_subjects):
        return None

    author_names = doc.get("author_name", []) or []
    author_keys  = doc.get("author_key", []) or []
    cover_id     = doc.get("cover_i")

    isbns = doc.get("isbn", []) or []
    isbn_13_list, isbn_10_list = [], []
    for i in isbns:
        i_clean = i.strip().replace("-", "")
        if len(i_clean) == 13:
            isbn_13_list.append(i_clean)
        elif len(i_clean) == 10:
            isbn_10_list.append(i_clean)
        elif len(i_clean) > 10:
            isbn_13_list.append(i_clean)
        else:
            isbn_10_list.append(i_clean)

    publish_years = doc.get("publish_year", []) or []
    edition_keys  = doc.get("edition_key", []) or []
    edition_key   = edition_keys[0] if edition_keys else ""
    langs         = doc.get("language", []) or []
    dewey         = doc.get("ddc", []) or []
    lc            = doc.get("lcc", []) or []
    goodreads     = doc.get("id_goodreads", []) or []
    librarything  = doc.get("id_librarything", []) or []
    publishers    = doc.get("publisher", []) or []

    return {
        "work_key":           work_key,
        "title":              doc.get("title", ""),
        "subtitle":           doc.get("subtitle", ""),
        "author_names":       ", ".join(author_names),
        "author_keys":        ", ".join(author_keys),
        "first_publish_year": doc.get("first_publish_year"),
        "subjects":           ", ".join(raw_subjects),
        "subject_places":     ", ".join(doc.get("subject_place", []) or []),
        "subject_people":     ", ".join(doc.get("subject_people", []) or []),
        "description":        "",
        "cover_id":           cover_id,
        "cover_url":          f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None,
        "isbn_13":            ", ".join(isbn_13_list),
        "isbn_10":            ", ".join(isbn_10_list),
        "publishers":         ", ".join(publishers),
        "publish_year":       str(publish_years[0]) if publish_years else "",
        "edition_key":        f"/books/{edition_key}" if edition_key and not edition_key.startswith("/") else edition_key,
        "edition_title":      doc.get("title", ""),
        "number_of_pages":    doc.get("number_of_pages_median"),
        "languages":          ", ".join(langs) if langs else "eng",
        "dewey_decimal":      ", ".join(dewey),
        "lc_classifications": ", ".join(lc),
        "goodreads_id":       goodreads[0] if goodreads else None,
        "librarything_id":    librarything[0] if librarything else None,
        "crawled_at":         datetime.now(timezone.utc).isoformat(),
    }

# ─────────────────────────────────────────────────────────────
# PAGE FETCH
# ─────────────────────────────────────────────────────────────
async def fetch_page(client: AsyncHTTPClient, subject: str, page: int) -> list:
    params = {
        "subject":  subject,
        "sort":     "new",
        "limit":    PAGE_SIZE,
        "offset":   (page - 1) * PAGE_SIZE,
        "fields":   SEARCH_FIELDS,
    }
    data = await client.get(SEARCH_URL, params=params)
    if not data:
        return []
    docs  = data.get("docs", [])
    total = data.get("numFound", 0)
    logger.info(f"  [subject={subject!r}] page={page} got={len(docs)} total={total}")
    return docs

# ─────────────────────────────────────────────────────────────
# MAIN ASYNC CRAWLER
# ─────────────────────────────────────────────────────────────
async def crawl_async():
    setup_logging()
    logger.info("=" * 60)
    logger.info("OpenLibrary Fiction Crawler v2 (async) starting")
    logger.info("=" * 60)

    progress  = load_progress()
    seen_keys: set = rebuild_seen_keys_from_json()

    # Pre-load existing books into memory
    global _all_books
    if JSON_FILE.exists() and seen_keys:
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                _all_books = json.load(f)
        except Exception:
            _all_books = []

    total_collected = progress.get("total_collected", len(_all_books))

    # Rate: 1/REQUEST_DELAY req/s sustained, burst of 10
    client = AsyncHTTPClient(rate=1.0 / REQUEST_DELAY, burst=10)
    sem = asyncio.Semaphore(PROCESS_CONCURRENCY)

    async def process_with_sem(doc: dict) -> Optional[dict]:
        async with sem:
            # process_doc is pure CPU; run it normally (fast, no I/O)
            return process_doc(doc)

    try:
        resume_subject = progress.get("current_subject", "fiction")
        resume_page    = progress.get("last_page", 1)

        start_idx = 0
        if resume_subject in FICTION_SEARCH_SUBJECTS:
            start_idx = FICTION_SEARCH_SUBJECTS.index(resume_subject)
        else:
            resume_page = 1

        batch_size = 10  # fetch 10 pages concurrently
        for idx in range(start_idx, len(FICTION_SEARCH_SUBJECTS)):
            subject = FICTION_SEARCH_SUBJECTS[idx]
            page    = resume_page if subject == resume_subject else 1

            logger.info(f"\n{'─'*50}")
            logger.info(f"Subject: {subject!r} (starting page {page})")
            logger.info(f"{'─'*50}")

            finished = False
            while not finished:
                pages_to_fetch = list(range(page, page + batch_size))
                
                # Fetch pages concurrently
                fetch_tasks = [fetch_page(client, subject, p) for p in pages_to_fetch]
                pages_docs = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                
                # Process pages in order
                for i, docs in enumerate(pages_docs):
                    curr_page = pages_to_fetch[i]
                    
                    if isinstance(docs, Exception):
                        logger.error(f"Error fetching page {curr_page}: {docs}")
                        continue
                    if not docs:
                        logger.info(f"No more results for {subject!r} at page {curr_page}.")
                        finished = True
                        break
                        
                    # Filter already-seen docs before processing
                    new_docs = [d for d in docs if d.get("key") not in seen_keys]
                    logger.info(f"  [page {curr_page}] {len(new_docs)} new docs (skipping {len(docs)-len(new_docs)} seen)")
                    
                    # Process all docs concurrently (pure CPU transform)
                    process_tasks = [asyncio.create_task(process_with_sem(doc)) for doc in new_docs]
                    results = await asyncio.gather(*process_tasks, return_exceptions=True)
                    
                    page_books = []
                    for res in results:
                        if isinstance(res, Exception):
                            logger.error(f"Processing error: {res}")
                        elif res is not None:
                            seen_keys.add(res["work_key"])
                            page_books.append(res)
                            
                    total_collected += len(page_books)
                    progress["total_collected"] = total_collected
                    
                    if page_books:
                        await batch_save(page_books)
                        
                    progress["current_subject"] = subject
                    progress["last_page"]       = curr_page
                    save_progress(progress)
                    
                    if len(docs) < PAGE_SIZE:
                        logger.info(f"Reached last page for {subject!r} at page {curr_page}.")
                        finished = True
                        break
                
                if finished:
                    break
                page += batch_size

    except asyncio.CancelledError:
        logger.warning("Cancelled. Progress saved.")
    except KeyboardInterrupt:
        logger.warning("Interrupted. Progress saved.")
    finally:
        # Force flush any buffered books to JSON
        await batch_save([], force=True)
        save_progress(progress)
        await client.close()
        logger.info(f"\n{'='*60}")
        logger.info(f"Done. Total books: {total_collected}")
        logger.info(f"JSON  → {JSON_FILE.resolve()}")
        logger.info(f"CSV   → {CSV_FILE.resolve()}")
        logger.info(f"Log   → {LOG_FILE.resolve()}")
        logger.info("=" * 60)

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print("aiohttp not found. Install with:  pip install aiohttp")
        sys.exit(1)

    asyncio.run(crawl_async())