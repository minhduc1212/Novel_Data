import os
os.environ['NO_PROXY'] = '127.0.0.1,localhost'
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
from datetime import datetime
from bs4 import BeautifulSoup
from DrissionPage import ChromiumPage, ChromiumOptions
CLEANHTML = re.compile('<.*?>')

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleantext = re.sub(CLEANHTML, '', raw_html)
    return html_module.unescape(cleantext).strip()

def is_english_isbn(isbn):
    """
    Checks if an ISBN is likely to be an English book based on its prefix and registration group.
    - ISBN-13 beginning with 9780 or 9781 (English groups) or 9798 (US)
    - ISBN-10 beginning with 0 or 1
    """
    isbn_clean = ''.join(c for c in isbn if c.isdigit())
    if len(isbn_clean) == 13:
        return isbn_clean.startswith(('9780', '9781', '9798'))
    elif len(isbn_clean) == 10:
        return isbn_clean.startswith(('0', '1'))
    return False

def load_proxies_from_env(env_path=".env"):
    """
    Loads a list of proxies from the PROXIES variable in a .env file.
    Example in .env:
    PROXIES=http://1.2.3.4:8080,http://username:password@5.6.7.8:1080
    """
    proxies = []
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        if key.strip() == "PROXIES":
                            val = val.strip().strip('"').strip("'")
                            proxies = [p.strip() for p in val.replace(";", ",").split(",") if p.strip()]
                            break
            if proxies:
                logger.info(f"Loaded {len(proxies)} proxies from {env_path}")
        except Exception as e:
            logger.error(f"Error reading {env_path} file: {e}")
    return proxies

# Avoid UnicodeEncodeError on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("goodreads_scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("goodreads_scraper")

def parse_goodreads_html(html):
    """
    Parses Goodreads book page HTML and extracts details.
    Uses Next.js __NEXT_DATA__ block first, then falls back to standard DOM scraping.
    """
    soup = BeautifulSoup(html, "lxml")
    
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

    # 1. Try parsing Next.js __NEXT_DATA__ first (contains clean metadata, complete genres, and reviews)
    next_data_script = soup.find("script", id="__NEXT_DATA__")
    if next_data_script:
        try:
            data = json.loads(next_data_script.string)
            apollo_state = data.get("props", {}).get("pageProps", {}).get("apolloState", {})
            
            # Find Book and Work keys in Apollo State
            book_key = next((k for k in apollo_state if k.startswith("Book:")), None)
            work_key = next((k for k in apollo_state if k.startswith("Work:")), None)
            
            if book_key:
                book_info = apollo_state[book_key]
                title = book_info.get("title")
                
                # Get the plain text description if available
                desc = book_info.get('description({"stripped":true})')
                if not desc:
                    desc_html = book_info.get("description")
                    if desc_html:
                        desc = clean_html(desc_html)
                
                # Get language
                details = book_info.get("details", {})
                if isinstance(details, dict):
                    lang_obj = details.get("language")
                    if isinstance(lang_obj, dict):
                        language = lang_obj.get("name")
                
                # Get all genres
                book_genres = book_info.get("bookGenres", [])
                for bg in book_genres:
                    if isinstance(bg, dict) and "genre" in bg:
                        g_info = bg["genre"]
                        if isinstance(g_info, dict) and "name" in g_info:
                            genres.append(g_info["name"])
            
            if work_key:
                work_info = apollo_state[work_key]
                stats = work_info.get("stats", {})
                if isinstance(stats, dict):
                    point = stats.get("averageRating", 0.0)
                    ratings_count = stats.get("ratingsCount", 0)
                    reviews_count = stats.get("textReviewsCount", 0)
            
            # Find currently reading & want to read from Apollo State
            for k, val in apollo_state.items():
                if isinstance(val, dict) and val.get("__typename") == "SocialSignal":
                    name = val.get("name")
                    count = val.get("count", 0)
                    if name == "CURRENTLY_READING":
                        currently_reading = count
                    elif name == "TO_READ":
                        want_to_read = count
            
            # Extract the 10 best reviews
            root_query = apollo_state.get("ROOT_QUERY", {})
            get_reviews_key = next((k for k in root_query if k.startswith("getReviews")), None)
            if get_reviews_key:
                edges = root_query[get_reviews_key].get("edges", [])
                for edge in edges[:10]:
                    node_ref = edge.get("node", {}).get("__ref")
                    if node_ref and node_ref in apollo_state:
                        rev_info = apollo_state[node_ref]
                        
                        # Resolve creator (author)
                        author_name = "Anonymous"
                        author_url = None
                        creator_ref = rev_info.get("creator", {}).get("__ref")
                        if creator_ref and creator_ref in apollo_state:
                            author_info = apollo_state[creator_ref]
                            author_name = author_info.get("name", "Anonymous")
                            author_url = author_info.get("webUrl")
                            
                        # Clean up review text HTML
                        raw_text = rev_info.get("text", "")
                        clean_text = clean_html(raw_text)
                        
                        # Parse review creation date
                        created_at_ms = rev_info.get("createdAt")
                        date_str = None
                        if created_at_ms:
                            try:
                                date_str = datetime.fromtimestamp(created_at_ms / 1000).strftime('%Y-%m-%d')
                            except Exception:
                                pass
                                
                        reviews_list.append({
                            "Author": author_name,
                            "AuthorUrl": author_url,
                            "Rating": rev_info.get("rating"),
                            "Likes": rev_info.get("likeCount", 0),
                            "Date": date_str,
                            "Spoiler": rev_info.get("spoilerStatus", False),
                            "Text": clean_text
                        })
        except Exception as e:
            logger.debug(f"Error parsing Next.js block: {e}")

    # 2. Fallbacks / HTML selectors for Title
    if not title:
        title_el = soup.find("h1", {"data-testid": "bookTitle"})
        if title_el:
            title = title_el.text.strip()
        else:
            meta_title = soup.find("meta", {"property": "og:title"})
            if meta_title:
                title = meta_title.get("content", "").strip()
            else:
                h1 = soup.find("h1")
                if h1:
                    title = h1.text.strip()
                elif soup.title:
                    title = soup.title.text.strip()

    # 3. Fallbacks / HTML selectors for Description
    if not desc:
        desc_el = soup.find("div", {"data-testid": "description"})
        if desc_el:
            formatted_div = desc_el.find(class_="Formatted")
            if formatted_div:
                desc = formatted_div.text.strip()
            else:
                desc = desc_el.text.strip()
        
        if not desc:
            meta_desc = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta_desc:
                desc = meta_desc.get("content", "").strip()

    # 4. Fallbacks / HTML selectors for Genres
    if not genres:
        genre_links = soup.find_all("a", href=lambda href: href and "/genres/" in href)
        seen_genres = []
        for link in genre_links:
            g_text = link.text.strip()
            if g_text and g_text not in ["...more", "More"] and g_text not in seen_genres:
                seen_genres.append(g_text)
        genres = seen_genres

    # 5. Fallbacks / HTML selectors for Point (ratingValue)
    if not point or point == 0.0:
        rating_val_el = soup.find("div", {"class": "RatingStatistics__rating"})
        if rating_val_el:
            try:
                point = float(rating_val_el.text.strip())
            except ValueError:
                pass
        if not point or point == 0.0:
            rating_val_el = soup.find("span", {"itemprop": "ratingValue"})
            if rating_val_el:
                try:
                    point = float(rating_val_el.text.strip())
                except ValueError:
                    pass

    # 6. Fallbacks / HTML selectors for counts
    if not ratings_count or ratings_count == 0:
        ratings_el = soup.find("span", {"data-testid": "ratingsCount"})
        if ratings_el:
            digits = re.sub(r'\D', '', ratings_el.text)
            ratings_count = int(digits) if digits else 0

    if not reviews_count or reviews_count == 0:
        reviews_el = soup.find("span", {"data-testid": "reviewsCount"})
        if reviews_el:
            digits = re.sub(r'\D', '', reviews_el.text)
            reviews_count = int(digits) if digits else 0

    if not currently_reading or currently_reading == 0:
        cr_el = soup.find("div", {"data-testid": "currentlyReadingSignal"})
        if cr_el:
            digits = re.sub(r'\D', '', cr_el.text)
            currently_reading = int(digits) if digits else 0

    if not want_to_read or want_to_read == 0:
        tr_el = soup.find("div", {"data-testid": "toReadSignal"})
        if tr_el:
            digits = re.sub(r'\D', '', tr_el.text)
            want_to_read = int(digits) if digits else 0

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
        "WantToReadCount": want_to_read
    }

def save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns):
    """Saves checkpoint data containing failed, duplicate, and non-English ISBNs atomically."""
    temp_dir = os.path.dirname(os.path.abspath(checkpoint_file))
    try:
        with tempfile.NamedTemporaryFile('w', dir=temp_dir, delete=False, encoding='utf-8') as tf:
            json.dump({
                "failed_isbns": list(failed_isbns),
                "duplicate_isbns": list(duplicate_isbns),
                "non_english_isbns": list(non_english_isbns)
            }, tf, ensure_ascii=False, indent=4)
            temp_name = tf.name
        if os.path.exists(checkpoint_file):
            os.replace(temp_name, checkpoint_file)
        else:
            os.rename(temp_name, checkpoint_file)
    except Exception as e:
        logger.error(f"Error saving checkpoint: {e}")
        if 'temp_name' in locals() and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except Exception:
                pass

def save_book_data(book, json_file, csv_file):
    """Saves book data to both JSON and CSV files atomically and efficiently."""
    # 1. Update JSON list efficiently: O(1) append for large files, fallback to standard update for small/non-existent files
    if not os.path.exists(json_file) or os.path.getsize(json_file) < 1000:
        books = []
        if os.path.exists(json_file):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    books = json.load(f, strict=False)
            except Exception as e:
                logger.error(f"Error reading JSON file {json_file}: {e}")
                
        books.append(book)
        
        temp_dir = os.path.dirname(os.path.abspath(json_file))
        try:
            with tempfile.NamedTemporaryFile('w', dir=temp_dir, delete=False, encoding='utf-8') as tf:
                json.dump(books, tf, ensure_ascii=False, indent=4)
                temp_name = tf.name
            if os.path.exists(json_file):
                os.replace(temp_name, json_file)
            else:
                os.rename(temp_name, json_file)
        except Exception as e:
            logger.error(f"Error saving book to JSON file: {e}")
            if 'temp_name' in locals() and os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except Exception:
                    pass
    else:
        # File exists and is sufficiently large. Open in r+b mode to append in O(1) time
        try:
            with open(json_file, 'r+b') as f:
                f.seek(0, os.SEEK_END)
                pos = f.tell()
                
                # Search backwards for the closing bracket ']'
                found = False
                while pos > 0:
                    pos -= 1
                    f.seek(pos)
                    char = f.read(1)
                    if char == b']':
                        found = True
                        break
                
                if found:
                    book_str = json.dumps(book, ensure_ascii=False, indent=4)
                    indented_book_str = "\n".join("    " + line for line in book_str.splitlines())
                    
                    f.seek(pos)
                    f.write(b',\n')
                    new_content = (indented_book_str + "\n]").encode('utf-8')
                    f.write(new_content)
                    f.truncate()
                else:
                    # If for some reason we didn't find ']', fallback to standard loading
                    logger.warning(f"Closing bracket ']' not found in {json_file}. Falling back to full rewrite.")
                    with open(json_file, 'r', encoding='utf-8') as f:
                        books = json.load(f, strict=False)
                    books.append(book)
                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(books, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Error appending book to JSON file in O(1) mode: {e}")

    # 2. Append to CSV file
    csv_exists = os.path.exists(csv_file)
    try:
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not csv_exists:
                writer.writerow(["ISBN", "Title", "Desc", "Genre", "Review", "Point", "Language", "RatingsCount", "ReviewsCount", "CurrentlyReadingCount", "WantToReadCount"])
            
            # Serialize complex structures to JSON strings in CSV cells
            genre_str = json.dumps(book["Genre"], ensure_ascii=False)
            review_str = json.dumps(book["Review"], ensure_ascii=False)
            
            writer.writerow([
                book["ISBN"],
                book["Title"],
                book["Desc"],
                genre_str,
                review_str,
                book["Point"],
                book.get("Language", ""),
                book.get("RatingsCount", 0),
                book.get("ReviewsCount", 0),
                book.get("CurrentlyReadingCount", 0),
                book.get("WantToReadCount", 0)
            ])
    except Exception as e:
        logger.error(f"Error appending book to CSV file: {e}")

class LocalProxyRelay:
    def __init__(self, listen_host, listen_port, upstream_host, upstream_port, username, password):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.auth_header = b"Proxy-Authorization: Basic " + base64.b64encode(f"{username}:{password}".encode()).strip() + b"\r\n"
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.listen_host, self.listen_port))
        self.server_socket.listen(100)
        self.running = True
        
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def run(self):
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                t = threading.Thread(target=self.handle_client, args=(client_sock,))
                t.daemon = True
                t.start()
            except Exception:
                break

    def handle_client(self, client_sock):
        try:
            req = client_sock.recv(4096)
            if not req:
                client_sock.close()
                return
            
            if req.startswith(b"CONNECT"):
                lines = req.split(b"\r\n")
                connect_line = lines[0].decode()
                match = re.match(r"CONNECT\s+([^:]+):(\d+)", connect_line, re.IGNORECASE)
                if match:
                    dest_host, dest_port = match.groups()
                    
                    upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    upstream_sock.connect((self.upstream_host, self.upstream_port))
                    
                    connect_req = f"CONNECT {dest_host}:{dest_port} HTTP/1.1\r\n".encode()
                    connect_req += self.auth_header
                    connect_req += b"\r\n"
                    upstream_sock.sendall(connect_req)
                    
                    resp = upstream_sock.recv(4096)
                    if b"200" in resp or b"established" in resp.lower():
                        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                        self.pipe(client_sock, upstream_sock)
                    else:
                        client_sock.sendall(resp)
                        client_sock.close()
                        upstream_sock.close()
            else:
                upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                upstream_sock.connect((self.upstream_host, self.upstream_port))
                
                parts = req.split(b"\r\n\r\n", 1)
                new_req = parts[0] + b"\r\n" + self.auth_header + b"\r\n"
                if len(parts) > 1:
                    new_req += parts[1]
                upstream_sock.sendall(new_req)
                
                self.pipe(client_sock, upstream_sock)
        except Exception:
            try:
                client_sock.close()
            except Exception:
                pass

    def pipe(self, sock1, sock2):
        inputs = [sock1, sock2]
        while self.running:
            try:
                readable, _, exceptional = select.select(inputs, [], inputs, 10)
                if exceptional:
                    break
                if not readable:
                    break
                for s in readable:
                    data = s.recv(4096)
                    if not data:
                        return
                    other = sock2 if s is sock1 else sock1
                    other.sendall(data)
            except Exception:
                break
        try: sock1.close()
        except Exception: pass
        try: sock2.close()
        except Exception: pass

    def close(self):
        self.running = False
        try:
            self.server_socket.close()
        except Exception:
            pass

def worker(thread_id, isbns_to_process, total_to_process, scraped_titles, failed_isbns, duplicate_isbns, non_english_isbns,
           lock, json_file, csv_file, checkpoint_file, global_state, shutdown_event,
           proxy=None, delay_min=3.0, delay_max=6.0, headless=False):
    """
    Worker thread function for scraping Goodreads books by ISBN.
    """
    relay = None
    co = ChromiumOptions()
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--disk-cache-size=1')
    co.set_argument('--media-cache-size=1')
    co.set_argument('--disable-software-rasterizer')
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_argument('--proxy-bypass-list=127.0.0.1;localhost;<-loopback>')
    co.set_argument('--blink-settings=imagesEnabled=false')
    
    if proxy:
        # Check if proxy contains username and password
        # Format: scheme://username:password@ip:port
        match = re.match(r"^(https?|socks5)://([^:]+):([^@]+)@([^:]+):(\d+)$", proxy)
        if match:
            scheme, username, password, host, port = match.groups()
            port = int(port)
            listen_port = 18000 + thread_id
            try:
                relay = LocalProxyRelay("127.0.0.1", listen_port, host, port, username, password)
                clean_proxy = f"http://127.0.0.1:{listen_port}"
                co.set_proxy(clean_proxy)
                logger.info(f"[Thread-{thread_id}] Started Local Proxy Relay on http://127.0.0.1:{listen_port} pointing to {host}:{port}")
            except Exception as e:
                logger.error(f"[Thread-{thread_id}] Failed to start Local Proxy Relay: {e}")
        else:
            co.set_proxy(proxy)
            logger.info(f"[Thread-{thread_id}] Using proxy: {proxy}")
    
    # Stagger window position to organize them on screen
    window_x = 2000 + (thread_id * 100)
    window_y = 2000 + (thread_id * 100)
    co.set_argument(f'--window-position={window_x},{window_y}')
    
    co.auto_port()
    if headless:
        co.set_argument('--headless=new')
    else:
        co.headless(False)

    logger.info(f"[Thread-{thread_id}] Initializing ChromiumPage...")
    try:
        page = ChromiumPage(co)
    except Exception as e:
        logger.error(f"[Thread-{thread_id}] Failed to initialize ChromiumPage: {e}")
        return

    try:
        while not shutdown_event.is_set():
            # Thread-safe pop of next ISBN
            with lock:
                if not isbns_to_process:
                    break
                isbn = isbns_to_process.pop(0)
                global_state["processed_so_far"] += 1
                idx = global_state["processed_so_far"]

            logger.info(f"[Thread-{thread_id}] [{idx}/{total_to_process}] Processing ISBN: {isbn}")
            
            # Retry mechanism
            max_retries = 3
            success = False
            is_waf_blocked = False
            
            for attempt in range(max_retries):
                if shutdown_event.is_set():
                    break
                try:
                    search_url = f"https://www.goodreads.com/search?q={isbn}"
                    page.get(search_url, timeout=15)
                    
                    # WAF Challenge Detection and Wait Loop
                    start_time = time.time()
                    redirected = False
                    not_found = False
                    
                    while time.time() - start_time < 12:
                        if shutdown_event.is_set():
                            break
                        current_url = page.url
                        current_title = page.title
                        
                        # 0. Detect 403 Forbidden / Access Denied block on search page
                        if "403 Forbidden" in current_title or current_title == "Access Denied" or "403 Forbidden" in page.html:
                            is_waf_blocked = True
                            break
                        
                        # 1. Check if redirected to the book details page
                        if "/book/show/" in current_url:
                            redirected = True
                            break
                        
                        # 2. Check if staying on search results indicating no books found by title first
                        if "showing 1-0 of 0 books" in current_title:
                            not_found = True
                            break
                        
                        # Fetch page.html lazily only when needed
                        current_html = page.html
                        if "No results" in current_html:
                            not_found = True
                            break
                            
                        # 3. Check if challenged by AWS WAF
                        if "AwsWafIntegration" in current_html or "challenge.js" in current_html:
                            logger.info(f"[Thread-{thread_id}] AWS WAF Challenge page detected. Waiting for browser to solve...")
                            time.sleep(1.0)
                            continue
                            
                        # 4. If the page is fully loaded and not in a WAF challenge, exit early
                        if not page.states.is_loading:
                            break

                        # Standard sleep between checks
                        time.sleep(0.5)

                    if shutdown_event.is_set():
                        break

                    if is_waf_blocked:
                        break

                    if redirected:
                        # Parse page details
                        book_data = parse_goodreads_html(page.html)
                        
                        # Ensure we extracted a title
                        title = book_data.get("Title")
                        if not title:
                            # Try parsing once more after a small delay
                            time.sleep(1)
                            book_data = parse_goodreads_html(page.html)
                            title = book_data.get("Title")
                            
                        if title:
                            # Detect block inside the parsed title
                            if "403 Forbidden" in title or title.strip() == "403 Forbidden":
                                is_waf_blocked = True
                                break

                            # Language Check: Only crawl English books
                            language = book_data.get("Language")
                            if language and language != "English":
                                logger.info(f"[Thread-{thread_id}] Book '{title}' for ISBN {isbn} is in language '{language}'. Skipping save.")
                                with lock:
                                    non_english_isbns.add(isbn)
                                    save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns)
                                success = True
                                break

                            title_clean = title.strip().lower()
                            point = book_data.get("Point", 0.0)
                            reviews = book_data.get("Review", [])

                            # Check for 0 point and 0 reviews
                            if (point == 0.0 or not point) and len(reviews) == 0:
                                logger.info(f"[Thread-{thread_id}] Book '{title}' for ISBN {isbn} has 0 point and 0 reviews. Skipping save.")
                                with lock:
                                    failed_isbns.add(isbn)
                                    save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns)
                                success = True
                                break

                            # Thread-safe check for duplicate title
                            with lock:
                                is_duplicate = title_clean in scraped_titles
                                if is_duplicate:
                                    duplicate_isbns.add(isbn)
                                else:
                                    scraped_titles.add(title_clean)

                            if is_duplicate:
                                logger.info(f"[Thread-{thread_id}] Duplicate title found: '{title}' for ISBN {isbn}. Skipping write.")
                                with lock:
                                    save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns)
                                success = True
                                break
                            else:
                                book_data["ISBN"] = isbn
                                with lock:
                                    save_book_data(book_data, json_file, csv_file)
                                logger.info(f"[Thread-{thread_id}] Scraped and Saved: '{title}' (Point: {book_data['Point']})")
                                success = True
                                break
                        else:
                            logger.warning(f"[Thread-{thread_id}] Redirected to book page but failed to parse title for ISBN {isbn} (Attempt {attempt+1}/{max_retries})")
                            
                    elif not_found:
                        logger.info(f"[Thread-{thread_id}] ISBN {isbn} not found on Goodreads (No results).")
                        with lock:
                            failed_isbns.add(isbn)
                            save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns)
                        success = True
                        break
                        
                    else:
                        logger.warning(f"[Thread-{thread_id}] Timeout/No redirect happened for ISBN {isbn} (Attempt {attempt+1}/{max_retries})")
                        
                except Exception as e:
                    logger.error(f"[Thread-{thread_id}] Error processing ISBN {isbn} (Attempt {attempt+1}/{max_retries}): {e}")
                    
                # Backoff delay before retry
                if not success and attempt < max_retries - 1:
                    sleep_time = (attempt + 1) * 5
                    logger.info(f"[Thread-{thread_id}] Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
            
            # If we were WAF blocked, requeue this ISBN and request shutdown
            if is_waf_blocked:
                logger.error(f"[Thread-{thread_id}] Cloudflare/WAF block (403 Forbidden) detected for ISBN {isbn}. Requeuing ISBN and stopping scraper.")
                with lock:
                    isbns_to_process.insert(0, isbn)
                    global_state["processed_so_far"] -= 1
                shutdown_event.set()
                break

            # If all retries failed and not successful, add to failed list (only if not blocked)
            if not success and not shutdown_event.is_set():
                logger.error(f"[Thread-{thread_id}] All retries failed for ISBN {isbn}. Skipping and saving to checkpoint.")
                with lock:
                    failed_isbns.add(isbn)
                    save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns)

            # Polite delay between books to prevent IP bans
            if not shutdown_event.is_set():
                time.sleep(random.uniform(delay_min, delay_max))

    except Exception as e:
        logger.error(f"[Thread-{thread_id}] Unhandled worker error: {e}")
    finally:
        logger.info(f"[Thread-{thread_id}] Closing ChromiumPage...")
        try:
            page.quit()
        except Exception:
            pass
        if relay:
            try:
                relay.close()
                logger.info(f"[Thread-{thread_id}] Closed Local Proxy Relay.")
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser(description="Goodreads Scraper with Multi-threading")
    parser.add_argument("--threads", type=int, default=4, help="Number of parallel threads/browsers to use")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy server address (e.g. http://username:password@ip:port)")
    parser.add_argument("--delay-min", type=float, default=3.0, help="Minimum delay between books in seconds")
    parser.add_argument("--delay-max", type=float, default=6.0, help="Maximum delay between books in seconds")
    parser.add_argument("--headless", type=str, default="False", help="Run Chrome in headless mode ('True' or 'False')")
    
    args, unknown = parser.parse_known_args()
    num_threads = args.threads
    
    # Load proxies from .env or override with command line argument
    proxies = load_proxies_from_env()
    if args.proxy:
        proxies = [args.proxy]
        
    delay_min = args.delay_min
    delay_max = args.delay_max
    headless = args.headless.lower() in ("true", "1", "yes")

    isbn_file = "clean_novel_isbns.txt"
    json_file = "goodreads_books.json"
    csv_file = "goodreads_books.csv"
    checkpoint_file = "goodreads_checkpoint.json"

    # 1. Load checkpoints and existing data
    successful_isbns = set()
    scraped_titles = set()
    failed_isbns = set()
    duplicate_isbns = set()
    non_english_isbns = set()
    
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                chk = json.load(f, strict=False)
                failed_isbns = set(chk.get("failed_isbns", []))
                duplicate_isbns = set(chk.get("duplicate_isbns", []))
                non_english_isbns = set(chk.get("non_english_isbns", []))
            logger.info(f"Resumed: {len(failed_isbns)} failed ISBNs, {len(duplicate_isbns)} duplicate ISBNs, {len(non_english_isbns)} non-English ISBNs loaded.")
        except Exception as e:
            logger.error(f"Failed to load checkpoint file {checkpoint_file}: {e}")

    # Load and clean existing JSON data (removing non-English books and 0 ratings/reviews books)
    cleaned_books = []
    removed_count = 0
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                books = json.load(f, strict=False)
            
            for book in books:
                point = book.get("Point", 0.0)
                reviews = book.get("Review", [])
                isbn = book.get("ISBN", "")
                language = book.get("Language")
                
                is_zero_ratings = (point == 0.0 or not point) and len(reviews) == 0
                
                is_non_english = False
                if language:
                    if language != "English":
                        is_non_english = True
                else:
                    if isbn and not is_english_isbn(isbn):
                        is_non_english = True
                
                if is_zero_ratings or is_non_english:
                    removed_count += 1
                    if isbn:
                        if is_non_english:
                            non_english_isbns.add(isbn)
                        else:
                            failed_isbns.add(isbn)
                else:
                    if not book.get("Language") and isbn and is_english_isbn(isbn):
                        book["Language"] = "English"
                    cleaned_books.append(book)
                    if isbn:
                        successful_isbns.add(isbn)
                    if book.get("Title"):
                        scraped_titles.add(book["Title"].strip().lower())
            
            logger.info(f"Loaded {len(books)} books from {json_file}. Removed {removed_count} books (non-English or 0 ratings/reviews).")
            
            if removed_count > 0:
                logger.info(f"Writing {len(cleaned_books)} cleaned books back to existing dataset...")
                # Write cleaned JSON
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(cleaned_books, f, ensure_ascii=False, indent=4)
                
                # Re-write CSV
                if os.path.exists(csv_file):
                    try:
                        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow(["ISBN", "Title", "Desc", "Genre", "Review", "Point", "Language", "RatingsCount", "ReviewsCount", "CurrentlyReadingCount", "WantToReadCount"])
                            for book in cleaned_books:
                                genre_str = json.dumps(book["Genre"], ensure_ascii=False)
                                review_str = json.dumps(book["Review"], ensure_ascii=False)
                                writer.writerow([
                                    book["ISBN"],
                                    book["Title"],
                                    book["Desc"],
                                    genre_str,
                                    review_str,
                                    book["Point"],
                                    book.get("Language", ""),
                                    book.get("RatingsCount", 0),
                                    book.get("ReviewsCount", 0),
                                    book.get("CurrentlyReadingCount", 0),
                                    book.get("WantToReadCount", 0)
                                ])
                        logger.info(f"Re-wrote cleaned CSV file: {csv_file}")
                    except Exception as e:
                        logger.error(f"Error rewriting CSV file during cleanup: {e}")
                
                # Update checkpoint
                save_checkpoint(checkpoint_file, failed_isbns, duplicate_isbns, non_english_isbns)
                
        except Exception as e:
            logger.error(f"Failed to load/clean existing JSON file {json_file}: {e}")

    # Union of all processed ISBNs
    processed_isbns = successful_isbns.union(failed_isbns).union(duplicate_isbns).union(non_english_isbns)

    # Load ISBNs from txt file (filtering by is_english_isbn to only crawl English books)
    if not os.path.exists(isbn_file):
        logger.error(f"ISBN source file {isbn_file} does not exist. Please place it in the same directory.")
        return

    isbns_to_process = []
    skipped_non_english_count = 0
    with open(isbn_file, 'r', encoding='utf-8') as f:
        for line in f:
            isbn = line.strip()
            if isbn and isbn not in processed_isbns:
                if is_english_isbn(isbn):
                    isbns_to_process.append(isbn)
                else:
                    skipped_non_english_count += 1

    total_all = len(processed_isbns) + len(isbns_to_process) + skipped_non_english_count
    logger.info(f"Starting Scraper. Total ISBNs: {total_all}. Already processed: {len(processed_isbns)}. Remaining English: {len(isbns_to_process)}. Skipped non-English: {skipped_non_english_count}")

    if not isbns_to_process:
        logger.info("All English ISBNs have already been processed.")
        return

    # 2. Setup threading and spawn workers
    lock = threading.Lock()
    shutdown_event = threading.Event()
    global_state = {"processed_so_far": 0}
    total_to_process = len(isbns_to_process)

    logger.info(f"Spawning {num_threads} worker threads...")
    threads = []
    for i in range(num_threads):
        thread_proxy = proxies[i % len(proxies)] if proxies else None
        t = threading.Thread(
            target=worker,
            args=(
                i + 1,
                isbns_to_process,
                total_to_process,
                scraped_titles,
                failed_isbns,
                duplicate_isbns,
                non_english_isbns,
                lock,
                json_file,
                csv_file,
                checkpoint_file,
                global_state,
                shutdown_event,
                thread_proxy,
                delay_min,
                delay_max,
                headless
            )
        )
        t.daemon = True
        threads.append(t)
        t.start()
        time.sleep(2.0)  # Stagger browser startup to avoid conflicts

    try:
        # Wait for all threads to finish
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("\nScraping process interrupted by user. Initiating shutdown of worker threads...")
        shutdown_event.set()
        # Wait up to 5 seconds for threads to exit
        for t in threads:
            t.join(timeout=5.0)
    finally:
        logger.info("Process finished.")

if __name__ == "__main__":
    main()