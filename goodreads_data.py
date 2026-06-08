import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

def get_goodreads_data(url):
    """
    Scrape book details from a Goodreads book URL.
    This scraper parses the Next.js '__NEXT_DATA__' cache block to get the complete
    set of fields, including all genres and the detailed data of the 10 best reviews.
    If '__NEXT_DATA__' parsing fails, it falls back to standard DOM scraping.
    
    Args:
        url (str): The Goodreads book page URL.
        
    Returns:
        dict: A dictionary containing:
            - Title: Cleaned title of the book.
            - Desc: Full text description of the book.
            - Genre: Complete list of genre names associated with the book.
            - Review: List of the 10 best reviews (each with Author, AuthorUrl, Rating, Likes, Date, Spoiler, Text).
            - Point: The average rating score (e.g., 4.48).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching page {url}: {e}")
        return {
            "Title": None,
            "Desc": None,
            "Genre": [],
            "Review": [],
            "Point": 0.0
        }
        
    soup = BeautifulSoup(response.text, "html.parser")
    
    title = None
    desc = None
    genres = []
    reviews_list = []
    point = 0.0

    # 1. Try parsing Next.js __NEXT_DATA__ first (contains full list of genres, reviews, and clean metadata)
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
                        desc = BeautifulSoup(desc_html, "html.parser").text.strip()
                
                # Get all genres (including those hidden under "Show more")
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
                        clean_text = BeautifulSoup(raw_text, "html.parser").text.strip() if raw_text else ""
                        
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
        except Exception:
            pass

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

    return {
        "Title": title,
        "Desc": desc,
        "Genre": genres,
        "Review": reviews_list,
        "Point": point
    }

if __name__ == "__main__":
    import sys
    # Avoid UnicodeEncodeError on Windows terminals
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    url = "https://www.goodreads.com/book/show/68428.Mistborn"
    print(f"Scraping Goodreads page: {url}\n")
    data = get_goodreads_data(url)
    
    for key, val in data.items():
        if key == "Desc" and val:
            print(f"{key}: {val}")
        elif key == "Review" and isinstance(val, list):
            print(f"{key} (10 Best Reviews):")
            for i, r in enumerate(val):
                snippet = r['Text'].replace('\n', ' ') 
                print(f"  {i+1}. {r['Author']} ({r['Rating']} stars, {r['Likes']} likes): {snippet}")
        else:
            print(f"{key}: {val}")
