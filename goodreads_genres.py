import os
import json
import sqlite3
import time

goodreads_genres_path = "D:\\LT\\data\\goodreads_book_genres_initial.json"
db_path = "goodreads_books.db"

# List of keywords that definitely indicate a shelf is NOT a genre.
# If a shelf name contains any of these substrings, it will be skipped.
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

# Classification mapping of popular shelf tags to standard categories (genres, themes, audiences)
SHELF_CLASSIFICATION = {
    # --- MAIN GENRES ---
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
    
    'poetry': ('genres', 'poetry'),
    'drama': ('genres', 'drama'),
    'plays': ('genres', 'drama'),
    'humor': ('genres', 'comedy'),
    'humour': ('genres', 'comedy'),
    'comedy': ('genres', 'comedy'),
    'funny': ('genres', 'comedy'),
    
    'religion': ('genres', 'religion'),
    'theology': ('genres', 'religion'),
    'philosophy': ('genres', 'philosophy'),
    'psychology': ('genres', 'psychology'),
    'politics': ('genres', 'politics'),
    'sociology': ('genres', 'sociology'),
    
    # --- THEMES & TROPES ---
    'magic': ('themes', 'magic'),
    'wizards': ('themes', 'wizards'),
    'wizards-witches': ('themes', 'wizards'),
    'dragons': ('themes', 'dragons'),
    'elves': ('themes', 'elves'),
    'paranormal': ('themes', 'paranormal'),
    'supernatural': ('themes', 'supernatural'),
    'vampires': ('themes', 'vampires'),
    'vampire': ('themes', 'vampires'),
    'werewolves': ('themes', 'werewolves'),
    'zombies': ('themes', 'zombies'),
    'ghosts': ('themes', 'ghosts'),
    
    'dystopian': ('themes', 'dystopia'),
    'dystopia': ('themes', 'dystopia'),
    'steampunk': ('themes', 'steampunk'),
    'cyberpunk': ('themes', 'cyberpunk'),
    'time-travel': ('themes', 'time travel'),
    'space-opera': ('themes', 'space opera'),
    'apocalypse': ('themes', 'apocalyptic'),
    'post-apocalypse': ('themes', 'post-apocalyptic'),
    'post-apocalyptic': ('themes', 'post-apocalyptic'),
    
    'war': ('themes', 'war'),
    'military': ('themes', 'military'),
    'grimdark': ('themes', 'grimdark'),
    'dark': ('themes', 'dark'),
    'coming-of-age': ('themes', 'coming of age'),
    'family': ('themes', 'family'),
    'school': ('themes', 'school'),
    'love': ('themes', 'love'),
    'friendship': ('themes', 'friendship'),
    'lgbtq': ('themes', 'lgbtq'),
    'queer': ('themes', 'lgbtq'),
    'lgbt': ('themes', 'lgbtq'),
    'mythology': ('themes', 'mythology'),
    'myths': ('themes', 'mythology'),
    'folklore': ('themes', 'folklore'),
    'fairy-tales': ('themes', 'fairy tales'),
    'fairy-tale': ('themes', 'fairy tales'),
    
    # --- AUDIENCES & FORMATS ---
    'young-adult': ('audiences', 'young adult'),
    'ya': ('audiences', 'young adult'),
    'teen': ('audiences', 'young adult'),
    'youth': ('audiences', 'young adult'),
    'ya-fiction': ('audiences', 'young adult'),
    'middle-grade': ('audiences', 'middle grade'),
    'children': ('audiences', 'children'),
    'childrens': ('audiences', 'children'),
    'children-s': ('audiences', 'children'),
    'kids': ('audiences', 'children'),
    'kids-books': ('audiences', 'children'),
    'childrens-books': ('audiences', 'children'),
    'children-s-books': ('audiences', 'children'),
    'juvenile': ('audiences', 'children'),
    'children-s-literature': ('audiences', 'children'),
    'children-s-lit': ('audiences', 'children'),
    'childhood-books': ('audiences', 'children'),
    'childhood': ('audiences', 'children'),
    'new-adult': ('audiences', 'new adult'),
    'adult': ('audiences', 'adult'),
    'adult-fiction': ('audiences', 'adult'),
    
    'short-stories': ('audiences', 'short stories'),
    'short-story': ('audiences', 'short stories'),
    'graphic-novel': ('audiences', 'graphic novel'),
    'manga': ('audiences', 'manga'),
    'comic': ('audiences', 'comics'),
    'comics': ('audiences', 'comics')
}

def clean_shelves_to_structured(shelves_str, initial_genres_list):
    """
    Cleans tags and populates them into structured lists (genres, themes, audiences).
    """
    genres = []
    themes = []
    audiences = []
    
    # Start with initial genres (defaulted as main genres, unless mapped otherwise)
    for g in initial_genres_list:
        g_clean = g.strip().lower()
        if g_clean in SHELF_CLASSIFICATION:
            cat, val = SHELF_CLASSIFICATION[g_clean]
            if cat == 'genres' and val not in genres:
                genres.append(val)
            elif cat == 'themes' and val not in themes:
                themes.append(val)
            elif cat == 'audiences' and val not in audiences:
                audiences.append(val)
        else:
            if g.strip() and g.strip() not in genres:
                genres.append(g.strip())
                
    if shelves_str:
        # Split popular shelves
        parts = [p.strip().lower() for p in shelves_str.split(',') if p.strip()]
        for p in parts:
            # Check blacklist
            is_blacklisted = False
            for bl_word in BLACKLIST_KEYWORDS:
                if bl_word in p:
                    is_blacklisted = True
                    break
            if is_blacklisted:
                continue
                
            if p in SHELF_CLASSIFICATION:
                cat, val = SHELF_CLASSIFICATION[p]
                if cat == 'genres' and val not in genres:
                    genres.append(val)
                elif cat == 'themes' and val not in themes:
                    themes.append(val)
                elif cat == 'audiences' and val not in audiences:
                    audiences.append(val)
                    
    return {
        "genres": genres,
        "themes": themes,
        "audiences": audiences
    }

def add_genres_to_db():
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
        
    # 1. Fetch popular_shelves from database
    print("Fetching popular_shelves from database...")
    t_fetch = time.time()
    cursor.execute("SELECT book_id, popular_shelves FROM books")
    db_books = {}
    for bid, shelves_str in cursor.fetchall():
        db_books[str(bid)] = shelves_str
    print(f"Loaded {len(db_books):,} books from DB in {time.time() - t_fetch:.2f} seconds.")
    
    # 2. Read initial genres and combine into structured objects
    print("Reading genres file and compiling structured classifications...")
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
                initial_list = []
                if isinstance(genres_data, dict):
                    for key in genres_data.keys():
                        parts = [p.strip().lower() for p in key.split(',')]
                        for p in parts:
                            if p and p not in initial_list:
                                initial_list.append(p)
                                
                # Compile structured dict combining initial genres and shelves
                shelves_str = db_books.get(book_id)
                structured = clean_shelves_to_structured(shelves_str, initial_list)
                
                if structured["genres"] or structured["themes"] or structured["audiences"]:
                    updated_genres[book_id] = structured
            except Exception:
                continue
                
    # 3. For books in DB that were NOT in genres file, extract from shelves
    print("Processing remaining books in DB...")
    for book_id, shelves_str in db_books.items():
        if book_id not in updated_genres:
            structured = clean_shelves_to_structured(shelves_str, [])
            if structured["genres"] or structured["themes"] or structured["audiences"]:
                updated_genres[book_id] = structured
                
    # 4. Update SQLite database in batches
    print("Updating SQLite database in batches...")
    batch = []
    batch_size = 50000
    updated_count = 0
    
    for book_id, structured_dict in updated_genres.items():
        batch.append((json.dumps(structured_dict), book_id))
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