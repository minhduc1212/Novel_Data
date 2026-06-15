import os
import json
import sqlite3
import time

goodreads_genres_path = "D:\\LT\\data\\goodreads_book_genres_initial.json"
db_path = "goodreads_books.db"

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

def clean_shelves_to_genres(shelves_str):
    """
    Splits the comma-separated popular shelves string and maps matches to clean genre names.
    """
    if not shelves_str:
        return []
    extracted = []
    # Split the comma-separated string from the SQLite database
    parts = [p.strip().lower() for p in shelves_str.split(',') if p.strip()]
    for p in parts:
        if p in GENRE_KEYWORDS:
            mapped = GENRE_KEYWORDS[p]
            if mapped not in extracted:
                extracted.append(mapped)
    return extracted

def add_genres_to_db():
    """
    Imports and cleans the genres database.
    1. Loads all book IDs and popular shelves from SQLite.
    2. Combines initial JSONL genres (with comma splitting and removing vote counts)
       with mapped genres extracted from the popular shelves.
    3. Backfills any remaining books in the database using their popular shelves.
    4. Commits all changes in fast transactions.
    """
    if not os.path.exists(goodreads_genres_path):
        print(f"Error: Genres file not found at {goodreads_genres_path}")
        return False
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return False
        
    print(f"Opening connection to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA synchronous = OFF')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA cache_size = 20000')
    
    cursor = conn.cursor()
    
    # Ensure genres column exists
    cursor.execute("PRAGMA table_info(books)")
    columns = [col[1] for col in cursor.fetchall()]
    if "genres" not in columns:
        print("Adding 'genres' column to the 'books' table...")
        cursor.execute("ALTER TABLE books ADD COLUMN genres TEXT")
        conn.commit()
    else:
        print("'genres' column already exists in 'books' table.")
        
    # 1. Fetch popular_shelves from database
    print("Fetching popular_shelves from database...")
    t_fetch = time.time()
    cursor.execute("SELECT book_id, popular_shelves FROM books")
    db_books = {}
    for bid, shelves_str in cursor.fetchall():
        db_books[str(bid)] = shelves_str
    print(f"Loaded {len(db_books):,} books from DB in {time.time() - t_fetch:.2f} seconds.")
    
    # 2. Read initial genres and combine with shelf-extracted genres
    print("Reading genres file and combining with popular shelves...")
    t0 = time.time()
    updated_genres = {}
    total_lines = 0
    
    with open(goodreads_genres_path, 'r', encoding='utf-8') as f:
        for line in f:
            total_lines += 1
            try:
                item = json.loads(line)
                book_id = str(item.get('book_id'))
                genres_data = item.get('genres')
                
                # Extract initial genres from dict keys
                clean_list = []
                if isinstance(genres_data, dict):
                    for key in genres_data.keys():
                        parts = [p.strip().lower() for p in key.split(',')]
                        for p in parts:
                            if p and p not in clean_list:
                                clean_list.append(p)
                                
                # Combine with genres from popular_shelves
                shelves_str = db_books.get(book_id)
                shelf_genres = clean_shelves_to_genres(shelves_str)
                for sg in shelf_genres:
                    if sg not in clean_list:
                        clean_list.append(sg)
                        
                if clean_list:
                    updated_genres[book_id] = clean_list
            except Exception:
                continue
                
    # 3. For books in DB that were NOT in genres file, extract genres from shelves
    print("Processing remaining books in DB...")
    for book_id, shelves_str in db_books.items():
        if book_id not in updated_genres:
            shelf_genres = clean_shelves_to_genres(shelves_str)
            if shelf_genres:
                updated_genres[book_id] = shelf_genres
                
    # 4. Update SQLite database in batches
    print("Updating SQLite database in batches...")
    batch = []
    batch_size = 50000
    updated_count = 0
    
    for book_id, genres_list in updated_genres.items():
        batch.append((json.dumps(genres_list), book_id))
        if len(batch) >= batch_size:
            cursor.executemany("UPDATE books SET genres = ? WHERE book_id = ?", batch)
            conn.commit()
            updated_count += len(batch)
            elapsed = time.time() - t0
            rate = updated_count / elapsed if elapsed > 0 else 0
            print(f"Updated {updated_count:,} books... ({elapsed:.1f}s, {rate:.0f} books/s)")
            batch = []
            
    if batch:
        cursor.executemany("UPDATE books SET genres = ? WHERE book_id = ?", batch)
        conn.commit()
        updated_count += len(batch)
        
    elapsed = time.time() - t0
    print(f"\nFinished updating genres!")
    print(f"Total books updated in SQLite: {updated_count:,}")
    print(f"Time taken: {elapsed:.2f} seconds")
    
    conn.close()
    return True

if __name__ == '__main__':
    add_genres_to_db()