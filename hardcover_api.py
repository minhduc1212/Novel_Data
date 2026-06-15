import requests
import json
import sys
import os
import csv
import time
import argparse
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# Fix console encoding on Windows to prevent UnicodeEncodeErrors
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Endpoint của Hardcover API
url = 'https://api.hardcover.app/v1/graphql'

# Token cá nhân của bạn
HARDCOVER_API_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJIYXJkY292ZXIiLCJ2ZXJzaW9uIjoiOCIsImp0aSI6IjY3MmQzODY2LTY5YzgtNGE2YS05OTgyLTUxOWY4NzVhMmNjMCIsImFwcGxpY2F0aW9uSWQiOjIsInN1YiI6IjExNDM3NCIsImF1ZCI6IjEiLCJpZCI6IjExNDM3NCIsImxvZ2dlZEluIjp0cnVlLCJpYXQiOjE3ODE1MjcyNTcsImV4cCI6MTgxMzA2MzI1NywiaHR0cHM6Ly9oYXN1cmEuaW8vand0L2NsYWltcyI6eyJ4LWhhc3VyYS1hbGxvd2VkLXJvbGVzIjpbInVzZXIiXSwieC1oYXN1cmEtZGVmYXVsdC1yb2xlIjoidXNlciIsIngtaGFzdXJhLXJvbGUiOiJ1c2VyIiwiWC1oYXN1cmEtdXNlci1pZCI6IjExNDM3NCJ9LCJ1c2VyIjp7ImlkIjoxMTQzNzR9fQ.-jT7DzVdevja2Zd6y1gToH0cVb3aiIOE-g5hJ0EIe5M"

# Khởi tạo logger
logger = logging.getLogger("hardcover_crawler")
logger.setLevel(logging.INFO)

# Import hoặc định nghĩa bộ lọc thể loại từ goodreads_genres
try:
    from goodreads_genres import BLACKLIST_KEYWORDS, SHELF_CLASSIFICATION
except ImportError:
    BLACKLIST_KEYWORDS = [
        'read', 'own', 'default', 'wish', 'give', 'gave', 'finish', 'dnf', 
        'abandon', 'hold', 'maybe', 'library', 'kindle', 'calibre', 'audible', 
        'e-book', 'ebook', 'favour', 'favor', 'fave', 'favs', 'have', 'tbr', 
        'recommend', 'series', 'english', 'british', 'canadian', 'american', 
        'german', 'french', 'spanish', 'translat', 'novel', 'book', 'audio', 
        'shelf', 'shelves', 'buy', 'purchase', 'borrow', 'list', 'queue', 
        'progress', 'status', 'start', 'end', 'year', 'month', 'date', 'star',
        'rating', 'review', 'club', 'group', 'collection', 'mine', 'personal',
        'physical', 'paperback', 'hardcover', 'hardback', 'tome', 'format',
        'copy', 'copies', 'pile', 'stack', 'current', 'keep', 'track', 'goal',
        'challenge', 'select', 'pick', 'choice', 'chose', 'author', 'writer',
        'illustrator', 'page', 'pages', 'chapter', 'chapters', 'pub', 'print',
        'edition', 'cover', 'arc', 'nook', 'netgalley', 'stand-alone', 'standalone',
        'amazon', 'freebie', 'free', 'to-get', 'want', 'other', 'not-interested'
    ]
    SHELF_CLASSIFICATION = {
        'fantasy': ('genres', 'fantasy'),
        'fantasía': ('genres', 'fantasy'),
        'fantasia': ('genres', 'fantasy'),
        'urban-fantasy': ('genres', 'urban fantasy'),
        'dark-fantasy': ('genres', 'dark fantasy'),
        'military-fantasy': ('genres', 'military fantasy'),
        'high-fantasy': ('genres', 'high fantasy'),
        'epic-fantasy': ('genres', 'epic fantasy'),
        'fantasy-epic': ('genres', 'epic fantasy'),
        'adult-fantasy': ('genres', 'adult fantasy'),
        'historical-fantasy': ('genres', 'historical fantasy'),
        'sci-fi': ('genres', 'science fiction'),
        'science-fiction': ('genres', 'science fiction'),
        'scifi': ('genres', 'science fiction'),
        'sff': ('genres', 'sci-fi & fantasy'),
        'sci-fi-fantasy': ('genres', 'sci-fi & fantasy'),
        'scifi-fantasy': ('genres', 'sci-fi & fantasy'),
        'science-fiction-fantasy': ('genres', 'sci-fi & fantasy'),
        'fantasy-sci-fi': ('genres', 'sci-fi & fantasy'),
        'fantasy-scifi': ('genres', 'sci-fi & fantasy'),
        'sf-fantasy': ('genres', 'sci-fi & fantasy'),
        'sci-fi-and-fantasy': ('genres', 'sci-fi & fantasy'),
        'fiction': ('genres', 'fiction'),
        'general-fiction': ('genres', 'general fiction'),
        'contemporary-fiction': ('genres', 'contemporary fiction'),
        'literary-fiction': ('genres', 'literary fiction'),
        'classics': ('genres', 'classics'),
        'classic': ('genres', 'classics'),
        'contemporary': ('genres', 'contemporary'),
        'mystery': ('genres', 'mystery'),
        'mysteries': ('genres', 'mystery'),
        'detective': ('genres', 'mystery'),
        'mystery-thriller': ('genres', 'mystery'),
        'mystery-suspense': ('genres', 'mystery'),
        'mystery-crime': ('genres', 'mystery'),
        'thriller': ('genres', 'thriller'),
        'thrillers': ('genres', 'thriller'),
        'suspense': ('genres', 'thriller'),
        'crime': ('genres', 'crime'),
        'crime-fiction': ('genres', 'crime'),
        'romance': ('genres', 'romance'),
        'romantic': ('genres', 'romance'),
        'historical-romance': ('genres', 'historical romance'),
        'paranormal-romance': ('genres', 'paranormal romance'),
        'contemporary-romance': ('genres', 'contemporary romance'),
        'erotica': ('genres', 'erotica'),
        'horror': ('genres', 'horror'),
        'gothic': ('genres', 'horror'),
        'adventure': ('genres', 'adventure'),
        'action': ('genres', 'adventure'),
        'action-adventure': ('genres', 'adventure'),
        'historical-fiction': ('genres', 'historical fiction'),
        'historical': ('genres', 'historical fiction'),
        'history': ('genres', 'history'),
        'biography': ('genres', 'biography'),
        'memoir': ('genres', 'memoir'),
        'autobiography': ('genres', 'biography'),
        'non-fiction': ('genres', 'non-fiction'),
        'nonfiction': ('genres', 'non-fiction'),
        'young-adult': ('audiences', 'young adult'),
        'ya': ('audiences', 'young adult'),
        'teen': ('audiences', 'young adult'),
        'youth': ('audiences', 'young adult'),
        'ya-fiction': ('audiences', 'young adult'),
        'middle-grade': ('audiences', 'middle grade'),
        'children': ('audiences', 'children'),
        'childrens': ('audiences', 'children'),
        'kids': ('audiences', 'children'),
        'new-adult': ('audiences', 'new adult'),
        'adult': ('audiences', 'adult'),
        'short-stories': ('audiences', 'short stories'),
        'graphic-novel': ('audiences', 'graphic novel'),
        'manga': ('audiences', 'manga'),
        'comic': ('audiences', 'comics'),
        'comics': ('audiences', 'comics')
    }


def clean_tags(raw_tags, raw_genres):
    """Lọc danh sách thể loại và nhãn (tags) qua Blacklist và Classification."""
    cleaned = []
    
    # Xử lý genres
    for g in raw_genres:
        if not g:
            continue
        g_clean = g.strip()
        g_lower = g_clean.lower().replace(" ", "-")
        # Kiểm tra blacklist
        if any(bl in g_lower for bl in BLACKLIST_KEYWORDS):
            continue
        # Kiểm tra bản đồ phân loại
        if g_lower in SHELF_CLASSIFICATION:
            cat, val = SHELF_CLASSIFICATION[g_lower]
            cleaned.append(val.title())
        else:
            cleaned.append(g_clean)
            
    # Xử lý tags
    for t in raw_tags:
        if not t:
            continue
        t_clean = t.strip()
        t_lower = t_clean.lower().replace(" ", "-")
        # Kiểm tra blacklist
        if any(bl in t_lower for bl in BLACKLIST_KEYWORDS):
            continue
        # Kiểm tra bản đồ phân loại
        if t_lower in SHELF_CLASSIFICATION:
            cat, val = SHELF_CLASSIFICATION[t_lower]
            cleaned.append(val.title())
        else:
            cleaned.append(t_clean)
            
    # Loại bỏ trùng lặp và giữ nguyên thứ tự
    seen = set()
    result = []
    for item in cleaned:
        item_lower = item.lower()
        if item_lower not in seen:
            seen.add(item_lower)
            result.append(item)
            
    return result


def setup_logging(to_file_only=False):
    """Cấu hình handlers cho logger."""
    logger.handlers = []
    
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    
    # Handler lưu file log
    file_handler = logging.FileHandler("hardcover_crawler.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    if not to_file_only:
        # Handler ghi ra console
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)


def parse_book(book):
    """Trích xuất và làm phẳng dữ liệu sách từ API Hardcover."""
    # Trích xuất tác giả
    authors = []
    contributors = book.get('cached_contributors') or []
    for contrib in contributors:
        author_info = contrib.get('author') if isinstance(contrib, dict) else None
        if author_info and isinstance(author_info, dict):
            name = author_info.get('name')
            if name:
                authors.append(name)
                
    # Trích xuất các nhãn phân loại từ cached_tags
    genres = []
    tags = []
    moods = []
    content_warnings = []
    
    cached_tags = book.get('cached_tags') or {}
    if isinstance(cached_tags, dict):
        for g in cached_tags.get('Genre') or []:
            if isinstance(g, dict) and g.get('tag'):
                genres.append(g['tag'])
        for t in cached_tags.get('Tag') or []:
            if isinstance(t, dict) and t.get('tag'):
                tags.append(t['tag'])
        for m in cached_tags.get('Mood') or []:
            if isinstance(m, dict) and m.get('tag'):
                moods.append(m['tag'])
        for cw in cached_tags.get('Content Warning') or []:
            if isinstance(cw, dict) and cw.get('tag'):
                content_warnings.append(cw['tag'])
                
    # Áp dụng bộ lọc làm sạch thể loại
    cleaned_genres = clean_tags(tags, genres)
    
    # Lọc tags thô (loại bỏ từ thuộc blacklist)
    cleaned_tags = [t for t in tags if not any(bl in t.lower() for bl in BLACKLIST_KEYWORDS)]
    
    slug = book.get('slug')
    book_url = f"https://hardcover.app/books/{slug}" if slug else ""
    
    return {
        'id': book.get('id'),
        'title': book.get('title') or "",
        'subtitle': book.get('subtitle') or "",
        'slug': slug or "",
        'authors': authors,
        'genres': cleaned_genres, # Sử dụng danh sách thể loại sạch đã phân loại và lọc blacklist
        'tags': cleaned_tags,
        'moods': moods,
        'content_warnings': content_warnings,
        'rating': book.get('rating'),
        'ratings_count': book.get('ratings_count') or 0,
        'reviews_count': book.get('reviews_count') or 0,
        'pages': book.get('pages'),
        'release_year': book.get('release_year'),
        'release_date': book.get('release_date') or "",
        'activities_count': book.get('activities_count') or 0,
        'book_category_id': book.get('book_category_id') or 0,
        'compilation': book.get('compilation') or False,
        'editions_count': book.get('editions_count') or 0,
        'journals_count': book.get('journals_count') or 0,
        'lists_count': book.get('lists_count') or 0,
        'prompts_count': book.get('prompts_count') or 0,
        'users_count': book.get('users_count') or 0,
        'users_read_count': book.get('users_read_count') or 0,
        'url': book_url,
        'description': book.get('description') or ""
    }


def append_books_to_json(json_file, parsed_books):
    """Ghi thêm danh sách sách vào file JSON một cách hiệu quả (O(1) seek)."""
    if not parsed_books:
        return
    batch_json_str = ",\n".join(json.dumps(book, ensure_ascii=False) for book in parsed_books)
    if not os.path.exists(json_file) or os.path.getsize(json_file) < 10:
        with open(json_file, 'wb') as f:
            f.write(f"[\n{batch_json_str}\n]".encode('utf-8'))
    else:
        try:
            with open(json_file, 'r+b') as f:
                f.seek(0, os.SEEK_END)
                pos = f.tell() - 1
                while pos >= 0:
                    f.seek(pos)
                    ch = f.read(1)
                    if ch == b']':
                        f.seek(pos)
                        f.write((',\n' + batch_json_str + '\n]').encode('utf-8'))
                        f.truncate()
                        break
                    pos -= 1
                else:
                    raise ValueError("Không tìm thấy ký tự đóng ']' trong file JSON")
        except Exception as e:
            logger.error(f"Ghi đè JSON O(1) thất bại ({e}), đang chuyển sang ghi toàn bộ...")
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = []
            existing.extend(parsed_books)
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)


def append_books_to_csv(csv_file, parsed_books):
    """Ghi thêm danh sách sách vào file CSV."""
    if not parsed_books:
        return
    csv_exists = os.path.exists(csv_file) and os.path.getsize(csv_file) > 0
    headers = [
        "id", "title", "subtitle", "slug", "authors", "genres", "tags", "moods", 
        "content_warnings", "rating", "ratings_count", "reviews_count", "pages", 
        "release_year", "release_date", "activities_count", "book_category_id",
        "compilation", "editions_count", "journals_count", "lists_count",
        "prompts_count", "users_count", "users_read_count", "url", "description"
    ]
    with open(csv_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not csv_exists:
            writer.writerow(headers)
        for book in parsed_books:
            writer.writerow([
                book['id'],
                book['title'],
                book['subtitle'],
                book['slug'],
                ", ".join(book['authors']),
                ", ".join(book['genres']),
                ", ".join(book['tags']),
                ", ".join(book['moods']),
                ", ".join(book['content_warnings']),
                book['rating'],
                book['ratings_count'],
                book['reviews_count'],
                book['pages'],
                book['release_year'],
                book['release_date'],
                book['activities_count'],
                book['book_category_id'],
                book['compilation'],
                book['editions_count'],
                book['journals_count'],
                book['lists_count'],
                book['prompts_count'],
                book['users_count'],
                book['users_read_count'],
                book['url'],
                book['description']
            ])


def get_total_books_count(url, headers):
    """Lấy tổng số lượng sách hiện có trong hệ thống Hardcover."""
    query = """
    {
      books_aggregate {
        aggregate {
          count
        }
      }
    }
    """
    try:
        r = requests.post(url, json={'query': query}, headers=headers).json()
        return r['data']['books_aggregate']['aggregate']['count']
    except Exception as e:
        logger.error(f"Không thể lấy tổng số sách từ API: {e}")
        return None


# Event để báo hiệu dừng tất cả các luồng khi nhận được Ctrl+C hoặc lỗi nghiêm trọng
stop_event = threading.Event()


def worker(thread_idx, args, query, headers, end_offset, state, pbar):
    """Hàm chạy cho mỗi luồng cào dữ liệu."""
    url = 'https://api.hardcover.app/v1/graphql'
    
    while not stop_event.is_set():
        # Lấy offset tiếp theo một cách an toàn giữa các luồng
        with state['lock']:
            if state['current_offset'] >= end_offset:
                break
            offset = state['current_offset']
            current_batch = min(args.batch_size, end_offset - offset)
            state['current_offset'] += current_batch
            
        variables = {
            'limit': current_batch,
            'offset': offset
        }
        
        retries = 3
        success = False
        r_data = None
        
        for attempt in range(retries):
            if stop_event.is_set():
                break
            try:
                logger.info(f"[Luồng-{thread_idx}] Đang tải offset {offset} (lần thử {attempt + 1})...")
                response = requests.post(url, json={'query': query, 'variables': variables}, headers=headers, timeout=args.timeout)
                if response.status_code == 200:
                    r_data = response.json()
                    if 'errors' in r_data:
                        logger.warning(f"[Luồng-{thread_idx}] Lỗi GraphQL tại offset {offset}: {r_data['errors']}")
                        time.sleep(3)
                        continue
                    success = True
                    break
                else:
                    logger.warning(f"[Luồng-{thread_idx}] Lỗi HTTP {response.status_code} tại offset {offset}: {response.text}")
                    time.sleep(3)
            except Exception as e:
                logger.warning(f"[Luồng-{thread_idx}] Lỗi mạng tại offset {offset}: {e}")
                time.sleep(3)
                
        if stop_event.is_set():
            break
            
        if not success or not r_data:
            logger.error(f"[Luồng-{thread_idx}] Thất bại liên tiếp tại offset {offset} sau {retries} lần thử.")
            stop_event.set()
            break
            
        books_list = r_data.get('data', {}).get('books', [])
        if not books_list:
            logger.info(f"[Luồng-{thread_idx}] Hết sách để cào tại offset {offset}.")
            with state['lock']:
                state['current_offset'] = end_offset
            break
            
        parsed_batch = [parse_book(b) for b in books_list]
        
        # Ghi vào file đầu ra, được bảo vệ bằng file_lock để tránh race conditions
        with state['file_lock']:
            append_books_to_json(args.output_json, parsed_batch)
            append_books_to_csv(args.output_csv, parsed_batch)
            
        # Cập nhật tiến trình và ghi checkpoint
        with state['lock']:
            state['completed_batches'][offset] = len(books_list)
            # Tịnh tiến checkpoint_offset đến offset chưa hoàn thành nhỏ nhất liên tục
            while state['checkpoint_offset'] in state['completed_batches']:
                batch_len = state['completed_batches'][state['checkpoint_offset']]
                state['checkpoint_offset'] += batch_len
            state['total_fetched'] += len(books_list)
            
            # Ghi checkpoint ra file
            checkpoint_file = 'hardcover_checkpoint.json'
            try:
                with open(checkpoint_file, 'w', encoding='utf-8') as f:
                    json.dump({'offset': state['checkpoint_offset']}, f)
            except Exception as e:
                logger.error(f"Không thể ghi checkpoint: {e}")
                
            pbar.update(len(books_list))
            
        if args.delay > 0:
            time.sleep(args.delay)


def run_crawl(args):
    """Bắt đầu tiến trình cào toàn bộ dữ liệu sách từ Hardcover API."""
    setup_logging(to_file_only=False)
    logger.info("Khởi động tiến trình cào dữ liệu từ Hardcover API...")
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {HARDCOVER_API_TOKEN}'
    }
    
    checkpoint_file = 'hardcover_checkpoint.json'
    start_offset = args.offset
    
    if args.resume and os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                ckpt = json.load(f)
                start_offset = ckpt.get('offset', start_offset)
                logger.info(f"Tìm thấy checkpoint! Sẽ tiếp tục cào từ offset: {start_offset}")
        except Exception as e:
            logger.error(f"Lỗi đọc file checkpoint, bắt đầu từ offset ban đầu {start_offset}: {e}")
            
    total_db_count = get_total_books_count(url, headers)
    if total_db_count is None:
        total_db_count = 2550000
        logger.info(f"Không lấy được tổng số sách từ API, sử dụng ước lượng dự phòng: {total_db_count}")
    else:
        logger.info(f"Tổng số sách trên hệ thống Hardcover: {total_db_count}")
        
    limit = args.limit
    if limit <= 0:
        max_to_fetch = total_db_count - start_offset
        limit = total_db_count
    else:
        max_to_fetch = min(limit, total_db_count - start_offset)
        
    end_offset = start_offset + max_to_fetch
    
    logger.info("Cấu hình cào:")
    logger.info(f"  - Số lượng cần cào: {max_to_fetch} sách")
    logger.info(f"  - Offset bắt đầu: {start_offset}")
    logger.info(f"  - Offset kết thúc: {end_offset}")
    logger.info(f"  - Số luồng (threads): {args.threads}")
    logger.info(f"  - Kích thước batch: {args.batch_size}")
    logger.info(f"  - Thời gian chờ (timeout): {args.timeout}s")
    logger.info(f"  - File JSON: '{args.output_json}'")
    logger.info(f"  - File CSV: '{args.output_csv}'")
    
    # Tạo mới file đầu ra nếu cào lại từ đầu
    if start_offset == 0:
        if os.path.exists(args.output_json):
            os.remove(args.output_json)
        if os.path.exists(args.output_csv):
            os.remove(args.output_csv)
            
    query = """
    query GetBooks($limit: Int!, $offset: Int!) {
      books(limit: $limit, offset: $offset, order_by: {id: asc}) {
        id
        title
        subtitle
        slug
        description
        rating
        ratings_count
        reviews_count
        pages
        release_year
        release_date
        activities_count
        book_category_id
        compilation
        editions_count
        journals_count
        lists_count
        prompts_count
        users_count
        users_read_count
        cached_contributors
        cached_tags
      }
    }
    """
    
    # Trạng thái dùng chung giữa các luồng
    state = {
        'current_offset': start_offset,
        'checkpoint_offset': start_offset,
        'completed_batches': {},  # offset -> length của batch
        'total_fetched': 0,
        'lock': threading.Lock(),
        'file_lock': threading.Lock()
    }
    
    pbar = tqdm(total=max_to_fetch, desc="Đang cào Hardcover API")
    
    global stop_event
    stop_event.clear()
    
    try:
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = []
            for idx in range(1, args.threads + 1):
                futures.append(executor.submit(
                    worker, idx, args, query, headers, end_offset, state, pbar
                ))
            
            # Đợi các luồng hoàn thành và giám sát lỗi
            for future in futures:
                future.result()
                
    except KeyboardInterrupt:
        logger.warning("Nhận tín hiệu dừng (KeyboardInterrupt). Đang yêu cầu các luồng dừng lại...")
        stop_event.set()
    except Exception as e:
        logger.error(f"Lỗi không mong muốn trong quá trình cào: {e}")
        stop_event.set()
    finally:
        pbar.close()
        logger.info("Tiến trình cào đã kết thúc.")
        logger.info(f"  - Tổng số sách đã tải thêm: {state['total_fetched']}")
        logger.info(f"  - Offset đã lưu: {state['checkpoint_offset']}")
        logger.info(f"  - File JSON: '{args.output_json}'")
        logger.info(f"  - File CSV: '{args.output_csv}'")


def main():
    parser = argparse.ArgumentParser(description="Hardcover API Crawler Tool")
    parser.add_argument("-l", "--limit", type=int, default=0, help="Giới hạn số sách cần cào (0 để cào toàn bộ, mặc định: 0)")
    parser.add_argument("-b", "--batch-size", type=int, default=1000, help="Số lượng sách mỗi lượt request (mặc định: 1000)")
    parser.add_argument("-o", "--offset", type=int, default=0, help="Offset bắt đầu cào (mặc định: 0)")
    parser.add_argument("-d", "--delay", type=float, default=0.1, help="Thời gian chờ giữa các request của mỗi luồng (mặc định: 0.1)")
    parser.add_argument("-t", "--threads", type=int, default=4, help="Số lượng luồng cào đồng thời (mặc định: 4)")
    parser.add_argument("--timeout", type=int, default=30, help="Thời gian chờ tối đa cho mỗi request kết nối (mặc định: 30s)")
    parser.add_argument("--output-json", default="hardcover_books.json", help="Tên file JSON đầu ra (mặc định: hardcover_books.json)")
    parser.add_argument("--output-csv", default="hardcover_books.csv", help="Tên file CSV đầu ra (mặc định: hardcover_books.csv)")
    
    # Cho phép tắt chế độ resume nếu cần
    parser.add_argument("--no-resume", action="store_false", dest="resume", help="Không tự động khôi phục từ file checkpoint")
    parser.set_defaults(resume=True)
    
    args = parser.parse_args()
    
    try:
        run_crawl(args)
    except KeyboardInterrupt:
        print("\n[Hủy] Nhận tín hiệu dừng từ bàn phím. Đang dọn dẹp và thoát...")
        stop_event.set()
        sys.exit(0)


if __name__ == "__main__":
    main()