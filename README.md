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

### 4. Structured Classification & Enrichment ([goodreads_genres.py](file:///D:/LT/Novel_data/goodreads_genres.py))
* **Goal**: Cleanses, standardizes, and classifies book genres into distinct dimensions: **Genres**, **Themes & Tropes**, and **Target Audiences / Formats** stored in the database.
* **Ingestion**: Processes `goodreads_book_genres_initial.json` (190MB JSON Lines file) and database records.
* **Multi-Dimensional Classification**:
  - **Blacklist Filter**: Discards formatting/status noise tags (like `ebook`, `audiobook`, `calibre`, `read-in-2016`, `tbr`, `standalone`) by checking shelves against a comprehensive `BLACKLIST_KEYWORDS` array.
  - **Shelf Mapping & Classification**: Decides whether a tag is a core genre, a theme/trope, or a target audience/format based on the `SHELF_CLASSIFICATION` mapping.
  - **Structured Storage**: Encodes classifications as a structured JSON object in the SQLite `genres` column: `{"genres": [...], "themes": [...], "audiences": [...]}`.
* **Database Updates**: Efficiently backfills the database in batches, classifying and updating **2,006,966 book records**.

### 5. High-Performance SQLite Search Engine ([goodreads_search.py](file:///D:/LT/Novel_data/goodreads_search.py))
* **Indexing**: Rebuilds the SQLite database index from the raw JSON file while compiling structured classifications.
* **Multi-Dimensional AND Filtering**: 
  - Translates queries using SQLite's native `json_extract()` functions (e.g. `json_extract(genres, '$.themes') LIKE '%"magic"%'`) for high-performance `AND`-matching.
  - Supports `--genre`, `--theme`, and `--audience` CLI arguments, each allowing multiple comma-separated values matching all terms (AND logic).
  - **Sort Inversion**: Supports choosing sorting directions via `--sort-dir asc` (worst-to-best / inverse rating) or `--sort-dir desc` (best-to-worst / default).
  - **Streaming Fallback**: Parses and builds structured classifications on the fly if running in streaming mode (without SQLite index).

### 6. CustomTkinter Desktop GUI ([goodreads_ui.py](file:///D:/LT/Novel_data/goodreads_ui.py))
* **User Interface**: Built on [customtkinter](https://github.com/TomSchimansky/CustomTkinter) featuring a modern dark theme layout.
* **Features**:
  - **Interactive Results**: Displays paginated book cards showing description excerpts, rating stars, and details.
  - **Filters Sidebar**: Replaces the single generic genre input with three distinct sidebar search entry fields: **Genre**, **Theme & Trope**, and **Audience / Format** supporting comma-separated `AND` queries.
  - **Detailed Card View**: Renders the cleaned Genres, Themes, and Audiences separately on result cards.
  - **Book Details**: Displays detailed book info in a popup modal, grouping classifications under distinct *Genres*, *Themes & Tropes*, and *Target Audience / Format* sections.

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
* Search books matching multiple classification filters: core genre `fantasy`, theme `magic` and `grimdark`, sorted by rating (best-to-worst):
  ```bash
  python goodreads_search.py --genre "fantasy" --theme "magic, grimdark" --sort rating --sort-dir desc --limit 5
  ```
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

### Step 6: Crawl New Releases Automatically (Auto-Get)
To scan Goodreads monthly releases from 2017 to 2026, identify missing books, and automatically crawl and insert them into the database:
```bash
python goodreads_autoget.py
```

---

## 📂 Codebase Details

*   [ol_data.py](file:///D:/LT/Novel_data/ol_data.py): Open Library extraction and ISBN generation script.
*   [goodreads_data.py](file:///D:/LT/Novel_data/goodreads_data.py): Main multi-threaded scraping script using Chromium controls and proxy relays.
*   [goodreads_autoget.py](file:///D:/LT/Novel_data/goodreads_autoget.py): Auto-get script which logs into Gmail, crawls monthly new releases from 2017 to 2026, and inserts missing books into the database.
*   [clean_checkpoint.py](file:///D:/LT/Novel_data/clean_checkpoint.py): Script to clear temporary network/WAF failure blocks from the scraper queue.
*   [goodreads_genres.py](file:///D:/LT/Novel_data/goodreads_genres.py): Cleanses, standardizes, enrich (from shelves), and populates database genres.
*   [goodreads_search.py](file:///D:/LT/Novel_data/goodreads_search.py): Core database indexing logic, CLI query engine, multi-value AND filtering, and sort inversion.
*   [goodreads_ui.py](file:///D:/LT/Novel_data/goodreads_ui.py): Python Tkinter GUI interface with full filter layout, sort directions dropdown, and genre tags.
*   [requirements.txt](file:///D:/LT/Novel_data/requirements.txt): List of dependencies.
*   [todo.md](file:///D:/LT/Novel_data/todo.md): Tracking notes on sources, attributes, and scraping schedules.
