import os
# Bypass system proxy completely
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'
import urllib.request
urllib.request.getproxies = lambda: {}

import sys
import csv
import json
import time
import random
import logging
import tempfile
import threading
import argparse
import re
import socket
import select
import base64
import html as html_module
from collections import deque
from datetime import datetime
from bs4 import BeautifulSoup
from DrissionPage import ChromiumPage, ChromiumOptions

CLEANHTML = re.compile('<.*?>')

# ── Avoid UnicodeEncodeError on Windows terminals ────────────────────────────
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("goodreads_scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("goodreads_scraper")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    return html_module.unescape(re.sub(CLEANHTML, '', raw_html)).strip()


def is_english_isbn(isbn: str) -> bool:
    """ISBN-13 starting with 9780/9781/9798, or ISBN-10 starting with 0/1."""
    d = ''.join(c for c in isbn if c.isdigit())
    if len(d) == 13:
        return d.startswith(('9780', '9781', '9798'))
    if len(d) == 10:
        return d.startswith(('0', '1'))
    return False


def load_proxies_from_env(env_path=".env") -> list:
    proxies = []
    if not os.path.exists(env_path):
        return proxies
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip() == "PROXIES":
                    val = val.strip().strip('"').strip("'")
                    proxies = [p.strip() for p in val.replace(";", ",").split(",") if p.strip()]
                    break
        if proxies:
            logger.info(f"Loaded {len(proxies)} proxies from {env_path}")
    except Exception as e:
        logger.error(f"Error reading {env_path}: {e}")
    return proxies


# ─────────────────────────────────────────────────────────────────────────────
# HTML Parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_goodreads_html(html: str) -> dict:
    """
    Extracts book metadata from Goodreads page HTML.
    Prefers __NEXT_DATA__ JSON, falls back to DOM selectors.
    Uses html.parser (built-in, lighter than lxml for this workload).
    """
    # Use html.parser — no C extension needed, lighter RAM footprint
    soup = BeautifulSoup(html, "html.parser")

    title = None
    desc = None
    genres = []
    reviews_list = []
    point = 0.0
    language = None
    ratings_count = 0
    reviews_count = 0
    currently_reading = 0
    want_to_read = 0

    # ── 1. __NEXT_DATA__ (fastest, most complete) ─────────────────────────────
    next_data_script = soup.find("script", id="__NEXT_DATA__")
    if next_data_script and next_data_script.string:
        try:
            data = json.loads(next_data_script.string)
            apollo = data.get("props", {}).get("pageProps", {}).get("apolloState", {})

            book_key = next((k for k in apollo if k.startswith("Book:")), None)
            work_key = next((k for k in apollo if k.startswith("Work:")), None)

            if book_key:
                bi = apollo[book_key]
                title = bi.get("title")

                # Prefer pre-stripped description
                desc = bi.get('description({"stripped":true})')
                if not desc:
                    raw_desc = bi.get("description", "")
                    desc = clean_html(raw_desc) if raw_desc else None

                details = bi.get("details") or {}
                lang_obj = details.get("language") if isinstance(details, dict) else None
                if isinstance(lang_obj, dict):
                    language = lang_obj.get("name")

                genres = [
                    bg["genre"]["name"]
                    for bg in (bi.get("bookGenres") or [])
                    if isinstance(bg, dict)
                    and isinstance(bg.get("genre"), dict)
                    and bg["genre"].get("name")
                ]

            if work_key:
                stats = (apollo[work_key].get("stats") or {})
                point = stats.get("averageRating", 0.0)
                ratings_count = stats.get("ratingsCount", 0)
                reviews_count = stats.get("textReviewsCount", 0)

            # Currently reading / want to read signals
            for val in apollo.values():
                if not isinstance(val, dict) or val.get("__typename") != "SocialSignal":
                    continue
                name = val.get("name")
                count = val.get("count", 0)
                if name == "CURRENTLY_READING":
                    currently_reading = count
                elif name == "TO_READ":
                    want_to_read = count

            # Extract up to 10 reviews
            root_query = apollo.get("ROOT_QUERY", {})
            reviews_key = next((k for k in root_query if k.startswith("getReviews")), None)
            if reviews_key:
                for edge in (root_query[reviews_key].get("edges") or [])[:10]:
                    node_ref = (edge.get("node") or {}).get("__ref")
                    if not node_ref or node_ref not in apollo:
                        continue
                    rev = apollo[node_ref]

                    author_name = "Anonymous"
                    author_url = None
                    creator_ref = (rev.get("creator") or {}).get("__ref")
                    if creator_ref and creator_ref in apollo:
                        ai = apollo[creator_ref]
                        author_name = ai.get("name", "Anonymous")
                        author_url = ai.get("webUrl")

                    date_str = None
                    created_ms = rev.get("createdAt")
                    if created_ms:
                        try:
                            date_str = datetime.fromtimestamp(created_ms / 1000).strftime('%Y-%m-%d')
                        except Exception:
                            pass

                    reviews_list.append({
                        "Author": author_name,
                        "AuthorUrl": author_url,
                        "Rating": rev.get("rating"),
                        "Likes": rev.get("likeCount", 0),
                        "Date": date_str,
                        "Spoiler": rev.get("spoilerStatus", False),
                        "Text": clean_html(rev.get("text", ""))
                    })

        except Exception as e:
            logger.debug(f"__NEXT_DATA__ parse error: {e}")

    # ── 2. DOM fallbacks ───────────────────────────────────────────────────────
    if not title:
        el = (soup.find("h1", {"data-testid": "bookTitle"})
              or soup.find("meta", {"property": "og:title"})
              or soup.find("h1")
              or soup.title)
        if el:
            title = (el.get("content") or el.text or "").strip() or None

    if not desc:
        desc_el = soup.find("div", {"data-testid": "description"})
        if desc_el:
            formatted = desc_el.find(class_="Formatted")
            desc = (formatted or desc_el).text.strip() or None
        if not desc:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta:
                desc = (meta.get("content") or "").strip() or None

    if not genres:
        seen = []
        for a in soup.find_all("a", href=lambda h: h and "/genres/" in h):
            g = a.text.strip()
            if g and g not in ("...more", "More") and g not in seen:
                seen.append(g)
        genres = seen

    if not point:
        for sel in (
            ("div", {"class": "RatingStatistics__rating"}),
            ("span", {"itemprop": "ratingValue"}),
        ):
            el = soup.find(*sel)
            if el:
                try:
                    point = float(el.text.strip())
                    break
                except ValueError:
                    pass

    def _parse_count(data_testid):
        el = soup.find("span", {"data-testid": data_testid})
        if el:
            digits = re.sub(r'\D', '', el.text)
            return int(digits) if digits else 0
        return 0

    if not ratings_count:
        ratings_count = _parse_count("ratingsCount")
    if not reviews_count:
        reviews_count = _parse_count("reviewsCount")

    if not currently_reading:
        el = soup.find("div", {"data-testid": "currentlyReadingSignal"})
        if el:
            d = re.sub(r'\D', '', el.text)
            currently_reading = int(d) if d else 0

    if not want_to_read:
        el = soup.find("div", {"data-testid": "toReadSignal"})
        if el:
            d = re.sub(r'\D', '', el.text)
            want_to_read = int(d) if d else 0

    return {
        "Title": title,
        "Desc": desc,
        "Genre": genres,
        "Review": reviews_list,
        "Point": point,
        "Language": language,
        "RatingsCount": ratings_count,
        "ReviewsCount": reviews_count,
        "CurrentlyReadingCount": currently_reading,
        "WantToReadCount": want_to_read,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────

def _atomic_write(path: str, data: bytes):
    """Write bytes atomically via temp file."""
    tmp_dir = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=tmp_dir)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def save_checkpoint(checkpoint_file: str, failed_isbns: set, duplicate_isbns: set, non_english_isbns: set):
    try:
        payload = json.dumps({
            "failed_isbns": list(failed_isbns),
            "duplicate_isbns": list(duplicate_isbns),
            "non_english_isbns": list(non_english_isbns),
        }, ensure_ascii=False).encode('utf-8')
        _atomic_write(checkpoint_file, payload)
    except Exception as e:
        logger.error(f"Checkpoint save error: {e}")


# ── Checkpoint dirty-flag: only write when something changed ──────────────────
_checkpoint_dirty = False
_checkpoint_lock = threading.Lock()

def mark_checkpoint_dirty():
    global _checkpoint_dirty
    with _checkpoint_lock:
        _checkpoint_dirty = True

def flush_checkpoint_if_dirty(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns, outer_lock):
    global _checkpoint_dirty
    with _checkpoint_lock:
        if not _checkpoint_dirty:
            return
        _checkpoint_dirty = False
    with outer_lock:
        save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns)


def save_book_data(book: dict, json_file: str, csv_file: str):
    """
    Appends book to JSON (O(1) seek) and CSV.
    Falls back to full rewrite only if the file is tiny or malformed.
    """
    # ── JSON append ────────────────────────────────────────────────────────────
    book_json = json.dumps(book, ensure_ascii=False)

    if not os.path.exists(json_file) or os.path.getsize(json_file) < 10:
        # First book: create valid JSON array
        _atomic_write(json_file, (f"[\n{book_json}\n]").encode('utf-8'))
    else:
        try:
            with open(json_file, 'r+b') as f:
                # Walk backwards to find the closing ']'
                f.seek(0, os.SEEK_END)
                pos = f.tell() - 1
                while pos >= 0:
                    f.seek(pos)
                    ch = f.read(1)
                    if ch == b']':
                        # Overwrite ']' with ',\n<book>\n]'
                        f.seek(pos)
                        f.write((',\n' + book_json + '\n]').encode('utf-8'))
                        f.truncate()
                        break
                    pos -= 1
                else:
                    raise ValueError("Closing ']' not found")
        except Exception as e:
            logger.error(f"JSON O(1) append failed ({e}), falling back to full rewrite")
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    books = json.load(f)
            except Exception:
                books = []
            books.append(book)
            _atomic_write(json_file, json.dumps(books, ensure_ascii=False, indent=2).encode('utf-8'))

    # ── CSV append ─────────────────────────────────────────────────────────────
    csv_exists = os.path.exists(csv_file) and os.path.getsize(csv_file) > 0
    try:
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            if not csv_exists:
                w.writerow(["ISBN", "Title", "Desc", "Genre", "Review", "Point", "Language",
                             "RatingsCount", "ReviewsCount", "CurrentlyReadingCount", "WantToReadCount"])
            w.writerow([
                book["ISBN"], book["Title"], book["Desc"],
                json.dumps(book["Genre"], ensure_ascii=False),
                json.dumps(book["Review"], ensure_ascii=False),
                book["Point"], book.get("Language", ""),
                book.get("RatingsCount", 0), book.get("ReviewsCount", 0),
                book.get("CurrentlyReadingCount", 0), book.get("WantToReadCount", 0),
            ])
    except Exception as e:
        logger.error(f"CSV append error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight TCP proxy relay (auth injection)
# ─────────────────────────────────────────────────────────────────────────────

_PIPE_BUF = 65536  # 64 KB — better throughput than 4 KB


class LocalProxyRelay:
    def __init__(self, listen_host, listen_port, upstream_host, upstream_port, username, password):
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.auth_header = (
            b"Proxy-Authorization: Basic "
            + base64.b64encode(f"{username}:{password}".encode()).strip()
            + b"\r\n"
        )
        self._running = True
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Small kernel buffers — we don't need large ones for a single browser
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        self._srv.bind((listen_host, listen_port))
        self._srv.listen(50)
        self._srv.settimeout(1.0)
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()

    def _accept_loop(self):
        while self._running:
            try:
                client, _ = self._srv.accept()
                threading.Thread(target=self._handle, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _handle(self, client: socket.socket):
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            req = client.recv(4096)
            if not req:
                return

            upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            upstream.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            upstream.connect((self.upstream_host, self.upstream_port))

            if req.startswith(b"CONNECT"):
                m = re.match(rb"CONNECT\s+([^:]+):(\d+)", req)
                if not m:
                    return
                host, port = m.group(1).decode(), m.group(2).decode()
                upstream.sendall(
                    f"CONNECT {host}:{port} HTTP/1.1\r\n".encode()
                    + self.auth_header + b"\r\n"
                )
                resp = upstream.recv(4096)
                if b"200" in resp or b"established" in resp.lower():
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    self._pipe(client, upstream)
                else:
                    client.sendall(resp)
            else:
                # Plain HTTP — inject auth header
                head, _, body = req.partition(b"\r\n\r\n")
                upstream.sendall(head + b"\r\n" + self.auth_header + b"\r\n" + body)
                self._pipe(client, upstream)
        except Exception:
            pass
        finally:
            for s in (client,):
                try:
                    s.close()
                except Exception:
                    pass

    def _pipe(self, a: socket.socket, b: socket.socket):
        a.setblocking(False)
        b.setblocking(False)
        socks = [a, b]
        while self._running:
            try:
                r, _, e = select.select(socks, [], socks, 5.0)
                if e:
                    break
                if not r:
                    break
                for s in r:
                    data = s.recv(_PIPE_BUF)
                    if not data:
                        return
                    (b if s is a else a).sendall(data)
            except Exception:
                break
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass

    def close(self):
        self._running = False
        try:
            self._srv.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Chrome options factory — minimise RAM & disk I/O
# ─────────────────────────────────────────────────────────────────────────────

def make_chrome_options(thread_id: int, proxy: str | None, headless: bool) -> tuple[ChromiumOptions, LocalProxyRelay | None]:
    co = ChromiumOptions()

    # ── Sandbox / GPU / shared mem ────────────────────────────────────────────
    for flag in (
        '--no-sandbox',
        '--disable-gpu',
        '--disable-gpu-compositing',
        '--disable-dev-shm-usage',
        '--disable-software-rasterizer',
        '--disable-blink-features=AutomationControlled',
        # Images already disabled — also disable video/audio codecs
        '--blink-settings=imagesEnabled=false',
        '--disable-background-networking',
        '--disable-default-apps',
        '--disable-extensions',
        '--disable-sync',
        '--disable-translate',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-hang-monitor',
        '--disable-prompt-on-repost',
        '--disable-domain-reliability',
        '--disable-client-side-phishing-detection',
        '--disable-component-update',
        '--disable-features=TranslateUI,BlinkGenPropertyTrees,AudioServiceOutOfProcess',
        '--no-first-run',
        '--no-default-browser-check',
        '--password-store=basic',
        '--use-mock-keychain',
        '--metrics-recording-only',
        '--safebrowsing-disable-auto-update',
        # ── Key: zero disk cache ──────────────────────────────────────────────
        '--disk-cache-size=0',
        '--media-cache-size=0',
        '--aggressive-cache-discard',
        '--disable-application-cache',
        '--disable-offline-auto-reload',
        '--disable-offline-auto-reload-visible-only',
    ):
        co.set_argument(flag)

    # RAM cap: 512 MB per renderer process (adjust if you have more headroom)
    co.set_argument('--renderer-process-limit=1')
    co.set_argument('--js-flags=--max-old-space-size=256')

    # ── User data dir: per-thread temp folder (no persistent profile on C:) ──
    tmp_profile = os.path.join(tempfile.gettempdir(), f"gr_chrome_{thread_id}")
    co.set_argument(f'--user-data-dir={tmp_profile}')

    # ── Proxy ─────────────────────────────────────────────────────────────────
    relay: LocalProxyRelay | None = None
    if proxy:
        m = re.match(r"^(https?|socks5)://([^:]+):([^@]+)@([^:]+):(\d+)$", proxy)
        if m:
            scheme, user, pwd, host, port = m.groups()
            listen_port = 18000 + thread_id
            try:
                relay = LocalProxyRelay("127.0.0.1", listen_port, host, int(port), user, pwd)
                co.set_argument(f'--proxy-server=http://127.0.0.1:{listen_port}')
                co.set_argument('--proxy-bypass-list=<-loopback>')
                logger.info(f"[Thread-{thread_id}] Relay: 127.0.0.1:{listen_port} → {host}:{port}")
            except Exception as e:
                logger.error(f"[Thread-{thread_id}] Relay start failed: {e}")
        else:
            co.set_argument(f'--proxy-server={proxy}')

    # Off-screen window (won't consume GPU memory even in non-headless mode)
    co.set_argument('--window-position=-32000,-32000')
    co.set_argument('--window-size=1024,768')

    co.auto_port()
    if headless:
        co.set_argument('--headless=new')

    return co, relay


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread
# ─────────────────────────────────────────────────────────────────────────────

# How often (in successfully-processed ISBNs) to flush checkpoint to disk
_CHECKPOINT_FLUSH_EVERY = 5


def worker(
    thread_id: int,
    isbns_queue: deque,
    total_to_process: int,
    scraped_titles: set,
    failed_isbns: set,
    duplicate_isbns: set,
    non_english_isbns: set,
    lock: threading.Lock,
    json_file: str,
    csv_file: str,
    checkpoint_file: str,
    global_state: dict,
    shutdown_event: threading.Event,
    proxy: str | None = None,
    delay_min: float = 3.0,
    delay_max: float = 6.0,
    headless: bool = False,
):
    co, relay = make_chrome_options(thread_id, proxy, headless)

    logger.info(f"[Thread-{thread_id}] Starting ChromiumPage...")
    try:
        page = ChromiumPage(co)
    except Exception as e:
        logger.error(f"[Thread-{thread_id}] ChromiumPage init failed: {e}")
        if relay:
            relay.close()
        return

    processed_since_flush = 0

    try:
        while not shutdown_event.is_set():
            # ── Pop next ISBN ─────────────────────────────────────────────────
            with lock:
                if not isbns_queue:
                    break
                isbn = isbns_queue.popleft()
                global_state["processed_so_far"] += 1
                idx = global_state["processed_so_far"]

            logger.info(f"[Thread-{thread_id}] [{idx}/{total_to_process}] ISBN: {isbn}")

            max_retries = 3
            success = False
            waf_blocked = False

            for attempt in range(max_retries):
                if shutdown_event.is_set():
                    break
                try:
                    page.get(f"https://www.goodreads.com/search?q={isbn}", timeout=20)

                    # ── WAF / redirect detection loop ────────────────────────
                    deadline = time.time() + 15
                    redirected = not_found = False
                    # Cache html to avoid repeated round-trips inside the loop
                    last_html_check = 0.0

                    while time.time() < deadline:
                        if shutdown_event.is_set():
                            break

                        cur_url = page.url
                        cur_title = page.title or ""

                        # 403 block
                        if "403 Forbidden" in cur_title or cur_title == "Access Denied":
                            waf_blocked = True
                            break

                        # Redirected to book page
                        if "/book/show/" in cur_url:
                            redirected = True
                            break

                        # No results (title check — cheap)
                        if "showing 1-0 of 0 books" in cur_title.lower():
                            not_found = True
                            break

                        # Only fetch HTML every 1.5 s to avoid hammering renderer
                        now = time.time()
                        if now - last_html_check >= 1.5:
                            cur_html = page.html
                            last_html_check = now

                            if "No results" in cur_html:
                                not_found = True
                                break

                            if "403 Forbidden" in cur_html:
                                waf_blocked = True
                                break

                            # AWS WAF JS challenge — browser handles it; just wait
                            if "AwsWafIntegration" in cur_html or "challenge.js" in cur_html:
                                logger.info(f"[Thread-{thread_id}] WAF challenge detected, waiting…")
                                time.sleep(1.5)
                                continue

                            # Page loaded normally
                            if not page.states.is_loading:
                                break

                        time.sleep(0.4)

                    if shutdown_event.is_set() or waf_blocked:
                        break

                    # ── Process result ────────────────────────────────────────
                    if redirected:
                        html_snapshot = page.html
                        book_data = parse_goodreads_html(html_snapshot)
                        book_title = book_data.get("Title")

                        if not book_title:
                            # One extra attempt after brief pause
                            time.sleep(1.0)
                            book_data = parse_goodreads_html(page.html)
                            book_title = book_data.get("Title")

                        if book_title:
                            if "403 Forbidden" in book_title:
                                waf_blocked = True
                                break

                            lang = book_data.get("Language")
                            if lang and lang != "English":
                                logger.info(f"[Thread-{thread_id}] Non-English '{lang}': '{book_title}' — skipping")
                                with lock:
                                    non_english_isbns.add(isbn)
                                mark_checkpoint_dirty()
                                success = True
                                break

                            point = book_data.get("Point", 0.0)
                            reviews = book_data.get("Review", [])
                            if (not point or point == 0.0) and not reviews:
                                logger.info(f"[Thread-{thread_id}] 0 rating & 0 reviews: '{book_title}' — skipping")
                                with lock:
                                    failed_isbns.add(isbn)
                                mark_checkpoint_dirty()
                                success = True
                                break

                            title_key = book_title.strip().lower()
                            with lock:
                                is_dup = title_key in scraped_titles
                                if is_dup:
                                    duplicate_isbns.add(isbn)
                                else:
                                    scraped_titles.add(title_key)

                            if is_dup:
                                logger.info(f"[Thread-{thread_id}] Duplicate: '{book_title}' — skipping")
                                mark_checkpoint_dirty()
                                success = True
                                break

                            book_data["ISBN"] = isbn
                            with lock:
                                save_book_data(book_data, json_file, csv_file)
                            logger.info(f"[Thread-{thread_id}] ✓ Saved '{book_title}' (★{point})")
                            success = True
                            break

                        else:
                            logger.warning(f"[Thread-{thread_id}] Could not parse title for {isbn} (attempt {attempt+1})")

                    elif not_found:
                        logger.info(f"[Thread-{thread_id}] Not found on Goodreads: {isbn}")
                        with lock:
                            failed_isbns.add(isbn)
                        mark_checkpoint_dirty()
                        success = True
                        break

                    else:
                        logger.warning(f"[Thread-{thread_id}] Timeout/no redirect for {isbn} (attempt {attempt+1})")

                except Exception as e:
                    logger.error(f"[Thread-{thread_id}] Error {isbn} attempt {attempt+1}: {e}")

                # Backoff: shorter than original (2s, 4s instead of 5s, 10s)
                if not success and attempt < max_retries - 1:
                    time.sleep(2 ** attempt * 2)

            # ── WAF block: requeue and shut down ─────────────────────────────
            if waf_blocked:
                logger.error(f"[Thread-{thread_id}] WAF/403 block — requeuing {isbn} and stopping")
                with lock:
                    isbns_queue.appendleft(isbn)
                    global_state["processed_so_far"] -= 1
                shutdown_event.set()
                break

            # ── All retries exhausted ─────────────────────────────────────────
            if not success and not shutdown_event.is_set():
                logger.error(f"[Thread-{thread_id}] All retries failed for {isbn}")
                with lock:
                    failed_isbns.add(isbn)
                mark_checkpoint_dirty()

            # ── Periodic checkpoint flush ─────────────────────────────────────
            processed_since_flush += 1
            if processed_since_flush >= _CHECKPOINT_FLUSH_EVERY:
                flush_checkpoint_if_dirty(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns, lock)
                processed_since_flush = 0

            # ── Polite delay ──────────────────────────────────────────────────
            if not shutdown_event.is_set():
                time.sleep(random.uniform(delay_min, delay_max))

    except Exception as e:
        logger.error(f"[Thread-{thread_id}] Unhandled worker error: {e}")
    finally:
        logger.info(f"[Thread-{thread_id}] Shutting down browser…")
        try:
            page.quit()
        except Exception:
            pass
        if relay:
            relay.close()
        # Final checkpoint flush
        flush_checkpoint_if_dirty(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns, lock)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Goodreads Scraper (optimised)")
    parser.add_argument("--threads",    type=int,   default=4)
    parser.add_argument("--proxy",      type=str,   default=None)
    parser.add_argument("--delay-min",  type=float, default=3.0)
    parser.add_argument("--delay-max",  type=float, default=6.0)
    parser.add_argument("--headless",   type=str,   default="False")
    args, _ = parser.parse_known_args()

    num_threads = args.threads
    delay_min   = args.delay_min
    delay_max   = args.delay_max
    headless    = args.headless.lower() in ("true", "1", "yes")

    proxies = load_proxies_from_env()
    if args.proxy:
        proxies = [args.proxy]

    isbn_file       = "clean_novel_isbns.txt"
    json_file       = "goodreads_books.json"
    csv_file        = "goodreads_books.csv"
    checkpoint_file = "goodreads_checkpoint.json"

    # ── Load checkpoint ───────────────────────────────────────────────────────
    successful_isbns  = set()
    scraped_titles    = set()
    failed_isbns      = set()
    duplicate_isbns   = set()
    non_english_isbns = set()

    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                chk = json.load(f)
            failed_isbns      = set(chk.get("failed_isbns", []))
            duplicate_isbns   = set(chk.get("duplicate_isbns", []))
            non_english_isbns = set(chk.get("non_english_isbns", []))
            logger.info(f"Checkpoint: {len(failed_isbns)} failed, {len(duplicate_isbns)} dup, {len(non_english_isbns)} non-EN")
        except Exception as e:
            logger.error(f"Checkpoint load error: {e}")

    # ── Load & clean existing JSON ────────────────────────────────────────────
    cleaned_books: list = []
    removed_count = 0
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                books = json.load(f)
            for book in books:
                point    = book.get("Point", 0.0)
                reviews  = book.get("Review", [])
                isbn     = book.get("ISBN", "")
                language = book.get("Language")

                zero_data    = (not point or point == 0.0) and not reviews
                non_en       = (language and language != "English") or (not language and isbn and not is_english_isbn(isbn))

                if zero_data or non_en:
                    removed_count += 1
                    if isbn:
                        (non_english_isbns if non_en else failed_isbns).add(isbn)
                else:
                    if not language and isbn and is_english_isbn(isbn):
                        book["Language"] = "English"
                    cleaned_books.append(book)
                    if isbn:
                        successful_isbns.add(isbn)
                    if book.get("Title"):
                        scraped_titles.add(book["Title"].strip().lower())

            logger.info(f"Loaded {len(books)} books; removed {removed_count} (non-EN/zero-data)")

            if removed_count > 0:
                logger.info(f"Rewriting {len(cleaned_books)} clean books…")
                _atomic_write(json_file, json.dumps(cleaned_books, ensure_ascii=False, indent=2).encode('utf-8'))

                if os.path.exists(csv_file):
                    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow(["ISBN","Title","Desc","Genre","Review","Point","Language",
                                    "RatingsCount","ReviewsCount","CurrentlyReadingCount","WantToReadCount"])
                        for b in cleaned_books:
                            w.writerow([
                                b["ISBN"], b["Title"], b["Desc"],
                                json.dumps(b["Genre"], ensure_ascii=False),
                                json.dumps(b["Review"], ensure_ascii=False),
                                b["Point"], b.get("Language",""),
                                b.get("RatingsCount",0), b.get("ReviewsCount",0),
                                b.get("CurrentlyReadingCount",0), b.get("WantToReadCount",0),
                            ])
                save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns)
        except Exception as e:
            logger.error(f"JSON load/clean error: {e}")

    processed_isbns = successful_isbns | failed_isbns | duplicate_isbns | non_english_isbns

    # ── Load ISBN list ────────────────────────────────────────────────────────
    if not os.path.exists(isbn_file):
        logger.error(f"ISBN file '{isbn_file}' not found.")
        return

    raw_queue = deque()
    skipped_non_en = 0
    with open(isbn_file, 'r', encoding='utf-8') as f:
        for line in f:
            isbn = line.strip()
            if not isbn or isbn in processed_isbns:
                continue
            if is_english_isbn(isbn):
                raw_queue.append(isbn)
            else:
                skipped_non_en += 1

    total = len(processed_isbns) + len(raw_queue) + skipped_non_en
    logger.info(
        f"Total ISBNs: {total} | Processed: {len(processed_isbns)} | "
        f"Remaining EN: {len(raw_queue)} | Skipped non-EN: {skipped_non_en}"
    )

    if not raw_queue:
        logger.info("All English ISBNs already processed.")
        return

    # ── Spawn workers ─────────────────────────────────────────────────────────
    lock           = threading.Lock()
    shutdown_event = threading.Event()
    global_state   = {"processed_so_far": 0}
    total_to_proc  = len(raw_queue)

    threads = []
    for i in range(num_threads):
        t_proxy = proxies[i % len(proxies)] if proxies else None
        t = threading.Thread(
            target=worker,
            args=(
                i + 1, raw_queue, total_to_proc,
                scraped_titles, failed_isbns, duplicate_isbns, non_english_isbns,
                lock, json_file, csv_file, checkpoint_file,
                global_state, shutdown_event,
                t_proxy, delay_min, delay_max, headless,
            ),
            daemon=True,
        )
        threads.append(t)
        t.start()
        time.sleep(2.5)  # stagger browser startups

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Interrupted — signalling workers to stop…")
        shutdown_event.set()
        for t in threads:
            t.join(timeout=8.0)
    finally:
        logger.info("Done.")


if __name__ == "__main__":
    main()