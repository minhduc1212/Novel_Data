import os
import sys
import threading
import webbrowser
import json
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter

# Import search functions from our search module
import goodreads_search

# Configure CustomTkinter
customtkinter.set_appearance_mode("Dark")  # Options: "System", "Light", "Dark"
customtkinter.set_default_color_theme("blue")  # Themes: "blue", "green", "dark-blue"

class GoodreadsApp(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        # Window configuration
        self.title("Goodreads Novel Search Engine")
        self.geometry("1280x800")
        self.minimum_width = 1000
        self.minimum_height = 600
        self.minsize(self.minimum_width, self.minimum_height)

        # Application state variables
        self.data_path = goodreads_search.data_path
        if not os.path.exists(self.data_path) and os.path.exists("goodreads_books.json"):
            self.data_path = os.path.abspath("goodreads_books.json")
            
        self.db_path = "goodreads_books.db"
        self.current_page = 1
        self.results_per_page = 10
        self.total_results_count = 0
        self.search_results = []
        self.is_searching = False
        self.is_indexing = False

        # Grid configuration (1 row, 2 columns: Sidebar & Main Content)
        self.grid_columnconfigure(0, weight=0, minsize=320)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Create sidebar and main content frame
        self.create_sidebar()
        self.create_main_content()

        # Check initial database index status
        self.update_db_status_ui()

    def create_sidebar(self):
        # Sidebar Frame
        self.sidebar_frame = customtkinter.CTkFrame(self, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar_frame.grid_rowconfigure(10, weight=1)  # spacer row

        # App Logo / Title
        self.logo_label = customtkinter.CTkLabel(
            self.sidebar_frame, 
            text="📚 Goodreads Browser", 
            font=customtkinter.CTkFont(family="Segoe UI", size=20, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # Database Status Section
        self.db_status_frame = customtkinter.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.db_status_frame.grid(row=1, column=0, padx=15, pady=10, sticky="ew")
        self.db_status_frame.grid_columnconfigure(0, weight=1)

        self.db_status_title = customtkinter.CTkLabel(
            self.db_status_frame, 
            text="DATABASE INDEX STATUS", 
            font=customtkinter.CTkFont(size=10, weight="bold")
        )
        self.db_status_title.grid(row=0, column=0, sticky="w", padx=5)

        self.db_status_value = customtkinter.CTkLabel(
            self.db_status_frame, 
            text="Checking index status...", 
            font=customtkinter.CTkFont(size=12), 
            text_color="gray"
        )
        self.db_status_value.grid(row=1, column=0, sticky="w", padx=5, pady=(2, 5))

        self.build_index_btn = customtkinter.CTkButton(
            self.db_status_frame, 
            text="Build/Rebuild SQLite Index",
            command=self.start_indexing_thread,
            font=customtkinter.CTkFont(size=12, weight="bold")
        )
        self.build_index_btn.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        # Index progress bar & label (hidden by default)
        self.index_progress_bar = customtkinter.CTkProgressBar(self.db_status_frame)
        self.index_progress_bar.grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        self.index_progress_bar.set(0)
        self.index_progress_bar.grid_remove()

        self.index_progress_label = customtkinter.CTkLabel(
            self.db_status_frame, 
            text="", 
            font=customtkinter.CTkFont(size=11)
        )
        self.index_progress_label.grid(row=4, column=0, sticky="w", padx=5)
        self.index_progress_label.grid_remove()

        # Separator line
        self.separator = customtkinter.CTkFrame(self.sidebar_frame, height=2, fg_color="#333")
        self.separator.grid(row=2, column=0, sticky="ew", padx=15, pady=10)

        # Filters Title
        self.filters_label = customtkinter.CTkLabel(
            self.sidebar_frame, 
            text="SEARCH FILTERS", 
            font=customtkinter.CTkFont(family="Segoe UI", size=13, weight="bold")
        )
        self.filters_label.grid(row=3, column=0, padx=20, pady=(10, 5), sticky="w")

        # Scrollable Filters Frame
        self.filters_scroll = customtkinter.CTkScrollableFrame(self.sidebar_frame, fg_color="transparent")
        self.filters_scroll.grid(row=4, column=0, sticky="nsew", padx=10, pady=5)
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        # Language Filter
        self.lang_label = customtkinter.CTkLabel(self.filters_scroll, text="Language Code", font=customtkinter.CTkFont(size=12))
        self.lang_label.pack(anchor="w", padx=5, pady=(5, 2))
        self.lang_menu = customtkinter.CTkComboBox(
            self.filters_scroll, 
            values=["All", "eng", "spa", "fre", "ger", "ita", "jpn", "mul", "en-US", "en-GB"]
        )
        self.lang_menu.pack(fill="x", padx=5, pady=(0, 10))
        self.lang_menu.set("All")

        # Rating Filter (Min / Max Sliders)
        self.rating_label_frame = customtkinter.CTkFrame(self.filters_scroll, fg_color="transparent")
        self.rating_label_frame.pack(fill="x", padx=5, pady=(5, 2))
        self.rating_title = customtkinter.CTkLabel(self.rating_label_frame, text="Min Average Rating", font=customtkinter.CTkFont(size=12))
        self.rating_title.pack(side="left")
        self.rating_val_label = customtkinter.CTkLabel(self.rating_label_frame, text="0.0", font=customtkinter.CTkFont(size=12, weight="bold"))
        self.rating_val_label.pack(side="right")

        self.rating_slider = customtkinter.CTkSlider(
            self.filters_scroll, 
            from_=0.0, 
            to=5.0, 
            number_of_steps=50,
            command=self.update_rating_slider_label
        )
        self.rating_slider.pack(fill="x", padx=5, pady=(0, 10))
        self.rating_slider.set(0.0)

        # Reviews Count Filter
        self.reviews_label = customtkinter.CTkLabel(self.filters_scroll, text="Min Reviews Count", font=customtkinter.CTkFont(size=12))
        self.reviews_label.pack(anchor="w", padx=5, pady=(5, 2))
        self.reviews_entry = customtkinter.CTkEntry(self.filters_scroll, placeholder_text="e.g. 100")
        self.reviews_entry.pack(fill="x", padx=5, pady=(0, 10))

        # Year Range Filters
        self.year_label = customtkinter.CTkLabel(self.filters_scroll, text="Publication Year Range", font=customtkinter.CTkFont(size=12))
        self.year_label.pack(anchor="w", padx=5, pady=(5, 2))
        self.year_frame = customtkinter.CTkFrame(self.filters_scroll, fg_color="transparent")
        self.year_frame.pack(fill="x", padx=5, pady=0)
        self.year_min_entry = customtkinter.CTkEntry(self.year_frame, placeholder_text="Min Year", width=100)
        self.year_min_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.year_max_entry = customtkinter.CTkEntry(self.year_frame, placeholder_text="Max Year", width=100)
        self.year_max_entry.pack(side="right", fill="x", expand=True, padx=(5, 0))

        # Ebook Filter
        self.ebook_label = customtkinter.CTkLabel(self.filters_scroll, text="Format Type", font=customtkinter.CTkFont(size=12))
        self.ebook_label.pack(anchor="w", padx=5, pady=(15, 2))
        self.ebook_menu = customtkinter.CTkOptionMenu(
            self.filters_scroll, 
            values=["All Formats", "Ebooks Only", "No Ebooks"]
        )
        self.ebook_menu.pack(fill="x", padx=5, pady=(0, 10))
        self.ebook_menu.set("All Formats")

        # Shelf Tag Filter
        self.shelf_label = customtkinter.CTkLabel(self.filters_scroll, text="Popular Shelf / Tag", font=customtkinter.CTkFont(size=12))
        self.shelf_label.pack(anchor="w", padx=5, pady=(5, 2))
        self.shelf_entry = customtkinter.CTkEntry(self.filters_scroll, placeholder_text="e.g. fantasy")
        self.shelf_entry.pack(fill="x", padx=5, pady=(0, 10))

        # Author ID Filter
        self.author_label = customtkinter.CTkLabel(self.filters_scroll, text="Author ID", font=customtkinter.CTkFont(size=12))
        self.author_label.pack(anchor="w", padx=5, pady=(5, 2))
        self.author_entry = customtkinter.CTkEntry(self.filters_scroll, placeholder_text="e.g. 1077326")
        self.author_entry.pack(fill="x", padx=5, pady=(0, 10))

        # Publisher Filter
        self.publisher_label = customtkinter.CTkLabel(self.filters_scroll, text="Publisher Name", font=customtkinter.CTkFont(size=12))
        self.publisher_label.pack(anchor="w", padx=5, pady=(5, 2))
        self.publisher_entry = customtkinter.CTkEntry(self.filters_scroll, placeholder_text="e.g. Scholastic")
        self.publisher_entry.pack(fill="x", padx=5, pady=(0, 15))

        # Reset button
        self.reset_filters_btn = customtkinter.CTkButton(
            self.sidebar_frame, 
            text="Reset Filters",
            command=self.reset_filters,
            fg_color="#D9534F",
            hover_color="#C9302C",
            font=customtkinter.CTkFont(size=12, weight="bold")
        )
        self.reset_filters_btn.grid(row=5, column=0, padx=20, pady=(5, 10), sticky="ew")

        # Dataset Settings button
        self.settings_btn = customtkinter.CTkButton(
            self.sidebar_frame, 
            text="Select JSON Data Path",
            command=self.change_data_path,
            fg_color="#4B5563",
            hover_color="#374151",
            font=customtkinter.CTkFont(size=11)
        )
        self.settings_btn.grid(row=6, column=0, padx=20, pady=(5, 20), sticky="ew")

    def create_main_content(self):
        # Main Frame
        self.main_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=0)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        # Search Bar Area (Row 0)
        self.search_bar_frame = customtkinter.CTkFrame(self.main_frame, fg_color="transparent")
        self.search_bar_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=(20, 10))
        self.search_bar_frame.grid_columnconfigure(0, weight=1)

        # Query Input
        self.search_entry = customtkinter.CTkEntry(
            self.search_bar_frame, 
            placeholder_text="Search book title or description keywords...",
            height=40,
            font=customtkinter.CTkFont(size=14)
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.search_entry.bind("<Return>", lambda event: self.trigger_search())

        # Search Button
        self.search_btn = customtkinter.CTkButton(
            self.search_bar_frame, 
            text="Search", 
            width=100, 
            height=40,
            command=self.trigger_search,
            font=customtkinter.CTkFont(size=14, weight="bold")
        )
        self.search_btn.grid(row=0, column=1, padx=(0, 10))

        # Sort Order Options
        self.sort_menu = customtkinter.CTkOptionMenu(
            self.search_bar_frame,
            values=["Popularity", "Average Rating", "Reviews Count", "Publish Year"],
            width=130,
            height=40,
            command=lambda val: self.trigger_search()
        )
        self.sort_menu.grid(row=0, column=2, padx=(0, 0))
        self.sort_menu.set("Popularity")

        # Results area (Row 1) - Scrollable list of book cards
        self.results_frame = customtkinter.CTkScrollableFrame(self.main_frame, corner_radius=8)
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=10)
        self.results_frame.grid_columnconfigure(0, weight=1)

        # Center label in results frame for status (No books / Loading...)
        self.status_label = customtkinter.CTkLabel(
            self.results_frame,
            text="Enter a query or click search to browse books.",
            font=customtkinter.CTkFont(size=14, slant="italic"),
            text_color="gray"
        )
        self.status_label.grid(row=0, column=0, pady=200, sticky="nsew")

        # Pagination & Stats Bar (Row 2)
        self.pagination_frame = customtkinter.CTkFrame(self.main_frame, fg_color="transparent")
        self.pagination_frame.grid(row=2, column=0, sticky="ew", padx=0, pady=(5, 15))
        self.pagination_frame.grid_columnconfigure(1, weight=1)

        # Previous Page Button
        self.prev_btn = customtkinter.CTkButton(
            self.pagination_frame, 
            text="◀ Prev", 
            width=80,
            command=self.prev_page,
            state="disabled"
        )
        self.prev_btn.grid(row=0, column=0, padx=(5, 10))

        # Page Stats Label
        self.page_label = customtkinter.CTkLabel(
            self.pagination_frame, 
            text="Page 1", 
            font=customtkinter.CTkFont(size=13, weight="bold")
        )
        self.page_label.grid(row=0, column=1, sticky="w")

        self.stats_label = customtkinter.CTkLabel(
            self.pagination_frame, 
            text="No results", 
            font=customtkinter.CTkFont(size=13)
        )
        self.stats_label.grid(row=0, column=1, sticky="e", padx=(0, 10))

        # Next Page Button
        self.next_btn = customtkinter.CTkButton(
            self.pagination_frame, 
            text="Next ▶", 
            width=80,
            command=self.next_page,
            state="disabled"
        )
        self.next_btn.grid(row=0, column=2, padx=(10, 5))

    def update_rating_slider_label(self, value):
        self.rating_val_label.configure(text=f"{value:.1f}")

    def update_db_status_ui(self):
        # Queries the database status from the search module
        exists, msg = goodreads_search.check_index_status(self.db_path)
        if exists:
            self.db_status_value.configure(text=msg, text_color="#5CB85C")
            self.build_index_btn.configure(text="Rebuild SQLite Index", fg_color="#0275D8", hover_color="#025AA5")
        else:
            self.db_status_value.configure(text="No Index Database Found.", text_color="#D9534F")
            self.build_index_btn.configure(text="Build SQLite Index", fg_color="#F0AD4E", hover_color="#EC971F")

    def reset_filters(self):
        # Resets all sidebar controls to their default state
        self.lang_menu.set("All")
        self.rating_slider.set(0.0)
        self.rating_val_label.configure(text="0.0")
        self.reviews_entry.delete(0, "end")
        self.year_min_entry.delete(0, "end")
        self.year_max_entry.delete(0, "end")
        self.ebook_menu.set("All Formats")
        self.shelf_entry.delete(0, "end")
        self.author_entry.delete(0, "end")
        self.publisher_entry.delete(0, "end")

    def change_data_path(self):
        # Open a file selection dialog to set the raw goodreads JSON path
        filepath = filedialog.askopenfilename(
            title="Select Goodreads Books JSON File",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if filepath:
            self.data_path = filepath
            goodreads_search.data_path = filepath
            messagebox.showinfo("Data Path Updated", f"Active dataset file set to:\n{filepath}")
            self.update_db_status_ui()
            # Clear current UI results
            for widget in self.results_frame.winfo_children():
                widget.destroy()
            self.status_label = customtkinter.CTkLabel(
                self.results_frame,
                text=f"Dataset loaded: {os.path.basename(filepath)}\nReady to search.",
                font=customtkinter.CTkFont(size=14, slant="italic"),
                text_color="gray"
            )
            self.status_label.grid(row=0, column=0, pady=200, sticky="ew")

    def start_indexing_thread(self):
        if self.is_indexing:
            return
        
        # Check if source file exists
        if not os.path.exists(self.data_path):
            messagebox.showerror(
                "File Not Found", 
                f"Cannot find source dataset at:\n{self.data_path}\nPlease click 'Select JSON Data Path' to choose a valid file."
            )
            return
            
        confirm = messagebox.askyesno(
            "Confirm Indexing",
            "This will create a new SQLite index database to allow instant searches.\n"
            "This process is optimized and takes ~3 minutes for 2.3M books.\n"
            "Do you want to proceed?"
        )
        if not confirm:
            return

        self.is_indexing = True
        self.build_index_btn.configure(state="disabled", text="Indexing...")
        self.index_progress_bar.grid()
        self.index_progress_bar.set(0)
        self.index_progress_label.grid()
        self.index_progress_label.configure(text="Preparing data...", text_color="white")

        # Start indexing in background thread so the UI does not freeze
        thread = threading.Thread(target=self.run_indexing, daemon=True)
        thread.start()

    def run_indexing(self):
        try:
            # We pass a callback to track progress in real-time
            success = goodreads_search.build_index(self.data_path, self.db_path, self.on_indexing_progress)
            if success:
                self.after(0, self.on_indexing_completed, True, "Successfully indexed books!")
            else:
                self.after(0, self.on_indexing_completed, False, "Indexing failed.")
        except Exception as e:
            self.after(0, self.on_indexing_completed, False, f"Error: {e}")

    def on_indexing_progress(self, total_count, pct, speed):
        # Progress callback safely scheduled to run on the main thread via self.after
        def update_ui():
            self.index_progress_bar.set(pct / 100.0)
            if pct >= 100.0:
                self.index_progress_label.configure(text=f"Finishing database build...", text_color="white")
            else:
                self.index_progress_label.configure(
                    text=f"Indexed {total_count:,} books... {pct:.1f}% ({speed:.1f} MB/s)",
                    text_color="#F0AD4E"
                )
        self.after(0, update_ui)

    def on_indexing_completed(self, success, message):
        self.is_indexing = False
        self.build_index_btn.configure(state="normal")
        self.index_progress_bar.grid_remove()
        self.index_progress_label.grid_remove()
        self.update_db_status_ui()
        if success:
            messagebox.showinfo("Success", "SQLite Indexing fully completed! You can now run instant queries.")
        else:
            messagebox.showerror("Error", f"Failed to build index:\n{message}")

    def trigger_search(self, page=1):
        if self.is_searching:
            return
        
        self.current_page = page
        self.is_searching = True
        self.search_btn.configure(state="disabled", text="Searching...")
        
        # Clear results panel
        for widget in self.results_frame.winfo_children():
            widget.destroy()
            
        # Re-create and show loading state
        self.status_label = customtkinter.CTkLabel(
            self.results_frame,
            text="🔍 Searching database, please wait...",
            font=customtkinter.CTkFont(size=15, weight="bold"),
            text_color="#0275D8"
        )
        self.status_label.grid(row=0, column=0, pady=200, sticky="ew")
        self.results_frame.grid_columnconfigure(0, weight=1)

        # Gather inputs from GUI
        search_query = self.search_entry.get().strip()
        lang_filter = self.lang_menu.get().strip()
        if lang_filter == "All":
            lang_filter = None
            
        min_rating = self.rating_slider.get()
        if min_rating <= 0.0:
            min_rating = None
            
        reviews_val = self.reviews_entry.get().strip()
        min_reviews = int(reviews_val) if (reviews_val.isdigit()) else None

        min_year_val = self.year_min_entry.get().strip()
        year_min = int(min_year_val) if (min_year_val.isdigit()) else None

        max_year_val = self.year_max_entry.get().strip()
        year_max = int(max_year_val) if (max_year_val.isdigit()) else None

        ebook_val = self.ebook_menu.get()
        is_ebook = None
        if ebook_val == "Ebooks Only":
            is_ebook = True
        elif ebook_val == "No Ebooks":
            is_ebook = False

        shelf = self.shelf_entry.get().strip()
        if not shelf:
            shelf = None

        author = self.author_entry.get().strip()
        if not author:
            author = None

        publisher = self.publisher_entry.get().strip()
        if not publisher:
            publisher = None

        sort_val = self.sort_menu.get()
        sort_by = 'popularity'
        if sort_val == "Average Rating":
            sort_by = 'rating'
        elif sort_val == "Reviews Count":
            sort_by = 'reviews'
        elif sort_val == "Publish Year":
            sort_by = 'year'

        # Pagination params
        offset = (self.current_page - 1) * self.results_per_page
        limit = self.results_per_page

        # Launch search in a background thread
        search_args = {
            "title_query": search_query,
            "rating_min": min_rating,
            "reviews_min": min_reviews,
            "publication_year_min": year_min,
            "publication_year_max": year_max,
            "language_code": lang_filter,
            "is_ebook": is_ebook,
            "shelf": shelf,
            "author_id": author,
            "publisher_query": publisher,
            "sort_by": sort_by,
            "limit": limit,
            "offset": offset
        }

        thread = threading.Thread(target=self.run_search_query, args=(search_args,), daemon=True)
        thread.start()

    def run_search_query(self, search_args):
        t0 = time.time()
        books = []
        error_msg = None
        use_db = False
        
        # Determine if we should query database or stream
        db_exists, _ = goodreads_search.check_index_status(self.db_path)
        if db_exists:
            use_db = True

        try:
            if use_db:
                books = goodreads_search.search_database(
                    db_path=self.db_path,
                    data_path=self.data_path,
                    **search_args
                )
            else:
                books = goodreads_search.search_streaming(
                    data_path=self.data_path,
                    **search_args
                )
        except Exception as e:
            error_msg = str(e)

        elapsed = time.time() - t0
        # Send results to main UI thread
        self.after(0, self.display_search_results, books, elapsed, error_msg, use_db)

    def display_search_results(self, books, elapsed_seconds, error_msg, used_db):
        self.is_searching = False
        self.search_btn.configure(state="normal", text="Search")
        
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        if error_msg:
            self.status_label = customtkinter.CTkLabel(
                self.results_frame,
                text=f"❌ Search Error:\n{error_msg}",
                font=customtkinter.CTkFont(size=14),
                text_color="#D9534F"
            )
            self.status_label.grid(row=0, column=0, pady=200, sticky="ew")
            self.stats_label.configure(text="Error occurred")
            self.prev_btn.configure(state="disabled")
            self.next_btn.configure(state="disabled")
            return

        self.search_results = books
        total_found = len(books)
        
        # Update pagination buttons state
        self.prev_btn.configure(state="normal" if self.current_page > 1 else "disabled")
        # Since we don't do a full COUNT SQL query (to keep performance instant),
        # we check if we found exactly the limit of results. If yes, there is likely a next page.
        self.next_btn.configure(state="normal" if total_found == self.results_per_page else "disabled")
        self.page_label.configure(text=f"Page {self.current_page}")

        # Update stats text
        db_label = "DB Mode" if used_db else "Streaming Mode"
        if total_found == 0:
            self.stats_label.configure(text=f"No matches found ({db_label} - {elapsed_seconds:.3f}s)")
            self.status_label = customtkinter.CTkLabel(
                self.results_frame,
                text="No books found matching these filters.",
                font=customtkinter.CTkFont(size=14, slant="italic"),
                text_color="gray"
            )
            self.status_label.grid(row=0, column=0, pady=200, sticky="ew")
            return

        # Display performance stats
        range_start = (self.current_page - 1) * self.results_per_page + 1
        range_end = range_start + total_found - 1
        self.stats_label.configure(
            text=f"Showing books {range_start}-{range_end} | Query time: {elapsed_seconds:.3f}s ({db_label})"
        )

        # Build book cards
        for idx, book in enumerate(books):
            self.build_book_card(book, idx)

    def build_book_card(self, book, row_index):
        title = book.get('title') or book.get('title_without_series') or 'Unknown Title'
        book_id = book.get('book_id', 'N/A')
        isbn = book.get('isbn') or book.get('isbn13') or book.get('asin') or 'N/A'
        avg_rating = book.get('average_rating', '0.0')
        ratings_count = book.get('ratings_count', '0')
        reviews_count = book.get('text_reviews_count', '0')
        lang = book.get('language_code') or 'N/A'
        pub = book.get('publisher') or 'N/A'
        year = book.get('publication_year') or 'N/A'
        fmt = book.get('format') or ('Ebook' if str(book.get('is_ebook')).lower() == 'true' else 'Paperback/N/A')
        
        # Resolve authors
        authors_list = []
        authors = book.get('authors') or []
        if isinstance(authors, list):
            for a in authors:
                if isinstance(a, dict) and a.get('author_id'):
                    role_str = f" ({a['role']})" if a.get('role') else ""
                    authors_list.append(f"Author {a['author_id']}{role_str}")
        authors_str = ", ".join(authors_list) if authors_list else "N/A"

        # Resolve shelves
        shelves_list = []
        shelves = book.get('popular_shelves') or []
        if isinstance(shelves, list):
            for s in shelves[:5]:
                if isinstance(s, dict) and s.get('name'):
                    shelves_list.append(s['name'])
        shelves_str = ", ".join(shelves_list) if shelves_list else "N/A"

        # Main Card Frame
        card_frame = customtkinter.CTkFrame(self.results_frame, corner_radius=8)
        card_frame.grid(row=row_index, column=0, sticky="ew", padx=5, pady=6)
        card_frame.grid_columnconfigure(0, weight=1)

        # Title Label
        title_lbl = customtkinter.CTkLabel(
            card_frame, 
            text=title, 
            font=customtkinter.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#3498DB",
            anchor="w",
            justify="left"
        )
        title_lbl.grid(row=0, column=0, columnspan=2, sticky="w", padx=15, pady=(10, 2))

        # Metadata Row 1: Authors & ID/ISBN
        meta1_lbl = customtkinter.CTkLabel(
            card_frame, 
            text=f"By: {authors_str}   |   ISBN: {isbn}   |   Book ID: {book_id}",
            font=customtkinter.CTkFont(size=11),
            text_color="gray",
            anchor="w"
        )
        meta1_lbl.grid(row=1, column=0, columnspan=2, sticky="w", padx=15, pady=2)

        # Metadata Row 2: Ratings
        ratings_str = f"⭐ {avg_rating}  ({int(ratings_count):,} ratings, {int(reviews_count):,} reviews)"
        meta2_lbl = customtkinter.CTkLabel(
            card_frame, 
            text=ratings_str,
            font=customtkinter.CTkFont(size=12, weight="bold"),
            text_color="#F0AD4E",
            anchor="w"
        )
        meta2_lbl.grid(row=2, column=0, columnspan=2, sticky="w", padx=15, pady=2)

        # Metadata Row 3: Format, Pub, Year, Language, Shelves
        details_str = f"Language: {lang}  •  Format: {fmt}  •  Publisher: {pub} ({year})  •  Shelves: {shelves_str}"
        meta3_lbl = customtkinter.CTkLabel(
            card_frame,
            text=details_str,
            font=customtkinter.CTkFont(size=11),
            text_color="#B5B5B5",
            anchor="w"
        )
        meta3_lbl.grid(row=3, column=0, columnspan=2, sticky="w", padx=15, pady=(2, 10))

        # Description text snippet
        desc = book.get('description') or ""
        if desc:
            clean_desc = desc.replace('\n', ' ').strip()
            if len(clean_desc) > 160:
                clean_desc = clean_desc[:160] + "..."
            desc_lbl = customtkinter.CTkLabel(
                card_frame,
                text=clean_desc,
                font=customtkinter.CTkFont(size=12, slant="italic"),
                text_color="#E0E0E0",
                anchor="w",
                justify="left",
                wraplength=800
            )
            desc_lbl.grid(row=4, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 10))

        # Action Buttons Frame
        btn_frame = customtkinter.CTkFrame(card_frame, fg_color="transparent")
        btn_frame.grid(row=5, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 12))

        # Details button
        details_btn = customtkinter.CTkButton(
            btn_frame, 
            text="View Full Details", 
            width=130, 
            height=28,
            command=lambda b=book: self.open_detail_popup(b)
        )
        details_btn.pack(side="left", padx=(0, 10))

        # Link button (Goodreads url)
        book_url = book.get('link') or book.get('url')
        if book_url:
            link_btn = customtkinter.CTkButton(
                btn_frame, 
                text="Open on Goodreads 🌐", 
                width=150, 
                height=28,
                fg_color="#4B5563",
                hover_color="#374151",
                command=lambda url=book_url: webbrowser.open(url)
            )
            link_btn.pack(side="left")

    def prev_page(self):
        if self.current_page > 1:
            self.trigger_search(self.current_page - 1)

    def next_page(self):
        self.trigger_search(self.current_page + 1)

    def open_detail_popup(self, book):
        # Create full detail popup
        DetailPopup(self, book)

    def search_similar_book_id(self, book_id):
        # Clears search bar, enters ID, resets filters, and searches
        self.reset_filters()
        self.search_entry.delete(0, "end")
        self.author_entry.delete(0, "end")
        self.shelf_entry.delete(0, "end")
        
        # Enter ID filter and search
        self.id_filter_to_inject = book_id
        # We temporarily inject a value in the search query or search by ID
        # Let's populate the query field with the book ID and search
        self.search_entry.insert(0, "") # clear
        
        # Actually, let's inject book_id into the id filter directly
        # Wait, there's no visible ID entry in the filters, but we can set it.
        # Let's set ID filter on the search
        self.trigger_search_by_id(book_id)

    def trigger_search_by_id(self, book_id):
        if self.is_searching:
            return
        
        self.current_page = 1
        self.is_searching = True
        self.search_btn.configure(state="disabled", text="Searching...")
        
        # Clear results panel
        for widget in self.results_frame.winfo_children():
            widget.destroy()
            
        self.status_label = customtkinter.CTkLabel(
            self.results_frame,
            text=f"🔍 Loading book ID {book_id}...",
            font=customtkinter.CTkFont(size=15, weight="bold"),
            text_color="#0275D8"
        )
        self.status_label.grid(row=0, column=0, pady=200, sticky="ew")

        search_args = {
            "book_id_query": book_id,
            "limit": 1,
            "offset": 0
        }
        
        thread = threading.Thread(target=self.run_search_query, args=(search_args,), daemon=True)
        thread.start()


class DetailPopup(customtkinter.CTkToplevel):
    def __init__(self, parent_app, book):
        super().__init__(parent_app)
        
        self.parent_app = parent_app
        self.book = book
        title = book.get('title') or book.get('title_without_series') or 'Book Details'
        
        self.title(f"Goodreads Book Details - {title[:50]}")
        self.geometry("800x650")
        self.minsize(600, 450)
        self.transient(parent_app)  # Keep on top of main window
        self.grab_set()             # Block interaction with parent
        
        # Layout configure
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # Description textbox row

        # 1. Header Frame (Title and stats)
        header_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        header_frame.grid_columnconfigure(0, weight=1)

        title_lbl = customtkinter.CTkLabel(
            header_frame,
            text=title,
            font=customtkinter.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#3498DB",
            justify="left",
            wraplength=760
        )
        title_lbl.grid(row=0, column=0, sticky="w")

        # Stats sub-frame
        stats_txt = (
            f"⭐ Rating: {book.get('average_rating', '0.0')}  •  "
            f"Ratings Count: {int(book.get('ratings_count', '0')):,}  •  "
            f"Reviews Count: {int(book.get('text_reviews_count', '0')):,}\n"
            f"ISBN: {book.get('isbn', 'N/A')}  |  ISBN13: {book.get('isbn13', 'N/A')}  |  ASIN: {book.get('asin', 'N/A')}  |  Book ID: {book.get('book_id')}"
        )
        stats_lbl = customtkinter.CTkLabel(
            header_frame,
            text=stats_txt,
            font=customtkinter.CTkFont(size=12),
            text_color="#B5B5B5",
            justify="left"
        )
        stats_lbl.grid(row=1, column=0, sticky="w", pady=(5, 5))

        # Details table frame
        details_frame = customtkinter.CTkFrame(self)
        details_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=10)
        details_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Create table key-values
        pub = book.get('publisher') or 'N/A'
        year = book.get('publication_year') or 'N/A'
        month = book.get('publication_month') or 'N/A'
        day = book.get('publication_day') or 'N/A'
        pub_date = f"{year}-{month}-{day}".replace("-N/A-N/A", "").replace("-N/A", "")
        
        self.add_table_cell(details_frame, "Language", book.get('language_code') or 'N/A', 0, 0)
        self.add_table_cell(details_frame, "Publisher", pub, 0, 1)
        self.add_table_cell(details_frame, "Published Date", pub_date, 0, 2)
        self.add_table_cell(details_frame, "Pages Count", book.get('num_pages') or 'N/A', 0, 3)
        self.add_table_cell(details_frame, "Format", book.get('format') or 'N/A', 1, 0)
        self.add_table_cell(details_frame, "Is Ebook", str(book.get('is_ebook')), 1, 1)
        self.add_table_cell(details_frame, "Country", book.get('country_code') or 'N/A', 1, 2)
        self.add_table_cell(details_frame, "Edition", book.get('edition_information') or 'Standard', 1, 3)

        # 2. Description (Middle Scrollable TextBox)
        desc_title = customtkinter.CTkLabel(
            self,
            text="DESCRIPTION",
            font=customtkinter.CTkFont(size=11, weight="bold")
        )
        desc_title.grid(row=2, column=0, sticky="w", padx=20, pady=(10, 2))

        self.desc_box = customtkinter.CTkTextbox(self, font=customtkinter.CTkFont(size=13), wrap="word")
        self.desc_box.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 15))
        
        desc_text = book.get('description') or "No description available for this book."
        self.desc_box.insert("0.0", desc_text)
        self.desc_box.configure(state="disabled")

        # 3. Bottom Panels: Popular Shelves & Similar Books
        bottom_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 20))
        bottom_frame.grid_columnconfigure(0, weight=1, minsize=350)
        bottom_frame.grid_columnconfigure(1, weight=1, minsize=350)

        # Popular Shelves List
        shelves_sub = customtkinter.CTkFrame(bottom_frame)
        shelves_sub.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        shelves_lbl = customtkinter.CTkLabel(shelves_sub, text="Popular Shelves", font=customtkinter.CTkFont(size=12, weight="bold"))
        shelves_lbl.pack(anchor="w", padx=10, pady=5)
        
        shelves = book.get('popular_shelves') or []
        shelves_box = customtkinter.CTkTextbox(shelves_sub, height=100, font=customtkinter.CTkFont(size=11))
        shelves_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        shelves_list = []
        for s in shelves:
            if isinstance(s, dict) and s.get('name'):
                cnt = f" ({s['count']})" if s.get('count') else ""
                shelves_list.append(f"• {s['name']}{cnt}")
        
        shelves_box.insert("0.0", "\n".join(shelves_list) if shelves_list else "No popular shelves information.")
        shelves_box.configure(state="disabled")

        # Similar Books List (Clickable IDs!)
        similar_sub = customtkinter.CTkFrame(bottom_frame)
        similar_sub.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        
        similar_lbl = customtkinter.CTkLabel(similar_sub, text="Similar Books (Click to Load)", font=customtkinter.CTkFont(size=12, weight="bold"))
        similar_lbl.pack(anchor="w", padx=10, pady=5)

        similar_books = book.get('similar_books') or []
        
        # Scrollable container for similar book buttons
        sim_scroll = customtkinter.CTkScrollableFrame(similar_sub, height=90)
        sim_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        if similar_books:
            for sim_id in similar_books:
                btn = customtkinter.CTkButton(
                    sim_scroll,
                    text=f"Book ID: {sim_id}",
                    font=customtkinter.CTkFont(size=11),
                    height=22,
                    fg_color="#334155",
                    hover_color="#475569",
                    command=lambda sid=sim_id: self.navigate_to_similar_book(sid)
                )
                btn.pack(fill="x", pady=2)
        else:
            no_sim_lbl = customtkinter.CTkLabel(sim_scroll, text="No similar book references.", font=customtkinter.CTkFont(size=11, slant="italic"))
            no_sim_lbl.pack(pady=20)

    def add_table_cell(self, parent, label_text, value_text, row, col):
        cell_frame = customtkinter.CTkFrame(parent, fg_color="transparent")
        cell_frame.grid(row=row, column=col, padx=10, pady=5, sticky="nsew")
        
        lbl = customtkinter.CTkLabel(cell_frame, text=label_text, font=customtkinter.CTkFont(size=10, weight="bold"), text_color="gray")
        lbl.pack(anchor="w")
        
        val = customtkinter.CTkLabel(cell_frame, text=value_text, font=customtkinter.CTkFont(size=11), wraplength=170, justify="left")
        val.pack(anchor="w")

    def navigate_to_similar_book(self, book_id):
        # Close this modal dialog
        self.grab_release()
        self.destroy()
        # Trigger query in main app
        self.parent_app.search_similar_book_id(book_id)


if __name__ == "__main__":
    app = GoodreadsApp()
    app.mainloop()
