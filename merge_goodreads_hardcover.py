import os
import sys
import csv
import json
import sqlite3
import argparse
from tqdm import tqdm

# Fix console encoding on Windows to prevent UnicodeEncodeErrors
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Increase CSV field size limit to prevent "_csv.Error: field larger than field limit"
maxInt = sys.maxsize
while True:
    try:
        csv.field_size_limit(maxInt)
        break
    except OverflowError:
        maxInt = int(maxInt / 10)


def ensure_columns_exist(conn):
    """Đảm bảo các cột mới để tích hợp dữ liệu từ Hardcover tồn tại trong bảng books."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(books)")
    cols = {col[1] for col in cursor.fetchall()}
    
    new_cols = {
        'moods': 'TEXT',
        'cover_id': 'INTEGER',
        'cover_url': 'TEXT',
        'cover_color': 'TEXT',
        'cover_width': 'INTEGER',
        'cover_height': 'INTEGER',
        'cover_color_name': 'TEXT',
        'hardcover_id': 'INTEGER',
        'hardcover_slug': 'TEXT',
        'hardcover_url': 'TEXT'
    }
    
    for col_name, col_type in new_cols.items():
        if col_name not in cols:
            print(f"Thêm cột '{col_name}' ({col_type}) vào bảng books...")
            cursor.execute(f"ALTER TABLE books ADD COLUMN {col_name} {col_type}")
    conn.commit()


def parse_csv_list(val):
    """Chuyển đổi chuỗi danh sách ngăn cách bởi dấu phẩy và khoảng trắng thành mảng."""
    if not val:
        return []
    return [x.strip() for x in val.split(', ') if x.strip()]


def safe_int(val, default=None):
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def safe_float(val, default=None):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def merge_data(db_path, csv_path, batch_size):
    """Thực hiện trộn dữ liệu từ Hardcover CSV vào Goodreads SQLite DB."""
    if not os.path.exists(db_path):
        print(f"Lỗi: Không tìm thấy cơ sở dữ liệu SQLite tại '{db_path}'")
        return
    if not os.path.exists(csv_path):
        print(f"Lỗi: Không tìm thấy file dữ liệu Hardcover CSV tại '{csv_path}'")
        return

    conn = sqlite3.connect(db_path)
    # Tối ưu hiệu năng ghi của SQLite
    conn.execute('PRAGMA synchronous = OFF')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA cache_size = 20000')
    
    print("Khởi tạo và kiểm tra cấu trúc cơ sở dữ liệu...")
    ensure_columns_exist(conn)
    
    cursor = conn.cursor()
    
    # 1. Tải bản đồ ánh xạ ISBN hiện tại từ cơ sở dữ liệu để tìm kiếm O(1)
    print("Đang tải ánh xạ ISBN và ID hiện có trong database...")
    isbn_to_bid = {}
    isbn13_to_bid = {}
    existing_hc_bids = set()
    
    cursor.execute("SELECT book_id, isbn, isbn13 FROM books")
    rows = cursor.fetchall()
    for bid, isbn, isbn13 in rows:
        if bid and bid.startswith("hc_"):
            existing_hc_bids.add(bid)
        if isbn and isbn.strip():
            isbn_to_bid[isbn.strip()] = bid
        if isbn13 and isbn13.strip():
            isbn13_to_bid[isbn13.strip()] = bid
            
    print(f"Đã tải {len(rows):,} bản ghi từ database (ISBN10: {len(isbn_to_bid):,}, ISBN13: {len(isbn13_to_bid):,}, HC-IDs: {len(existing_hc_bids):,}).")
    
    # Chuẩn bị truy vấn lấy raw_json và genres cho việc trộn
    select_meta_sql = "SELECT genres, raw_json, description FROM books WHERE book_id = ?"
    
    # Đọc tổng số dòng của CSV để hiển thị tiến trình
    total_csv_rows = 0
    with open(csv_path, 'r', encoding='utf-8') as f:
        total_csv_rows = sum(1 for _ in f) - 1
        
    print(f"Bắt đầu xử lý {total_csv_rows:,} dòng từ file Hardcover CSV...")
    
    updates = []
    inserts = []
    
    updated_count = 0
    inserted_count = 0
    
    update_sql = """
    UPDATE books SET
        moods = ?,
        cover_id = ?,
        cover_url = ?,
        cover_color = ?,
        cover_width = ?,
        cover_height = ?,
        cover_color_name = ?,
        hardcover_id = ?,
        hardcover_slug = ?,
        hardcover_url = ?,
        genres = ?,
        description = COALESCE(NULLIF(description, ''), ?),
        raw_json = ?
    WHERE book_id = ?
    """
    
    insert_sql = """
    INSERT INTO books (
        book_id, title, description, isbn, isbn13, average_rating, ratings_count, 
        text_reviews_count, publication_year, is_ebook, author_ids, genres, moods, 
        cover_id, cover_url, cover_color, cover_width, cover_height, cover_color_name, 
        hardcover_id, hardcover_slug, hardcover_url, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in tqdm(reader, total=total_csv_rows, desc="Trộn dữ liệu"):
            hc_id = row['id']
            title = row['title']
            subtitle = row['subtitle']
            slug = row['slug']
            desc = row['description']
            rating = safe_float(row['rating'])
            ratings_count = safe_int(row['ratings_count'], 0)
            reviews_count = safe_int(row['reviews_count'], 0)
            release_year = safe_int(row['release_year'])
            release_date = row['release_date']
            compilation = row['compilation']
            url_str = row['url']
            
            authors = parse_csv_list(row['authors'])
            hc_genres = parse_csv_list(row['genres'])
            tags = parse_csv_list(row['tags'])
            moods = parse_csv_list(row['moods'])
            
            isbn10 = row.get('isbn_10', '').strip()
            isbn13 = row.get('isbn_13', '').strip()
            cover_id = safe_int(row.get('cover_id'))
            cover_url = row.get('cover_url', '')
            cover_color = row.get('cover_color', '')
            cover_width = safe_int(row.get('cover_width'))
            cover_height = safe_int(row.get('cover_height'))
            cover_color_name = row.get('cover_color_name', '')
            
            # Kiểm tra xem sách đã tồn tại trong DB chưa
            matched_bid = None
            if isbn13 and isbn13 in isbn13_to_bid:
                matched_bid = isbn13_to_bid[isbn13]
            elif isbn10 and isbn10 in isbn_to_bid:
                matched_bid = isbn_to_bid[isbn10]
            elif f"hc_{hc_id}" in existing_hc_bids:
                matched_bid = f"hc_{hc_id}"
                
            if matched_bid:
                # ── SÁCH ĐÃ TỒN TẠI: TRỘN VÀ CẬP NHẬT ─────────────────────────────
                # Lấy dữ liệu cũ để trộn
                cursor.execute(select_meta_sql, (matched_bid,))
                meta = cursor.fetchone()
                
                db_genres_str, db_raw_json, db_desc = meta if meta else (None, None, None)
                
                # Trộn danh sách Genres
                genres_list = list(hc_genres)
                themes_list = []
                audiences_list = []
                
                if db_genres_str:
                    try:
                        g_obj = json.loads(db_genres_str)
                        if isinstance(g_obj, dict):
                            # Gộp danh sách
                            for g in g_obj.get('genres') or []:
                                if g not in genres_list:
                                    genres_list.append(g)
                            themes_list = g_obj.get('themes') or []
                            audiences_list = g_obj.get('audiences') or []
                    except Exception:
                        pass
                
                updated_genres_str = json.dumps({
                    "genres": genres_list,
                    "themes": themes_list,
                    "audiences": audiences_list
                }, ensure_ascii=False)
                
                # Trộn Raw JSON
                updated_raw_json_str = db_raw_json
                if db_raw_json:
                    try:
                        raw_dict = json.loads(db_raw_json)
                        if isinstance(raw_dict, dict):
                            # Cập nhật ảnh bìa và link nếu chưa có
                            if not raw_dict.get('image_url') and cover_url:
                                raw_dict['image_url'] = cover_url
                            
                            # Lưu trữ thông tin chi tiết của bìa cứng
                            raw_dict['cover_details'] = {
                                'id': cover_id,
                                'url': cover_url,
                                'color': cover_color,
                                'width': cover_width,
                                'height': cover_height,
                                'color_name': cover_color_name
                            }
                            raw_dict['hardcover_url'] = url_str
                            raw_dict['moods'] = moods
                            
                            # Cập nhật trường genres
                            raw_dict['genres'] = genres_list
                            updated_raw_json_str = json.dumps(raw_dict, ensure_ascii=False)
                    except Exception:
                        pass
                else:
                    # Nếu chưa có raw_json, tạo mới
                    raw_dict = {
                        'book_id': matched_bid,
                        'title': title,
                        'description': db_desc or desc,
                        'isbn': isbn10,
                        'isbn13': isbn13,
                        'average_rating': rating,
                        'image_url': cover_url,
                        'cover_details': {
                            'id': cover_id,
                            'url': cover_url,
                            'color': cover_color,
                            'width': cover_width,
                            'height': cover_height,
                            'color_name': cover_color_name
                        },
                        'hardcover_url': url_str,
                        'moods': moods,
                        'genres': genres_list
                    }
                    updated_raw_json_str = json.dumps(raw_dict, ensure_ascii=False)
                
                updates.append((
                    ", ".join(moods) if moods else None,
                    cover_id,
                    cover_url or None,
                    cover_color or None,
                    cover_width,
                    cover_height,
                    cover_color_name or None,
                    safe_int(hc_id),
                    slug,
                    url_str,
                    updated_genres_str,
                    desc, # Đối số cho COALESCE trường description
                    updated_raw_json_str,
                    matched_bid
                ))
                
                updated_count += 1
            else:
                # ── SÁCH CHƯA TỒN TẠI: THÊM MỚI TOÀN BỘ ──────────────────────────
                new_bid = f"hc_{hc_id}"
                
                # Tạo genres cấu trúc JSON
                new_genres_str = json.dumps({
                    "genres": hc_genres,
                    "themes": [],
                    "audiences": []
                }, ensure_ascii=False)
                
                # Tạo raw_json
                raw_dict = {
                    'book_id': new_bid,
                    'title': title,
                    'title_without_series': title,
                    'description': desc,
                    'isbn': isbn10,
                    'isbn13': isbn13,
                    'average_rating': rating,
                    'ratings_count': ratings_count,
                    'text_reviews_count': reviews_count,
                    'publication_year': release_year,
                    'image_url': cover_url,
                    'url': url_str,
                    'authors': [{'author_id': '', 'name': name} for name in authors],
                    'cover_details': {
                        'id': cover_id,
                        'url': cover_url,
                        'color': cover_color,
                        'width': cover_width,
                        'height': cover_height,
                        'color_name': cover_color_name
                    },
                    'moods': moods,
                    'genres': hc_genres
                }
                raw_json_str = json.dumps(raw_dict, ensure_ascii=False)
                
                inserts.append((
                    new_bid,
                    title,
                    desc,
                    isbn10 or None,
                    isbn13 or None,
                    rating,
                    ratings_count,
                    reviews_count,
                    release_year,
                    1 if compilation == 'True' else 0,
                    f",hc_author," if authors else "",
                    new_genres_str,
                    ", ".join(moods) if moods else None,
                    cover_id,
                    cover_url or None,
                    cover_color or None,
                    cover_width,
                    cover_height,
                    cover_color_name or None,
                    safe_int(hc_id),
                    slug,
                    url_str,
                    raw_json_str
                ))
                
                # Thêm vào ánh xạ tạm thời để tránh bị trùng lặp trong cùng một đợt CSV
                if isbn10:
                    isbn_to_bid[isbn10] = new_bid
                if isbn13:
                    isbn13_to_bid[isbn13] = new_bid
                    
                inserted_count += 1
                
            # Thực thi ghi theo lô (batch_size) để đảm bảo tốc độ tối đa
            if len(updates) >= batch_size:
                cursor.executemany(update_sql, updates)
                conn.commit()
                updates = []
                
            if len(inserts) >= batch_size:
                cursor.executemany(insert_sql, inserts)
                conn.commit()
                inserts = []

        # Thực thi nốt các bản ghi còn lại
        if updates:
            cursor.executemany(update_sql, updates)
            conn.commit()
        if inserts:
            cursor.executemany(insert_sql, inserts)
            conn.commit()
            
    conn.close()
    
    print("\nQuá trình trộn hoàn tất thành công!")
    print(f"  - Số sách được cập nhật (trộn thêm thông tin): {updated_count:,}")
    print(f"  - Số sách chưa có và được chèn mới: {inserted_count:,}")
    print(f"Cơ sở dữ liệu '{db_path}' đã được đồng bộ hóa và lưu trữ.")


def main():
    parser = argparse.ArgumentParser(description="Trộn dữ liệu sách Hardcover vào cơ sở dữ liệu Goodreads SQLite")
    parser.add_argument("--db", default=os.path.join("goodreads", "goodreads_books.db"), help="Đường dẫn đến file cơ sở dữ liệu SQLite (mặc định: goodreads/goodreads_books.db)")
    parser.add_argument("--csv", default=os.path.join("hardcover", "hardcover_books.csv"), help="Đường dẫn đến file dữ liệu Hardcover CSV (mặc định: hardcover/hardcover_books.csv)")
    parser.add_argument("--batch-size", type=int, default=1000, help="Kích thước lô giao dịch ghi cơ sở dữ liệu (mặc định: 1000)")
    
    args = parser.parse_args()
    
    merge_data(args.db, args.csv, args.batch_size)


if __name__ == '__main__':
    main()
