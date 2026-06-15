import os
import sys
import json
import sqlite3
import time
import argparse
import csv

# Default data path in the environment
data_path = "D:\\LT\\data\\goodreads_books.json"

# Comprehensive dictionary mapping common shelf names to standard genres
GENRE_KEYWORDS = {
    # Fantasy, Sci-Fi & Paranormal
    'fantasy': 'fantasy',
    'urban-fantasy': 'fantasy',
    'ya-fantasy': 'fantasy',
    'magic': 'fantasy',
    'wizards': 'fantasy',
    'paranormal': 'paranormal',
    'supernatural': 'supernatural',
    'sci-fi': 'science fiction',
    'science-fiction': 'science fiction',
    'scifi': 'science fiction',
    'sci-fi-fantasy': 'science fiction',
    'scifi-fantasy': 'science fiction',
    'science-fiction-fantasy': 'science fiction',
    'fantasy-sci-fi': 'science fiction',
    'high-fantasy': 'fantasy',
    'epic-fantasy': 'fantasy',
    'dystopian': 'dystopia',
    'dystopia': 'dystopia',
    'steampunk': 'steampunk',
    'cyberpunk': 'cyberpunk',
    
    # Fiction & Literature
    'fiction': 'fiction',
    'novel': 'fiction',
    'novels': 'fiction',
    'ya-fiction': 'fiction',
    'classics': 'classics',
    'classic': 'classics',
    'contemporary': 'contemporary',
    'drama': 'drama',
    'poetry': 'poetry',
    'chick-lit': 'chick lit',
    'literary-fiction': 'fiction',
    
    # Mystery, Thriller, Horror & Crime
    'mystery': 'mystery',
    'thriller': 'thriller',
    'crime': 'crime',
    'detective': 'mystery',
    'suspense': 'thriller',
    'horror': 'horror',
    'gothic': 'horror',
    'mystery-thriller': 'mystery',
    
    # Age Groups
    'young-adult': 'young adult',
    'ya': 'young adult',
    'teen': 'young adult',
    'youth': 'young adult',
    'middle-grade': 'middle grade',
    'children': 'children',
    'childrens': 'children',
    'children-s': 'children',
    'kids': 'children',
    'kids-books': 'children',
    'childrens-books': 'children',
    'children-s-books': 'children',
    'juvenile': 'children',
    'children-s-literature': 'children',
    'children-s-lit': 'children',
    'childhood-books': 'children',
    
    # Action, Adventure & Romance
    'adventure': 'adventure',
    'romance': 'romance',
    'romantic': 'romance',
    'historical-romance': 'romance',
    
    # Historical & Non-fiction
    'historical-fiction': 'historical fiction',
    'history': 'history',
    'historical': 'history',
    'biography': 'biography',
    'memoir': 'biography',
    'autobiography': 'biography',
    'non-fiction': 'non-fiction',
    'nonfiction': 'non-fiction',
    
    # Others
    'humor': 'comedy',
    'comedy': 'comedy',
    'graphic-novel': 'graphic novel',
    'manga': 'manga',
    'comic': 'comics',
    'comics': 'comics'
}

def normalize_book(book_dict):
    """
    Normalizes book dictionaries from either:
    1. Lowercase schema (Kaggle Goodreads dataset format)
    2. Uppercase schema (Scraped/workspace format)
    Returns a standardized dictionary with lowercase keys.
    """
    is_uppercase = 'Title' in book_dict
    
    if is_uppercase:
        # Normalize uppercase format to standard lowercase keys
        genres = book_dict.get('Genre') or []
        popular_shelves = [{"count": "1", "name": g} for g in genres]
        
        # Build authors list from review authors if present, or leave empty
        # In the uppercase format there's no direct authors field, but reviews exist
        normalized = {
            'book_id': book_dict.get('book_id') or str(abs(hash(book_dict.get('Title', '')))),
            'title': book_dict.get('Title') or "",
            'title_without_series': book_dict.get('Title') or "",
            'description': book_dict.get('Desc') or "",
            'isbn': book_dict.get('ISBN') or "",
            'isbn13': "",
            'asin': "",
            'average_rating': str(book_dict.get('Point') or "0.0"),
            'ratings_count': str(book_dict.get('RatingsCount') or "0"),
            'text_reviews_count': str(book_dict.get('ReviewsCount') or "0"),
            'publication_year': "",
            'publication_month': "",
            'publication_day': "",
            'publisher': "",
            'language_code': book_dict.get('Language') or "",
            'is_ebook': "false",
            'format': "",
            'link': "",
            'url': "",
            'image_url': "",
            'authors': [],
            'popular_shelves': popular_shelves,
            'similar_books': [],
            'series': [],
            'country_code': "",
            'work_id': ""
        }
        return normalized
    else:
        # Already in standard lowercase format, return as is
        return book_dict

def read_books_generator(data_path):
    """
    Detects if the file is a standard JSON array or a JSON Lines file.
    Yields normalized book dictionaries, along with their byte offset and length.
    For JSON array files, the offset is not easily used for direct seek,
    but we can still support streaming them.
    """
    if not os.path.exists(data_path):
        print(f"Error: Path does not exist: {data_path}")
        return
        
    # Read the first few characters to detect format
    first_char = ""
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    first_char = stripped[0]
                    break
    except Exception as e:
        print(f"Error reading file to detect format: {e}")
        return
                
    if first_char == '[':
        # Standard JSON array.
        print("Detected JSON array format. Parsing JSON file (this may take a few seconds)...")
        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                data = json.load(f, strict=False)
            for item in data:
                yield normalize_book(item), None, None
        except Exception as e:
            print(f"Error loading JSON array: {e}")
    else:
        # JSON Lines format. Stream line-by-line using binary mode for precise offsets.
        with open(data_path, 'rb') as f:
            while True:
                offset = f.tell()
                line_bytes = f.readline()
                if not line_bytes:
                    break
                length = len(line_bytes)
                try:
                    line = line_bytes.decode('utf-8')
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    yield normalize_book(item), offset, length
                except Exception:
                    continue

def build_index(data_path, db_path, progress_callback=None):
    """
    Builds a SQLite database index of the book records.
    For JSON Lines format: stores offsets and lengths to seek back into the file.
    For JSON Array format: stores the raw JSON representation in the DB since seek is not possible.
    """
    print(f"Building SQLite index from:\n  Source: {data_path}\n  Database: {db_path}\n")
    t0 = time.time()
    
    if not os.path.exists(data_path):
        print(f"Error: Data file not found at {data_path}")
        return False
        
    # Load genres mapping in memory if genres file exists
    genres_path = "D:\\LT\\data\\goodreads_book_genres_initial.json"
    genres_map = {}
    if os.path.exists(genres_path):
        print(f"Loading genres mapping from {genres_path}...")
        t_genres = time.time()
        try:
            with open(genres_path, 'r', encoding='utf-8') as gf:
                for g_line in gf:
                    g_item = json.loads(g_line)
                    g_bid = g_item.get('book_id')
                    g_data = g_item.get('genres')
                    if g_bid and g_data:
                        # Extract individual genre names from dictionary keys by splitting commas
                        clean_list = []
                        if isinstance(g_data, dict):
                            for key in g_data.keys():
                                parts = [p.strip().lower() for p in key.split(',')]
                                for p in parts:
                                    if p and p not in clean_list:
                                        clean_list.append(p)
                        genres_map[str(g_bid)] = json.dumps(clean_list)
            print(f"Loaded {len(genres_map):,} genres in {time.time() - t_genres:.2f} seconds.\n")
        except Exception as ge:
            print(f"Warning: Failed to load genres file: {ge}\n")
            
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception as e:
            print(f"Error removing existing database: {e}")
            return False
            
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA synchronous = OFF')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA cache_size = 20000')
    
    conn.execute('''
        CREATE TABLE books (
            book_id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            isbn TEXT,
            isbn13 TEXT,
            asin TEXT,
            average_rating REAL,
            ratings_count INTEGER,
            text_reviews_count INTEGER,
            publication_year INTEGER,
            publisher TEXT,
            language_code TEXT,
            is_ebook INTEGER,
            author_ids TEXT,
            popular_shelves TEXT,
            genres TEXT,
            offset INTEGER,
            length INTEGER,
            raw_json TEXT
        )
    ''')
    
    batch = []
    batch_size = 50000
    total_count = 0
    skipped_count = 0
    
    file_size = os.path.getsize(data_path)
    bytes_processed = 0
    last_report_time = time.time()
    
    # We iterate using our generator
    for item, offset, length in read_books_generator(data_path):
        # Update progress estimate based on length
        if length is not None:
            bytes_processed += length
        
        book_id = item.get('book_id')
        if not book_id:
            skipped_count += 1
            continue
            
        title = item.get('title') or item.get('title_without_series') or ""
        description = item.get('description') or ""
        isbn = item.get('isbn') or ""
        isbn13 = item.get('isbn13') or ""
        asin = item.get('asin') or ""
        
        try:
            avg_rating = float(item.get('average_rating') or 0.0)
        except Exception:
            avg_rating = 0.0
            
        try:
            ratings_count = int(item.get('ratings_count') or 0)
        except Exception:
            ratings_count = 0
            
        try:
            text_reviews_count = int(item.get('text_reviews_count') or 0)
        except Exception:
            text_reviews_count = 0
            
        try:
            pub_year = int(item.get('publication_year') or 0)
        except Exception:
            pub_year = None
            
        publisher = item.get('publisher') or ""
        lang_code = item.get('language_code') or ""
        
        is_eb = item.get('is_ebook')
        if isinstance(is_eb, str):
            is_ebook = 1 if is_eb.lower() == 'true' else 0
        elif isinstance(is_eb, bool):
            is_ebook = 1 if is_eb else 0
        else:
            is_ebook = 0
            
        # Extract author IDs for fast lookup
        auth_list = []
        authors = item.get('authors')
        if isinstance(authors, list):
            for a in authors:
                if isinstance(a, dict) and a.get('author_id'):
                    auth_list.append(str(a['author_id']).strip())
        author_ids_str = "," + ",".join(auth_list) + "," if auth_list else ""
        
        # Extract popular shelves for fast lookup
        shelves_list = []
        shelves = item.get('popular_shelves')
        if isinstance(shelves, list):
            for s in shelves:
                if isinstance(s, dict) and s.get('name'):
                    shelves_list.append(str(s['name']).strip().lower())
        popular_shelves_str = "," + ",".join(shelves_list) + "," if shelves_list else ""
        
        # If we don't have offset (JSON array), store raw JSON
        raw_json_val = json.dumps(item) if offset is None else None
        
        # Combine initial genres with genres extracted from popular shelves
        genres_val = genres_map.get(str(book_id)) if genres_map else None
        clean_list = []
        if genres_val:
            try:
                clean_list = json.loads(genres_val)
            except Exception:
                clean_list = []
                
        if isinstance(shelves, list):
            for s in shelves:
                if isinstance(s, dict) and s.get('name'):
                    name_clean = str(s['name']).strip().lower()
                    if name_clean in GENRE_KEYWORDS:
                        mapped = GENRE_KEYWORDS[name_clean]
                        if mapped not in clean_list:
                            clean_list.append(mapped)
                            
        genres_json = json.dumps(clean_list) if clean_list else None
        
        batch.append((
            str(book_id),
            title,
            description,
            isbn,
            isbn13,
            asin,
            avg_rating,
            ratings_count,
            text_reviews_count,
            pub_year,
            publisher,
            lang_code,
            is_ebook,
            author_ids_str,
            popular_shelves_str,
            genres_json,
            offset,
            length,
            raw_json_val
        ))
        
        if len(batch) >= batch_size:
            conn.executemany('''
                INSERT OR REPLACE INTO books (
                    book_id, title, description, isbn, isbn13, asin, average_rating, ratings_count,
                    text_reviews_count, publication_year, publisher, language_code,
                    is_ebook, author_ids, popular_shelves, genres, offset, length, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', batch)
            conn.commit()
            total_count += len(batch)
            batch = []
            
            # Print progress reports for large files
            current_time = time.time()
            if current_time - last_report_time >= 2.0:
                elapsed = current_time - t0
                pct = (bytes_processed / file_size) * 100 if length is not None else 0.0
                speed = bytes_processed / elapsed / (1024 * 1024) if length is not None else 0.0
                if progress_callback:
                    progress_callback(total_count, pct, speed)
                else:
                    if length is not None:
                        print(f"Indexed {total_count:,} books... {pct:.1f}% complete ({speed:.1f} MB/s)")
                    else:
                        print(f"Indexed {total_count:,} books...")
                last_report_time = current_time
                
    if batch:
        conn.executemany('''
            INSERT OR REPLACE INTO books (
                book_id, title, description, isbn, isbn13, asin, average_rating, ratings_count,
                text_reviews_count, publication_year, publisher, language_code,
                is_ebook, author_ids, popular_shelves, genres, offset, length, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', batch)
        conn.commit()
        total_count += len(batch)
        
    print("Creating SQL indexes for high performance search...")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_title ON books(title COLLATE NOCASE)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_isbn ON books(isbn)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_isbn13 ON books(isbn13)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_asin ON books(asin)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_avg_rating ON books(average_rating)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_ratings_count ON books(ratings_count)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_lang ON books(language_code)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_pub_year ON books(publication_year)')
    conn.commit()
    conn.close()
    
    elapsed = time.time() - t0
    if progress_callback:
        progress_callback(total_count, 100.0, 0.0)
    print(f"Successfully indexed {total_count:,} books in {elapsed:.2f} seconds!")
    if skipped_count:
        print(f"Skipped {skipped_count:,} invalid records.")
    return True

def check_index_status(db_path):
    """
    Checks the status of the SQLite database index.
    """
    if not os.path.exists(db_path):
        return False, "Database index file does not exist."
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM books")
        count = cursor.fetchone()[0]
        conn.close()
        return True, f"Database index exists. Total records: {count:,} books."
    except Exception as e:
        return False, f"Database index exists but is corrupted or invalid: {e}"

def search_database(db_path, data_path, title_query=None, isbn_query=None, book_id_query=None,
                    rating_min=None, rating_max=None, reviews_min=None,
                    publication_year=None, publication_year_min=None, publication_year_max=None,
                    language_code=None, is_ebook=None, publisher_query=None,
                    author_id=None, shelf=None, genre=None, sort_by='popularity', sort_dir='desc', limit=10, offset=0):
    """
    Searches using the SQLite database.
    Loads matching metadata, resolves actual offsets/raw_json, and parses the original records.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database index not found at {db_path}. Please run with --build-index first.")
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query_parts = []
    params = []
    
    if title_query:
        query_parts.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{title_query}%", f"%{title_query}%"])
        
    if isbn_query:
        query_parts.append("(isbn = ? OR isbn13 = ? OR asin = ?)")
        params.extend([isbn_query, isbn_query, isbn_query])
        
    if book_id_query:
        query_parts.append("book_id = ?")
        params.append(str(book_id_query))
        
    if rating_min is not None:
        query_parts.append("average_rating >= ?")
        params.append(rating_min)
        
    if rating_max is not None:
        query_parts.append("average_rating <= ?")
        params.append(rating_max)
        
    if reviews_min is not None:
        query_parts.append("text_reviews_count >= ?")
        params.append(reviews_min)
        
    if publication_year is not None:
        query_parts.append("publication_year = ?")
        params.append(publication_year)
        
    if publication_year_min is not None:
        query_parts.append("publication_year >= ?")
        params.append(publication_year_min)
        
    if publication_year_max is not None:
        query_parts.append("publication_year <= ?")
        params.append(publication_year_max)
        
    if language_code:
        query_parts.append("language_code = ?")
        params.append(language_code)
        
    if is_ebook is not None:
        query_parts.append("is_ebook = ?")
        params.append(1 if is_ebook else 0)
        
    if publisher_query:
        query_parts.append("publisher LIKE ?")
        params.append(f"%{publisher_query}%")
        
    if author_id:
        query_parts.append("author_ids LIKE ?")
        params.append(f"%,{author_id},%")
        
    if shelf:
        # Support comma-separated multiple shelves (AND match)
        shelves = [s.strip().lower() for s in shelf.split(',') if s.strip()]
        for sh in shelves:
            query_parts.append("popular_shelves LIKE ?")
            params.append(f"%,{sh},%")
        
    if genre:
        # Support comma-separated multiple genres (AND match)
        genres_query = [g.strip().lower() for g in genre.split(',') if g.strip()]
        for ge in genres_query:
            query_parts.append("genres LIKE ?")
            params.append(f"%{ge}%")
        
    sql = "SELECT offset, length, raw_json, genres FROM books"
    if query_parts:
        sql += " WHERE " + " AND ".join(query_parts)
        
    # Sort ordering
    direction = "ASC" if sort_dir == 'asc' else "DESC"
    if sort_by == 'rating':
        sql += f" ORDER BY average_rating {direction}"
    elif sort_by == 'reviews':
        sql += f" ORDER BY text_reviews_count {direction}"
    elif sort_by == 'year':
        sql += f" ORDER BY publication_year {direction}"
    else: # popularity (ratings_count)
        sql += f" ORDER BY ratings_count {direction}"
        
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(sql, params)
    results = cursor.fetchall()
    conn.close()
    
    # Resolve matching books
    books = []
    f = None
    try:
        # Check if we need to open the raw data file (only needed if some offsets are populated)
        needs_file = any(r[0] is not None for r in results)
        if needs_file:
            if not os.path.exists(data_path):
                raise FileNotFoundError(f"Original data file not found at {data_path} (needed to read complete records).")
            f = open(data_path, 'rb')
            
        for off, length, raw_json, genres_val in results:
            book = None
            if off is not None and length is not None:
                f.seek(off)
                line_bytes = f.read(length)
                book = normalize_book(json.loads(line_bytes.decode('utf-8')))
            elif raw_json is not None:
                book = json.loads(raw_json)
                
            if book is not None:
                if genres_val:
                    try:
                        book['genres'] = json.loads(genres_val)
                    except Exception:
                        pass
                books.append(book)
    finally:
        if f:
            f.close()
            
    return books

def search_streaming(data_path, title_query=None, isbn_query=None, book_id_query=None,
                     rating_min=None, rating_max=None, reviews_min=None,
                     publication_year=None, publication_year_min=None, publication_year_max=None,
                     language_code=None, is_ebook=None, publisher_query=None,
                     author_id=None, shelf=None, genre=None, sort_by=None, sort_dir='desc', limit=10, offset=0):
    """
    Streaming search fallback that scans the file line-by-line.
    Useful for ad-hoc queries when no database index is present.
    """
    count = 0
    matched_books = []
    
    # We read records from the generator
    for item, _, _ in read_books_generator(data_path):
        if book_id_query and str(item.get('book_id')) != str(book_id_query):
            continue
            
        if isbn_query:
            isbns = [item.get('isbn'), item.get('isbn13'), item.get('asin')]
            if isbn_query not in isbns:
                continue
                
        if title_query:
            t = (item.get('title') or item.get('title_without_series') or "").lower()
            desc = (item.get('description') or "").lower()
            if title_query.lower() not in t and title_query.lower() not in desc:
                continue
                
        if rating_min is not None:
            try:
                val = float(item.get('average_rating') or 0.0)
                if val < rating_min: continue
            except ValueError:
                continue
                
        if rating_max is not None:
            try:
                val = float(item.get('average_rating') or 0.0)
                if val > rating_max: continue
            except ValueError:
                continue
                
        if reviews_min is not None:
            try:
                val = int(item.get('text_reviews_count') or 0)
                if val < reviews_min: continue
            except ValueError:
                continue
                
        if publication_year is not None:
            try:
                val = int(item.get('publication_year') or 0)
                if val != publication_year: continue
            except ValueError:
                continue
                
        if publication_year_min is not None:
            try:
                val = int(item.get('publication_year') or 0)
                if val < publication_year_min: continue
            except ValueError:
                continue
                
        if publication_year_max is not None:
            try:
                val = int(item.get('publication_year') or 0)
                if val > publication_year_max: continue
            except ValueError:
                continue
                
        if language_code:
            if item.get('language_code') != language_code:
                continue
                
        if is_ebook is not None:
            is_eb_str = str(item.get('is_ebook')).lower()
            is_eb_val = True if is_eb_str == 'true' else False
            if is_eb_val != is_ebook:
                continue
                
        if publisher_query:
            pub = (item.get('publisher') or "").lower()
            if publisher_query.lower() not in pub:
                continue
                
        if author_id:
            authors = item.get('authors') or []
            if not any(str(a.get('author_id')) == str(author_id) for a in authors if isinstance(a, dict)):
                continue
                
        if shelf:
            shelves_query = [s.strip().lower() for s in shelf.split(',') if s.strip()]
            book_shelves = []
            if isinstance(item.get('popular_shelves'), list):
                for s in item.get('popular_shelves'):
                    if isinstance(s, dict) and s.get('name'):
                        book_shelves.append(str(s['name']).strip().lower())
            if not all(sq in book_shelves for sq in shelves_query):
                continue
                
        if genre:
            genres_query = [g.strip().lower() for g in genre.split(',') if g.strip()]
            book_genres = item.get('genres') or []
            if isinstance(book_genres, str):
                try:
                    book_genres = json.loads(book_genres)
                except Exception:
                    book_genres = []
            if isinstance(book_genres, dict):
                book_genres = list(book_genres.keys())
            book_genres = [bg.lower() for bg in book_genres if isinstance(bg, str)]
            
            # Check if all query genres are matched (AND matching)
            if not all(any(gq in bg for bg in book_genres) for gq in genres_query):
                continue
                
        # Match found!
        count += 1
        if count > offset:
            matched_books.append(item)
            # Stop once limit is satisfied (if not sorting globally)
            # If they want sorting, we need to scan the whole file to find all candidates,
            # which is very slow. We warn the user about it.
            if not sort_by and len(matched_books) >= limit:
                break
                
    if sort_by and matched_books:
        # Sort matched results locally
        rev = False if sort_dir == 'asc' else True
        if sort_by == 'rating':
            matched_books.sort(key=lambda x: float(x.get('average_rating') or 0), reverse=rev)
        elif sort_by == 'reviews':
            matched_books.sort(key=lambda x: int(x.get('text_reviews_count') or 0), reverse=rev)
        elif sort_by == 'year':
            matched_books.sort(key=lambda x: int(x.get('publication_year') or 0) if x.get('publication_year') else 0, reverse=rev)
        else: # popularity
            matched_books.sort(key=lambda x: int(x.get('ratings_count') or 0) if x.get('ratings_count') else 0, reverse=rev)
        # Apply limit after sorting
        matched_books = matched_books[:limit]
        
    return matched_books

def pretty_print_books(books):
    """
    Displays book details in a beautifully formatted text style.
    """
    if not books:
        print("No books found.")
        return
        
    print("=" * 70)
    for idx, book in enumerate(books, 1):
        title = book.get('title') or book.get('title_without_series') or 'Unknown Title'
        book_id = book.get('book_id', 'N/A')
        isbn = book.get('isbn') or book.get('isbn13') or book.get('asin') or 'N/A'
        avg_rating = book.get('average_rating', 'N/A')
        ratings_count = book.get('ratings_count', '0')
        lang = book.get('language_code') or 'N/A'
        pub = book.get('publisher') or 'N/A'
        year = book.get('publication_year') or 'N/A'
        fmt = book.get('format') or ('Ebook' if str(book.get('is_ebook')).lower() == 'true' else 'N/A')
        
        # Authors
        authors_list = []
        authors = book.get('authors')
        if isinstance(authors, list):
            for a in authors:
                if isinstance(a, dict) and a.get('author_id'):
                    role_str = f" ({a['role']})" if a.get('role') else ""
                    authors_list.append(f"ID:{a['author_id']}{role_str}")
        authors_str = ", ".join(authors_list) if authors_list else "N/A"
        
        # popular shelves/genres
        shelves_list = []
        shelves = book.get('popular_shelves') or []
        if isinstance(shelves, list):
            for s in shelves[:5]:  # show up to 5 shelves
                if isinstance(s, dict) and s.get('name'):
                    cnt = f" ({s['count']})" if s.get('count') else ""
                    shelves_list.append(f"{s['name']}{cnt}")
        shelves_str = ", ".join(shelves_list) if shelves_list else "N/A"
        
        # genres
        genres = book.get('genres') or []
        if isinstance(genres, list):
            genres_list = genres
        elif isinstance(genres, dict):
            genres_list = list(genres.keys())
        else:
            genres_list = []
        genres_str = ", ".join(genres_list) if genres_list else "N/A"
        
        print(f"[{idx}] {title}")
        print(f"    Book ID : {book_id} | ISBN: {isbn}")
        print(f"    Authors : {authors_str}")
        print(f"    Rating  : {avg_rating} | Ratings Count: {int(ratings_count):,} | Reviews Count: {int(book.get('text_reviews_count') or 0):,}")
        print(f"    Details : Lang: {lang} | Format: {fmt} | Publisher: {pub} | Year: {year}")
        print(f"    Shelves : {shelves_str}")
        if genres_str != "N/A":
            print(f"    Genres  : {genres_str}")
        if book.get('link') or book.get('url'):
            print(f"    Link    : {book.get('link') or book.get('url')}")
            
        desc = book.get('description') or ""
        if desc:
            clean_desc = desc.replace('\n', ' ').strip()
            if len(clean_desc) > 200:
                clean_desc = clean_desc[:200] + "..."
            print(f"    Desc    : {clean_desc}")
            
        print("-" * 70)
    print("=" * 70)

def main():
    # Fix console encoding on Windows to prevent UnicodeEncodeErrors
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        
    parser = argparse.ArgumentParser(description="Search and filter Goodreads books dataset.")
    parser.add_argument("--data-path", default=data_path, help="Path to the goodreads_books.json file.")
    parser.add_argument("--db-path", default="goodreads_books.db", help="Path to the SQLite index database.")
    parser.add_argument("--build-index", action="store_true", help="Build the SQLite database index from the raw JSON file.")
    parser.add_argument("--status", action="store_true", help="Print the status of the SQLite database index.")
    
    # Query parameters
    parser.add_argument("--search", help="Search string to match in title or description.")
    parser.add_argument("--id", help="Retrieve a book by book_id.")
    parser.add_argument("--isbn", help="Retrieve a book by isbn, isbn13, or asin.")
    
    # Filter parameters
    parser.add_argument("--rating-min", type=float, help="Minimum average rating.")
    parser.add_argument("--rating-max", type=float, help="Maximum average rating.")
    parser.add_argument("--reviews-min", type=int, help="Minimum number of text reviews.")
    parser.add_argument("--year", type=int, help="Specific publication year.")
    parser.add_argument("--year-min", type=int, help="Minimum publication year.")
    parser.add_argument("--year-max", type=int, help="Maximum publication year.")
    parser.add_argument("--lang", help="Language code (e.g. 'eng').")
    parser.add_argument("--ebook", action="store_true", default=None, help="Filter for ebooks.")
    parser.add_argument("--no-ebook", action="store_false", dest="ebook", help="Filter out ebooks.")
    parser.add_argument("--publisher", help="Publisher name contains this string.")
    parser.add_argument("--author", help="Author ID.")
    parser.add_argument("--shelf", help="Comma-separated popular shelf names (all must match).")
    parser.add_argument("--genre", help="Comma-separated genres (all must match).")
    
    # Sorting and Pagination
    parser.add_argument("--sort", choices=['rating', 'reviews', 'year', 'popularity'], default='popularity',
                        help="Sort by criteria (popularity uses ratings_count). Default: popularity.")
    parser.add_argument("--sort-dir", choices=['asc', 'desc'], default='desc',
                        help="Sort direction: 'asc' or 'desc'. Default: desc.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of results to return. Default: 10.")
    parser.add_argument("--offset", type=int, default=0, help="Offset for pagination. Default: 0.")
    
    # Execution options
    parser.add_argument("--streaming", action="store_true", help="Force scanning the JSON file line-by-line (no index).")
    parser.add_argument("--format", choices=['pretty', 'json', 'csv'], default='pretty', help="Output format. Default: pretty.")
    
    args = parser.parse_args()
    
    # If no actions or filters are specified, print help and current status
    if not any([args.build_index, args.status, args.search, args.id, args.isbn,
                args.rating_min, args.rating_max, args.reviews_min, args.year,
                args.year_min, args.year_max, args.lang, args.ebook is not None,
                args.publisher, args.author, args.shelf, args.genre]):
        parser.print_help()
        print("\nIndex Status:")
        exists, msg = check_index_status(args.db_path)
        print(f"  {msg}")
        return
        
    if args.build_index:
        build_index(args.data_path, args.db_path)
        return
        
    if args.status:
        exists, msg = check_index_status(args.db_path)
        print(msg)
        return
        
    # Check if database index exists and streaming is not forced
    use_db = False
    if not args.streaming:
        exists, _ = check_index_status(args.db_path)
        if exists:
            use_db = True
        else:
            # If DB doesn't exist, we fall back to streaming
            print(f"Note: SQLite database index not found at {args.db_path}. Running in streaming mode (slower).")
            print("To speed up future searches, run with: --build-index\n")
            
    # Execute query
    t_start = time.time()
    try:
        if use_db:
            books = search_database(
                db_path=args.db_path,
                data_path=args.data_path,
                title_query=args.search,
                isbn_query=args.isbn,
                book_id_query=args.id,
                rating_min=args.rating_min,
                rating_max=args.rating_max,
                reviews_min=args.reviews_min,
                publication_year=args.year,
                publication_year_min=args.year_min,
                publication_year_max=args.year_max,
                language_code=args.lang,
                is_ebook=args.ebook,
                publisher_query=args.publisher,
                author_id=args.author,
                shelf=args.shelf,
                genre=args.genre,
                sort_by=args.sort,
                sort_dir=args.sort_dir,
                limit=args.limit,
                offset=args.offset
            )
        else:
            books = search_streaming(
                data_path=args.data_path,
                title_query=args.search,
                isbn_query=args.isbn,
                book_id_query=args.id,
                rating_min=args.rating_min,
                rating_max=args.rating_max,
                reviews_min=args.reviews_min,
                publication_year=args.year,
                publication_year_min=args.year_min,
                publication_year_max=args.year_max,
                language_code=args.lang,
                is_ebook=args.ebook,
                publisher_query=args.publisher,
                author_id=args.author,
                shelf=args.shelf,
                genre=args.genre,
                sort_by=args.sort if (args.sort or any([args.rating_min, args.rating_max])) else None,
                sort_dir=args.sort_dir,
                limit=args.limit,
                offset=args.offset
            )
    except Exception as e:
        print(f"Error executing search: {e}", file=sys.stderr)
        sys.exit(1)
        
    t_elapsed = time.time() - t_start
    
    # Format and display output
    if args.format == 'pretty':
        pretty_print_books(books)
        print(f"Search completed in {t_elapsed:.3f} seconds (Found {len(books)} matches).")
    elif args.format == 'json':
        print(json.dumps(books, indent=2))
    elif args.format == 'csv':
        writer = csv.writer(sys.stdout)
        headers = ['book_id', 'title', 'authors', 'average_rating', 'ratings_count', 'isbn', 'isbn13', 'asin', 'language_code', 'publication_year', 'publisher', 'format', 'is_ebook', 'link']
        writer.writerow(headers)
        for book in books:
            authors_str = ",".join([str(a.get('author_id', '')) for a in book.get('authors', []) if isinstance(a, dict)])
            writer.writerow([
                book.get('book_id', ''),
                book.get('title', '') or book.get('title_without_series', ''),
                authors_str,
                book.get('average_rating', ''),
                book.get('ratings_count', ''),
                book.get('isbn', ''),
                book.get('isbn13', ''),
                book.get('asin', ''),
                book.get('language_code', ''),
                book.get('publication_year', ''),
                book.get('publisher', ''),
                book.get('format', ''),
                book.get('is_ebook', ''),
                book.get('link', '')
            ])

if __name__ == '__main__':
    main()
