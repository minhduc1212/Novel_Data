# Goodreads Novel Scraper, SQLite Search Engine & Genre Analytics Pipeline

An advanced, end-to-end Python pipeline designed to scrape, clean, enrich, index, and browse massive book datasets. The system extracts novel metadata from raw Open Library dumps, scrapes Goodreads using a multi-threaded headless browser framework capable of bypassing WAF/Cloudflare blocks, refines execution checkpoints, builds a high-performance SQLite database, cleanses and enrich book genres by cross-referencing user tags, and provides both a CLI search engine and a modern dark-theme GUI browser built with `customtkinter`.

---

## 📌 System Architecture

The pipeline consists of six key steps, moving from raw public data dumps to an interactive search GUI and incorporating an offline genre enrichment dataset.

```mermaid
graph TD
    A[Open Library 59GB Dump] -->|ol_data.py| B(clean_novel_isbns.txt)
    B -->|goodreads_data.py| C{Goodreads Scraper}
    C -->|DrissionPage & proxies| D[(goodreads_books.json / csv)]
    C -.->|WAF block log| E(goodreads_scraper.log)
    E -->|clean_checkpoint.py| F(goodreads_checkpoint.json)
    F -.->|Restore clean ISBNs| C
    
    D -->|goodreads_search.py| G[(goodreads_books.db)]
    
    H[(goodreads_book_genres_initial.json)] -->|goodreads_genres.py| G
    G -->|goodreads_search.py| I[CLI Search Engine]
    G -->|goodreads_ui.py| J[CustomTkinter Desktop GUI]
```

---

## 🛠️ Components & Features

### 1. Ingestion & ISBN Filtering ([ol_data.py](file:///D:/LT/Novel_data/ol_data.py))
* **Goal**: Processes raw Open Library dumps (often 50GB+) to filter for novels and extract unique ISBNs.
* **Keyword Filter**: Detects subjects like fiction, novel, romance, fantasy, mystery, thriller, horror, young adult, etc.
* **Negative Exclusions**: Strips non-novel formats like textbook, manual, guide, dictionary, encyclopedia, biography, manga, comics, academic, and poetry.
* **Performance**: Stream-reads the dump line-by-line using binary buffer seek, matching key text before JSON deserialization (`json.loads`) to minimize memory load and CPU time.

### 2. Resilient Goodreads Scraper ([goodreads_data.py](file:///D:/LT/Novel_data/goodreads_data.py))
* **WAF/Cloudflare Bypassing**: Uses [DrissionPage](https://github.com/g1879/DrissionPage) to control Chromium directly. Unlike standard `requests` or Selenium/Puppeteer, it is highly resistant to bot-detection mechanisms and processes Cloudflare/AWS challenges naturally.
* **Multi-Threaded**: Spawns multiple Chromium instances crawling concurrently with staggered startups.
* **Local Proxy Relay**: Features a lightweight local TCP tunnel server per thread that dynamically injects basic authentication credentials into HTTP/SOCKS5 proxy requests.
* **RAM & Disk Optimizations**: 
  - Disables media (images, audio, video) loading.
  - Limits Chromium to one renderer process.
  - Caps V8 javascript heap at 256MB.
  - Employs sandbox-disabled configurations and uses a per-thread temp folder for profiles to prevent disk write thrashing.
* **Data Extraction**: Resolves Next.js page states via `__NEXT_DATA__` for complete accuracy, capturing title, description, average points, counts (ratings, reviews, currently reading, want to read), full genres, and the top 10 reviews (with date, author details, like counts, and spoiler status). Falls back to DOM selectors on script fail.
* **Atomic Append Persistence**: Performs O(1) tail-append operations to add JSON objects directly inside the closing array tag (`]`), avoiding complete rewrites.
* **Checkpoints**: Persists active state (`failed_isbns`, `duplicate_isbns`, and `non_english_isbns`) in `goodreads_checkpoint.json` for crash safety and deduplication.

### 3. Checkpoint Recovery & Refiner ([clean_checkpoint.py](file:///D:/LT/Novel_data/clean_checkpoint.py))
* **Goal**: Automatically scans the execution logs (`goodreads_scraper.log`).
* **Logic**: Extracts ISBNs that failed solely because of temporary `403 Forbidden` WAF challenges and cleanses them from `failed_isbns` in `goodreads_checkpoint.json`. This permits them to be retried on subsequent scraping passes instead of being permanently skipped.

### 4. Genre Extraction, Cleaning & Enrichment ([goodreads_genres.py](file:///D:/LT/Novel_data/goodreads_genres.py))
* **Goal**: Cleanses, standardizes, and adds comprehensive genres to the SQLite database.
* **Ingestion**: Processes `goodreads_book_genres_initial.json` (190MB JSON Lines file).
* **Cleaning & Standardizing**:
  - Splits compound/multi-category keys (e.g., `"fantasy, paranormal"`, `"mystery, thriller, crime"`) by commas into distinct individual genre names.
  - Removes vote count numbers (e.g. `(54156)`) to store clean textual labels.
* **Enrichment from Shelves**:
  - Cross-references the book's `popular_shelves` column (representing raw user shelf tags) using a comprehensive mapping (`GENRE_KEYWORDS`).
  - Automatically extracts and standardizes additional genres (e.g., mapping tags like `middle-grade` to `middle grade`, `classic` to `classics`, `sci-fi-fantasy` to `science fiction`, `supernatural` to `supernatural`).
  - Combines these with the initial genres list, keeping the primary/original categories first and removing duplicates.
* **Database Updates**: Stores the resulting clean genres list as a JSON array of strings in the `genres` column of the `books` table. Backfills matching database entries efficiently (updates 1.98M books in ~105 seconds).

### 5. High-Performance SQLite Search Engine ([goodreads_search.py](file:///D:/LT/Novel_data/goodreads_search.py))
* **Indexing**: Indexes JSON datasets into a local SQLite database (`goodreads_books.db`) using transaction batching. Includes the `genres` column during index rebuilding, automatically applying the genre-enrichment mapping.
* **Filtering & Sorting**: 
  - Supports filtering by title, description, ISBN/ASIN, average rating, reviews count, publication year bounds, ebooks, authors, and publishers.
  - **Multi-Value AND Filtering**: Supports comma-separated tag lists for both `--shelf` and `--genre` arguments. Searches are translated into relational `AND` statements (e.g., `--genre "fantasy, young-adult"`) ensuring books match all query elements.
  - **Sort Inversion**: Supports choosing sorting directions via `--sort-dir asc` (worst-to-best / inverse rating) or `--sort-dir desc` (best-to-worst / default).
* **Storage Modes**:
  - **JSON Lines format**: Stores byte offsets and length markers in the database for zero-memory seek queries back into the main text data.
  - **Standard JSON Array**: Fallback stores raw JSON records directly in the SQLite database columns.

### 6. CustomTkinter Desktop GUI ([goodreads_ui.py](file:///D:/LT/Novel_data/goodreads_ui.py))
* **User Interface**: Built on [customtkinter](https://github.com/TomSchimansky/CustomTkinter) featuring a modern dark theme layout.
* **Features**:
  - **Interactive Results**: Displays paginated book cards showing description excerpts, rating stars, details, and cleaned genres.
  - **Filters Sidebar**: Provides slider controls (Average Rating), range entries (Publication Year bounds), menus (Language codes, Ebook formats), and tag entries. Includes a dedicated **Genre** entry field supporting comma-separated multi-genre `AND` filters (e.g. `fiction, young-adult`).
  - **Sort Order & Direction**: Includes dropdown options for sort criteria (Popularity, Average Rating, Reviews Count, Publish Year) paired with a sort direction dropdown menu supporting `Desc (High to Low)` and `Asc (Low to High)` ordering.
  - **Book Details**: Displays detailed book info in a popup modal, combining popular shelves and cleaned genres into a formatted "Shelves & Genres" scroll panel.

---

## 🚀 Installation & Setup

1. **Clone & Open Project Directory**:
   ```bash
   cd D:\LT\Novel_data
   ```

2. **Create and Activate virtual environment**:
   ```bash
   python -m venv .venv
   # For Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # For Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *Note: Ensure you have `customtkinter` installed as well:*
   ```bash
   pip install customtkinter DrissionPage beautifulsoup4 lxml requests tqdm
   ```

4. **Setup Proxy Environment File**:
   Create or modify [.env](file:///D:/LT/Novel_data/.env) in the project root folder. Add your proxy lists (supporting basic auth) under `PROXIES`:
   ```ini
   # Add SOCKS5 or HTTP proxies separated by commas
   PROXIES=http://user:password@proxy1_ip:port,socks5://user:pwd@proxy2_ip:port
   ```

---

## 📖 How to Run

### Step 1: Filter Novel ISBNs from Open Library
Specify your raw Open Library dump location in [ol_data.py](file:///D:/LT/Novel_data/ol_data.py) and execute:
```bash
python ol_data.py
```
This produces [clean_novel_isbns.txt](file:///D:/LT/Novel_data/clean_novel_isbns.txt).

### Step 2: Run the Goodreads Scraper
Crawls details for the English ISBNs inside `clean_novel_isbns.txt`.
```bash
python goodreads_data.py --threads 4 --delay-min 3.0 --delay-max 6.0 --headless False
```

### Step 3: Index and Import Genres to Database
1. **Build SQLite index from JSON database**:
   ```bash
   python goodreads_search.py --build-index
   ```
2. **Backfill & Clean Genres**:
   Reads raw genres, splits compound items, discards vote counts, enrich with popular shelves, and saves them to the DB:
   ```bash
   python goodreads_genres.py
   ```

### Step 4: Perform Searches via CLI
* Search books by genre matching both "fantasy" and "young-adult", sorted by ratings from best to worst:
  ```bash
  python goodreads_search.py --genre "fantasy, young-adult" --sort rating --sort-dir desc --limit 5
  ```
* Search books by "science fiction" in inverse rating order (worst-to-best):
  ```bash
  python goodreads_search.py --genre "science fiction" --sort rating --sort-dir asc --limit 5
  ```
* Search with multiple shelves (both "fantasy" and "favorites" tags):
  ```bash
  python goodreads_search.py --shelf "fantasy, favorites" --sort popularity --limit 5
  ```

### Step 5: Launch the GUI Browser
To run the interactive desktop app:
```bash
python goodreads_ui.py
```

---

## 📂 Codebase Details

*   [ol_data.py](file:///D:/LT/Novel_data/ol_data.py): Open Library extraction and ISBN generation script.
*   [goodreads_data.py](file:///D:/LT/Novel_data/goodreads_data.py): Main multi-threaded scraping script using Chromium controls and proxy relays.
*   [clean_checkpoint.py](file:///D:/LT/Novel_data/clean_checkpoint.py): Script to clear temporary network/WAF failure blocks from the scraper queue.
*   [goodreads_genres.py](file:///D:/LT/Novel_data/goodreads_genres.py): Cleanses, standardizes, enrich (from shelves), and populates database genres.
*   [goodreads_search.py](file:///D:/LT/Novel_data/goodreads_search.py): Core database indexing logic, CLI query engine, multi-value AND filtering, and sort inversion.
*   [goodreads_ui.py](file:///D:/LT/Novel_data/goodreads_ui.py): Python Tkinter GUI interface with full filter layout, sort directions dropdown, and genre tags.
*   [requirements.txt](file:///D:/LT/Novel_data/requirements.txt): List of dependencies.
*   [todo.md](file:///D:/LT/Novel_data/todo.md): Tracking notes on sources, attributes, and scraping schedules.
