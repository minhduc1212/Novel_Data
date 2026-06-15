# Goodreads & Hardcover Novel Data Scraper, SQLite Search Engine & Genre Analytics Pipeline

An advanced, end-to-end Python pipeline designed to filter, crawl, clean, enrich, index, merge, and browse massive book datasets. The system extracts novel metadata from raw 59GB Open Library dumps, crawls Goodreads using a multi-threaded headless browser framework capable of bypassing Web Application Firewalls (WAF) and Cloudflare blocks, refines checkpoints from logs, crawls cover designs and reader moods from the Hardcover GraphQL API, backfills and classifies genres, and indexes everything into a high-performance SQLite database. Finally, it exposes a multi-dimensional CLI search engine and a modern dark-theme GUI browser built with `customtkinter`.

---

## 📌 System Architecture & Data Flow

The pipeline operates in three distinct phases: Ingestion & Extraction, Enrichment & Merging, and Querying & Visualization.

```mermaid
graph TD
    %% Phase 1: Ingestion & Goodreads Scraping
    subgraph Phase 1: Ingestion & Scraping
        OL[Open Library 59GB Dump] -->|ol_data.py| OL_Clean(clean_novel_isbns.txt)
        OL_Clean -->|goodreads_data.py| GR_Scraper{Goodreads Scraper}
        GR_Scraper -->|DrissionPage & local proxy relay| GR_Raw[(goodreads_books.json / csv)]
        GR_Scraper -.->|WAF block logs| LOG(goodreads_scraper.log)
        LOG -->|clean_checkpoint.py| CKPT(goodreads_checkpoint.json)
        CKPT -.->|Restore/Retry Failed ISBNs| GR_Scraper
    end

    %% Phase 2: Indexing & Enrichment
    subgraph Phase 2: Indexing & Enrichment
        GR_Raw -->|goodreads_search.py --build-index| DB[(goodreads_books.db)]
        GEN_INIT[goodreads_book_genres_initial.json] -->|goodreads_genres.py| DB
        
        %% Hardcover Crawling & Integration
        HC_API{Hardcover GraphQL API} -->|hardcover_api.py| HC_Raw(hardcover_books.csv / json)
        HC_Raw -->|merge_goodreads_hardcover.py| DB
    end

    %% Phase 3: Access & Search
    subgraph Phase 3: Access & Search
        DB -->|goodreads_search.py --search| CLI[CLI Search Engine]
        DB -->|goodreads_ui.py| GUI[CustomTkinter Desktop GUI]
    end

    style GR_Scraper fill:#f9f,stroke:#333,stroke-width:2px
    style HC_API fill:#9cf,stroke:#333,stroke-width:2px
    style DB fill:#ff9,stroke:#333,stroke-width:2px
```

---

## 📂 Codebase Details & File Directory

| File | Description | Target Inputs / Outputs |
| :--- | :--- | :--- |
| **[ol_data.py](file:///D:/LT/Novel_data/ol_data.py)** | Stream-reads massive Open Library JSON dumps to isolate novel-specific ISBNs using subjects matching and blacklist keywords. | Input: `F:/Data/ol_data.txt`<br>Output: `clean_novel_isbns.txt` |
| **[goodreads_data.py](file:///D:/LT/Novel_data/goodreads_data.py)** | Multi-threaded Chromium web-crawler utilizing DrissionPage and TCP credential-injection proxy tunnels to bypass WAFs and retrieve Goodreads pages. | Input: `clean_novel_isbns.txt`<br>Output: `goodreads_books.json`, `goodreads_books.csv`, `goodreads_checkpoint.json` |
| **[goodreads_1data.py](file:///D:/LT/Novel_data/goodreads_1data.py)** | Lightweight scraper using standard Python `requests` and `BeautifulSoup` to scrape and parse a single Goodreads page (extracts JSON `__NEXT_DATA__` page states). | Input: URL (e.g. Mistborn page)<br>Output: Console metadata prints |
| **[clean_checkpoint.py](file:///D:/LT/Novel_data/clean_checkpoint.py)** | Scans logs to identify temporary `403 Forbidden` WAF challenges and deletes these ISBNs from the checkpoint skip-list to allow retry sweeps. | Input: `goodreads_scraper.log`<br>Output: Updates `goodreads_checkpoint.json` |
| **[goodreads_genres.py](file:///D:/LT/Novel_data/goodreads_genres.py)** | Standardizes, cleanses, and maps raw user-defined shelf tags into three database dimensions: genres, themes/tropes, and target audiences/formats. | Input: `goodreads_book_genres_initial.json`<br>Output: Updates `genres` column in `goodreads_books.db` |
| **[goodreads_search.py](file:///D:/LT/Novel_data/goodreads_search.py)** | Compiles the SQLite database from scraped JSON, sets up indexes, and runs CLI search queries via native `json_extract()` SQL matches. | Input: `goodreads_books.json` or `goodreads_books.db`<br>Output: CLI result prints or CSV/JSON queries |
| **[goodreads_ui.py](file:///D:/LT/Novel_data/goodreads_ui.py)** | Interactive CustomTkinter desktop GUI browser featuring complex sidebar filters, ratings sorting, paginated results, and detail popup cards. | Input: `goodreads_books.db`<br>Output: Desktop UI interface |
| **[hardcover_api.py](file:///D:/LT/Novel_data/hardcover_api.py)** | High-throughput multi-threaded client querying Hardcover's GraphQL API for cover colors, image paths, page dimensions, reader moods, and metadata. | Input: Hardcover GraphQL API endpoint<br>Output: `hardcover_books.json`, `hardcover_books.csv`, `hardcover_checkpoint.json` |
| **[merge_goodreads_hardcover.py](file:///D:/LT/Novel_data/merge_goodreads_hardcover.py)** | Performs batch updates to enrich existing SQLite records with Hardcover cover metrics, reader moods, and adds any unmatched books. | Input: `hardcover_books.csv`<br>Output: Updates `goodreads_books.db` |
| **[todo.md](file:///D:/LT/Novel_data/todo.md)** | Task list tracking research paths, data sources (Wikidata, isfdb, RanobeDB, etc.), and planned workflows. | Task tracking |

---

## 🛠️ Detailed Component Analysis

### 1. Ingestion & ISBN Filtering ([ol_data.py](file:///D:/LT/Novel_data/ol_data.py))
* **Keywords Checked**: `fiction`, `novel`, `romance`, `fantasy`, `mystery`, `thriller`, `horror`, `science fiction`, `historical fiction`, `young adult`, `literary fiction`.
* **Exclusion List**: Discards non-novel formats like `non-fiction`, `biography`, `textbook`, `manual`, `guide`, `dictionary`, `encyclopedia`, `comic`, `manga`, `poetry`, `academic`.
* **Performance Optimization**: Scans files using a fast generator line split loop before calling the heavy `json.loads()` parser. This allows it to scan a 59GB dump in under an hour on a standard SSD.

### 2. Resilient Goodreads Scraper ([goodreads_data.py](file:///D:/LT/Novel_data/goodreads_data.py))
* **Bot-Bypass Engine**: Powered by [DrissionPage](https://github.com/g1879/DrissionPage) to control Chromium directly. It behaves identically to human browsers, letting Cloudflare and AWS challenge-defense pages resolve transparently.
* **Per-Thread Proxy relays**: Bypasses the browser's lack of support for authentication-protected proxies by running a lightweight local TCP tunnel server on each worker thread. The TCP server intercepts browser requests, appends proxy authentication headers, and relays traffic.
* **Data Parsing Strategy**: Extracts variables directly from the script tag containing `__NEXT_DATA__`. This caches apollo-state fields, bypassing pagination to scrape all book genres, reviews, and reading statistics instantly. It falls back to BeautifulSoup DOM parsing if javascript blocks fail to load.

### 3. Checkpoint Refiner ([clean_checkpoint.py](file:///D:/LT/Novel_data/clean_checkpoint.py))
* **WAF Self-Healing**: Network issues or proxy failures can cause requests to yield a `403 Forbidden` block. `goodreads_data.py` flags these as failures, but `clean_checkpoint.py` parses logs to find these temporary failures and removes them from the failed queue so they are retried in subsequent rounds.

### 4. Classification & Enrichment ([goodreads_genres.py](file:///D:/LT/Novel_data/goodreads_genres.py))
* **Tag Cleansing**: Filters out user status tags (e.g. `read-in-2018`, `favorites`, `abandoned`, `kindle`, `paperback`) using `BLACKLIST_KEYWORDS`.
* **Standardized Shelf Categories**: Map shelf keywords into standard categories:
  * **Genres**: `fantasy`, `science fiction`, `mystery`, `thriller`, `romance`, `horror`, `biography`, etc.
  * **Themes & Tropes**: `magic`, `wizards`, `dragons`, `paranormal`, `dystopian`, `steampunk`, `cyberpunk`, `time travel`, `grimdark`.
  * **Target Audiences & Formats**: `young adult`, `middle grade`, `children`, `new adult`, `adult`, `graphic novel`, `manga`, `comics`.
* **Structured Output**: Saves classifications to the SQLite `genres` column as a structured JSON object:
  ```json
  {"genres": ["fantasy", "epic fantasy"], "themes": ["magic", "dragons"], "audiences": ["adult"]}
  ```

### 5. GraphQL Hardcover Scraper ([hardcover_api.py](file:///D:/LT/Novel_data/hardcover_api.py))
* **GraphQL Crawl**: Accesses `https://api.hardcover.app/v1/graphql` to retrieve rich book covers and reader moods.
* **Multi-threaded Worker**: Employs a `ThreadPoolExecutor` where threads retrieve blocks of offset ranges (configured via `--batch-size`) and append results to output files safely using a file write lock.
* **Command Arguments**:
  * `-t`, `--threads` (default: `4`): Number of parallel network crawlers.
  * `-l`, `--limit` (default: `0`): Cap on total books fetched (`0` fetches everything).
  * `-b`, `--batch-size` (default: `1000`): Books retrieved per GraphQL call.
  * `-o`, `--offset` (default: `0`): Starting offset index.
  * `-d`, `--delay` (default: `0.1`): Throttling delay between thread requests.

### 6. SQLite Database Merger ([merge_goodreads_hardcover.py](file:///D:/LT/Novel_data/merge_goodreads_hardcover.py))
* **Schema Alterations**: Dynamically appends Hardcover attributes to the standard `books` table structure (see the Database Schema below).
* **O(1) Memory Lookup**: Preloads the database's ISBN mapping into memory hashtables to resolve record matches in constant time.
* **Enrichment Logic**: If a book matches an existing Goodreads record via ISBN/ISBN13, it appends the cover links, main colors, and reader moods. If no matching record is found, it inserts a new record (prefixed with `hc_` as `book_id`).

---

## 🗄️ Database Schema (`books` table)

The `goodreads_books.db` file stores all processed records in the `books` table:

| Column | SQLite Type | Source | Description |
| :--- | :--- | :--- | :--- |
| **`book_id`** | TEXT (PK) | Goodreads / Hardcover | The unique book ID (Hardcover IDs are prefixed with `hc_`). |
| **`title`** | TEXT | Goodreads / Hardcover | Title of the novel. |
| **`description`** | TEXT | Goodreads / Hardcover | Cleaned description or synopsis of the book. |
| **`isbn`** | TEXT | Goodreads / Hardcover | 10-digit International Standard Book Number. |
| **`isbn13`** | TEXT | Goodreads / Hardcover | 13-digit International Standard Book Number. |
| **`asin`** | TEXT | Goodreads | Amazon Standard Identification Number. |
| **`average_rating`** | REAL | Goodreads / Hardcover | Average user rating out of 5.0. |
| **`ratings_count`** | INTEGER | Goodreads / Hardcover | Total number of user ratings. |
| **`text_reviews_count`**| INTEGER | Goodreads / Hardcover | Total number of text reviews written. |
| **`publication_year`** | INTEGER | Goodreads / Hardcover | Year the book was published. |
| **`publisher`** | TEXT | Goodreads | Name of the publisher. |
| **`language_code`** | TEXT | Goodreads | Language code of the book (e.g. `eng`, `spa`). |
| **`is_ebook`** | INTEGER | Goodreads | Binary flag (0 or 1) indicating if the book is an ebook. |
| **`author_ids`** | TEXT | Goodreads | Comma-separated list of Goodreads Author IDs. |
| **`popular_shelves`** | TEXT | Goodreads | Comma-separated list of raw shelf tags. |
| **`genres`** | TEXT (JSON) | Goodreads / Hardcover | Structured JSON: `{"genres": [...], "themes": [...], "audiences": [...]}`. |
| **`offset`** | INTEGER | Indexer | Record byte offset within `goodreads_books.json`. |
| **`length`** | INTEGER | Indexer | Record byte length within `goodreads_books.json`. |
| **`raw_json`** | TEXT (JSON) | Goodreads / Hardcover | Raw, unmodified JSON payload. |
| **`moods`** | TEXT | Hardcover | Comma-separated list of reader moods (e.g. `emotional, dark`). |
| **`cover_id`** | INTEGER | Hardcover | The unique cover image ID from Hardcover. |
| **`cover_url`** | TEXT | Hardcover | Direct web URL to the book cover image. |
| **`cover_color`** | TEXT | Hardcover | Hex color code of the dominant cover color (e.g. `#5a4d41`). |
| **`cover_width`** | INTEGER | Hardcover | Width of the cover image in pixels. |
| **`cover_height`** | INTEGER | Hardcover | Height of the cover image in pixels. |
| **`cover_color_name`** | TEXT | Hardcover | Text representation of the cover's dominant color. |
| **`hardcover_id`** | INTEGER | Hardcover | Unique identification number from Hardcover. |
| **`hardcover_slug`** | TEXT | Hardcover | Slug identifier from Hardcover. |
| **`hardcover_url`** | TEXT | Hardcover | Full hyperlink to the book on hardcover.app. |

---

## 🚀 Installation & Environment Setup

### 1. Initialize the Virtual Environment
Navigate to the project directory and create a virtual environment:
```powershell
# Navigate to the working directory
cd D:\LT\Novel_data

# Create the python virtual environment
python -m venv .venv

# Activate the environment (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Activate the environment (Linux / macOS)
source .venv/bin/activate
```

### 2. Install Project Dependencies
Run `pip` to install all necessary browser automation, layout, UI, and data components:
```bash
pip install -r requirements.txt
pip install customtkinter DrissionPage beautifulsoup4 lxml requests tqdm
```

### 3. Setup Proxy and API Tokens
Create a [.env](file:///D:/LT/Novel_data/.env) file in the root folder to house proxy parameters:
```ini
# Add SOCKS5 or HTTP proxies separated by commas
PROXIES=http://user:pass@proxy1_ip:port,socks5://user:pass@proxy2_ip:port
```
Configure your personal token directly in [hardcover_api.py](file:///D:/LT/Novel_data/hardcover_api.py) under `HARDCOVER_API_TOKEN` if crawling new hardcover entries.

---

## 📖 Operational Run Guide

### Step 1: Filter raw Open Library dumps
Ensure your Open Library dump is configured in `ol_data.py` and run it:
```bash
python ol_data.py
```
This writes all isolated novel ISBNs to `clean_novel_isbns.txt`.

### Step 2: Crawl Goodreads book information
Launch the scraper to crawl metadata for the filtered ISBNs:
```bash
python goodreads_data.py --threads 4 --delay-min 3.0 --delay-max 6.0 --headless True
```
> [!TIP]
> If the scraper gets blocked or network interrupts occur, you can repair the checkpoints by running:
> ```bash
> python clean_checkpoint.py
> ```
> Then run `goodreads_data.py` again to resume operations automatically.

### Step 3: Crawl Cover Art and Reader Moods
Fetch cover and mood details from the Hardcover API:
```bash
python hardcover_api.py --threads 8 --batch-size 1000 --limit 50000
```
This saves data to `hardcover_books.csv` and `hardcover_books.json`.

### Step 4: Build Database & Integrate Data
1. **Build index from Goodreads JSON**:
   ```bash
   python goodreads_search.py --build-index
   ```
2. **Standardize and classify genres**:
   ```bash
   python goodreads_genres.py
   ```
3. **Merge Hardcover attributes into the database**:
   ```bash
   python merge_goodreads_hardcover.py --db goodreads_books.db --csv hardcover_books.csv
   ```

---

## 🔍 Search Engine & CLI Query Usage

The CLI search tool (`goodreads_search.py`) supports fast SQLite queries with multi-dimensional criteria matching:

### Query Parameters

| Flag | Argument Type | Description |
| :--- | :--- | :--- |
| `--search` | String | Performs a wildcard `LIKE` search on both title and description. |
| `--genre` | Comma-separated strings | Matches all specified genre classifications (AND logic). |
| `--theme` | Comma-separated strings | Matches all specified theme/trope classifications (AND logic). |
| `--audience`| Comma-separated strings | Matches all specified audience categories (AND logic). |
| `--mood` | Comma-separated strings | Matches all specified reader moods (AND logic). |
| `--sort` | `rating`, `reviews`, `year`, `popularity` | Metric to sort search results. |
| `--sort-dir`| `asc` or `desc` | Ordering direction. Set `asc` to perform **Sort Inversion** (e.g. worst rated). |
| `--limit` | Integer | Limits total output records. |

### CLI Query Examples

* **Find Grimdark Magic Books**: Searches for books matching core genre `fantasy`, themes `magic` and `grimdark`, sorted by average rating (best-to-worst):
  ```bash
  python goodreads_search.py --genre "fantasy" --theme "magic, grimdark" --sort rating --sort-dir desc --limit 5
  ```

* **Search by Target Audience**: Find Young Adult fantasy novels with high popularity:
  ```bash
  python goodreads_search.py --genre "fantasy" --audience "young adult" --sort popularity --limit 5
  ```

* **Sort Inversion Example (Worst Sci-Fi)**: Finds Science Fiction books sorted by average rating in ascending order:
  ```bash
  python goodreads_search.py --genre "science fiction" --sort rating --sort-dir asc --limit 5
  ```

* **Search by Mood & Theme**: Matches books tagged with the theme `space opera` and reader mood `mysterious`:
  ```bash
  python goodreads_search.py --theme "space opera" --mood "mysterious" --sort rating --limit 5
  ```

---

## 🖥️ Graphical User Interface Desktop App

To launch the dark-themed desktop application:
```bash
python goodreads_ui.py
```

### GUI Features & Controls
* **Paginated Result Cards**: Renders search results on custom cards showing title, author names, description synopses, rating metrics, cover colors (if matched), and tags.
* **Granular Filters Sidebar**: Employs three dedicated search inputs to match specific **Genres**, **Themes & Tropes**, and **Target Audience / Formats** alongside keywords.
* **Interactive Modals**: Click on any book card to trigger a popup modal that groups genres, themes, and audiences into separate sections, display cover dimensions, and reviews list.
* **Database Management Panel**: View real-time database counts and launch indexing jobs directly from the sidebar.

> [!NOTE]
> The GUI application runs database search queries on background threads to ensure the UI remains fully responsive during heavy searches.
