# Goodreads Novel Scraper & SQLite Search Engine Pipeline

An advanced, end-to-end Python pipeline designed to scrape, clean, index, and browse massive book datasets. The system extracts novel metadata from raw Open Library dumps, scrapes Goodreads using a multi-threaded headless browser framework capable of bypassing WAF/Cloudflare blocks, cleans scrape checkpoints, builds a SQLite database search index supporting both scraped formats and public Kaggle datasets, and provides both a CLI search engine and a modern dark-theme GUI browser built with `customtkinter`.

---

## 📌 System Architecture

The pipeline consists of five key steps, starting from raw public data dumps to an interactive search GUI.

```mermaid
graph TD
    A[Open Library 59GB Dump] -->|ol_data.py| B(clean_novel_isbns.txt)
    B -->|goodreads_data.py| C{Goodreads Scraper}
    C -->|DrissionPage & proxies| D[(goodreads_books.json / csv)]
    C -.->|WAF block log| E(goodreads_scraper.log)
    E -->|clean_checkpoint.py| F(goodreads_checkpoint.json)
    F -.->|Restore clean ISBNs| C
    D -->|goodreads_search.py| G[(goodreads_books.db)]
    G -->|goodreads_search.py| H[CLI Search Engine]
    G -->|goodreads_ui.py| I[CustomTkinter Desktop GUI]
```

---

## 🛠️ Components & Features

### 1. Ingestion & ISBN Filtering ([ol_data.py](file:///D:/LT/Novel_data/ol_data.py))
* **Goal**: Processes raw Open Library dumps (often 50GB+) to filter for novels and extract unique ISBNs.
* **Keyword Filter**: Detects genres like fiction, novel, romance, fantasy, mystery, thriller, horror, young adult, etc.
* **Negative Exclusions**: Strips non-novel formats like textbook, manual, guide, dictionary, encyclopedia, biography, manga, comics, academic, and poetry.
* **Performance**: Stream-reads the dump line-by-line using binary buffer seek, matching key text before JSON deserialization (`json.loads`) to minimize memory load and CPU time.

### 2. Resilient Goodreads Scraper ([goodreads_data.py](file:///D:/LT/Novel_data/goodreads_data.py))
* **WAF/Cloudflare Bypassing**: Uses [DrissionPage](https://github.com/g1879/DrissionPage) to control Chromium directly. Unlike standard `requests` or Selenium/Puppeteer, it is highly resistant to bot-detection mechanisms and processes Cloudflare/AWS challenges naturally.
* **Multi-Threaded**: Spawns multiple Chromium instances crawling concurrently with staggered startups.
* **Local Proxy Relay ([LocalProxyRelay](file:///D:/LT/Novel_data/goodreads_data.py#L394-L496))**: Features a lightweight local TCP tunnel server per thread that dynamically injects basic authentication credentials into HTTP/SOCKS5 proxy requests.
* **RAM & Disk Optimizations ([make_chrome_options](file:///D:/LT/Novel_data/goodreads_data.py#L501-L578))**: 
  - Disables media (images, audio, video) loading.
  - Limits Chromium to one renderer process.
  - Caps V8 javascript heap at 256MB.
  - Employs sandbox-disabled configurations and uses a per-thread temp folder for profiles to prevent disk write thrashing.
* **Data Extraction**: Resolves Next.js page states via `__NEXT_DATA__` for complete accuracy, capturing title, description, average points, counts (ratings, reviews, currently reading, want to read), full genres, and the top 10 reviews (with date, author details, like counts, and spoiler status). Falls back to DOM selectors on script fail.
* **Atomic Append persistence ([save_book_data](file:///D:/LT/Novel_data/goodreads_data.py#L328-L386))**: Performs O(1) tail-append operations to add JSON objects directly inside the closing array tag (`]`), avoiding complete rewrites.
* **Checkpoints**: Persists active state (`failed_isbns`, `duplicate_isbns`, and `non_english_isbns`) in `goodreads_checkpoint.json` for crash safety and deduplication.

### 3. Checkpoint Recovery & Refiner ([clean_checkpoint.py](file:///D:/LT/Novel_data/clean_checkpoint.py))
* **Goal**: Automatically scans the execution logs (`goodreads_scraper.log`).
* **Logic**: Extracts ISBNs that failed solely because of temporary `403 Forbidden` WAF challenges and cleanses them from `failed_isbns` in `goodreads_checkpoint.json`. This permits them to be retried on subsequent scraping passes instead of being permanently skipped.

### 4. High-Performance SQLite Search Engine ([goodreads_search.py](file:///D:/LT/Novel_data/goodreads_search.py))
* **Indexing**: Indexes JSON datasets into a local SQLite database (`goodreads_books.db`) using transaction batching.
* **Schema Adaptability**: Normalizes and indexes both the custom scraped format (with uppercase keys) and public Kaggle datasets (e.g. UCSD book review datasets with lowercase schemas).
* **Storage Modes**:
  - **JSON Lines format**: Stores byte offsets and length markers in the database for zero-memory seek queries back into the main text data.
  - **Standard JSON Array**: Fallback stores raw JSON records directly in the SQLite database columns.
* **Filtering & Sorting**: Provides a rich CLI for filtering by title, ISBN, average rating range, review count limits, pub year, ebook formats, author, publisher, and shelf tags. Supports pagination and sorting by popularity (ratings count), average score, reviews, and year.

### 5. CustomTkinter Desktop GUI ([goodreads_ui.py](file:///D:/LT/Novel_data/goodreads_ui.py))
* **User Interface**: Built on [customtkinter](https://github.com/TomSchimansky/CustomTkinter) featuring a dark theme layout.
* **Features**:
  - **Index Management**: Checks database indexing status and allows building/rebuilding SQLite indexes with an in-app progress bar.
  - **Filters Sidebar**: Includes range controls (average rating slider, publication year bounds, minimum reviews), menus (language codes, ebook options), and entry boxes (tags/shelves, authors, publishers).
  - **Interactive Results**: Displays paginated book cards showing description excerpts, rating stars, and details. Double-clicking or pressing details opens the official Goodreads book web page directly in the default browser.

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
*   `--threads`: Number of simultaneous browser crawling processes (default: `4`).
*   `--headless`: Whether to run Chromium in hidden headless mode (default: `False`). Staggers browser window positions off-screen to avoid distraction.
*   `--delay-min` / `--delay-max`: Random interval bounds between pages.

If you want to test the scraper logic on a single book page:
```bash
python goodreads_1data.py
```

### Step 3: Refine Failed Checkpoints
If proxies get temporarily blocked (403 errors), reset their status in the checkpoint before starting the next scrape:
```bash
python clean_checkpoint.py
```

### Step 4: Index and Search via CLI
1. **Build SQLite index from JSON database**:
   ```bash
   python goodreads_search.py --build-index
   ```
2. **Perform Searches**:
   * Search books by title matching "Mistborn":
     ```bash
     python goodreads_search.py --search "Mistborn"
     ```
   * Search with multiple criteria (Rating >= 4.2, English only, sorted by rating):
     ```bash
     python goodreads_search.py --rating-min 4.2 --lang "eng" --sort "rating" --limit 5
     ```
   * Other filters: `--isbn`, `--year-min`, `--year-max`, `--reviews-min`, `--publisher`, `--author`, `--shelf`.

### Step 5: Launch the GUI Browser
To run the interactive desktop app:
```bash
python goodreads_ui.py
```

---

## 📂 Codebase Details

*   [ol_data.py](file:///D:/LT/Novel_data/ol_data.py): Open Library extraction and ISBN generation script.
*   [goodreads_data.py](file:///D:/LT/Novel_data/goodreads_data.py): Main multi-threaded scraping script using Chromium controls and proxy relays.
*   [goodreads_1data.py](file:///D:/LT/Novel_data/goodreads_1data.py): Test script for downloading metadata from a single Goodreads URL.
*   [clean_checkpoint.py](file:///D:/LT/Novel_data/clean_checkpoint.py): Script to clear temporary network/WAF failure blocks from the scraper queue.
*   [goodreads_search.py](file:///D:/LT/Novel_data/goodreads_search.py): Core database indexing logic and command-line query engine.
*   [goodreads_ui.py](file:///D:/LT/Novel_data/goodreads_ui.py): Python Tkinter GUI interface with full filter layout.
*   [requirements.txt](file:///D:/LT/Novel_data/requirements.txt): List of dependencies.
*   [todo.md](file:///D:/LT/Novel_data/todo.md): Tracking notes on sources, attributes, and scraping schedules.

---

## 📈 Performance & Reliability Enhancements

*   **Chromium Process Cap**: Passing `--renderer-process-limit=1` and `--js-flags=--max-old-space-size=256` ensures low memory footprint when running multiple scraper threads.
*   **WAF Integration Bypass**: Rather than writing custom Cloudflare scrapers that easily break, running Chromium directly allows it to evaluate challenges normally. The scraper automatically monitors states and pauses if WAF challenge scripts are found, resuming once the page completes loading.
*   **Fast DB Pagination**: SQLite indexes created on columns (`title`, `isbn`, `average_rating`, etc.) keep database lookups under 2-3ms, even on datasets with millions of records.
