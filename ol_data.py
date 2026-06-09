import json
from tqdm import tqdm
import time

data_path = "F:/Data/ol_data.txt"
def extract_novels_from_massive_dump(input_file, output_file):
    # 1. BỘ LỌC TỪ KHÓA (Keyword Filter)
    # Bao gồm các thể loại tiểu thuyết phổ biến
    novel_keywords = {
        'fiction', 'novel', 'romance', 'fantasy', 'mystery', 
        'thriller', 'horror', 'science fiction', 'historical fiction', 
        'young adult', 'literary fiction'
    }
    
    # Loại trừ gắt gao các loại sách không phải tiểu thuyết (rất quan trọng để data sạch)
    exclude_keywords = {
        'non-fiction', 'nonfiction', 'biography', 'autobiography', 
        'history', 'textbook', 'manual', 'guide', 'dictionary', 
        'encyclopedia', 'comic', 'comics', 'manga', 'graphic novel', 
        'poetry', 'short stories', 'essay', 'academic'
    }

    # set to save
    unique_isbns = set()
    error_count = 0

    print("Bắt đầu quét file 59GB. Quá trình này có thể mất từ 30 phút đến 2 tiếng tùy tốc độ ổ SSD...")
    start_time = time.time()

    # Mở file đọc và file ghi
    with open(input_file, 'r', encoding='utf-8') as infile, \
        open(output_file, 'w', encoding='utf-8') as outfile:
        
        # tqdm giúp hiển thị tốc độ quét (lines/second)
        for line in tqdm(infile, desc="Đang quét"):
            try:
                # Cắt chuỗi bằng Tab. Dữ liệu JSON luôn nằm ở cột cuối cùng (index 4)
                parts = line.split('\t')
                if len(parts) < 5:
                    continue
                
                # Load JSON
                data = json.loads(parts[4])
                
                # Ưu tiên lấy ISBN-13 (tiêu chuẩn mới), nếu không có mới lấy ISBN-10
                isbns = data.get('isbn_13', [])
                if not isbns:
                    isbns = data.get('isbn_10', [])
                
                if not isbns:
                    continue # Bỏ qua nếu sách không có mã định danh
                
                subjects = data.get('subjects', [])
                if not subjects:
                    continue
                
                # Chuẩn hóa subject về chữ thường
                subjects_lower = [str(s).lower() for s in subjects]
                
                # 2. KIỂM TRA ĐIỀU KIỆN
                is_novel = False
                is_excluded = False
                
                # Kiểm tra xem có tag nào khớp với danh sách loại trừ không
                for sub in subjects_lower:
                    if any(ex_kw in sub for ex_kw in exclude_keywords):
                        is_excluded = True
                        break # Thoát vòng lặp ngay nếu phát hiện từ cấm
                
                if is_excluded:
                    continue # Bỏ qua sách này
                
                # Kiểm tra xem có tag nào khớp với danh sách tiểu thuyết không
                for sub in subjects_lower:
                    if any(nov_kw in sub for nov_kw in novel_keywords):
                        is_novel = True
                        break
                
                # 3. LƯU KẾT QUẢ
                if is_novel:
                    isbn = isbns[0].strip()
                    # Chỉ ghi vào file nếu ISBN này chưa từng xuất hiện
                    if isbn not in unique_isbns:
                        unique_isbns.add(isbn)
                        outfile.write(isbn + '\n')
                        
            except (json.JSONDecodeError, IndexError):
                error_count += 1
                continue

    end_time = time.time()
    mins = (end_time - start_time) / 60
    
    print("\n" + "="*50)
    print(f"🎉 HOÀN THÀNH!")
    print(f"⏱️ Thời gian quét: {mins:.2f} phút")
    print(f"📚 Tổng số mã ISBN tiểu thuyết lọc được (không trùng lặp): {len(unique_isbns):,}")
    print(f"⚠️ Số dòng lỗi/bỏ qua do sai định dạng: {error_count:,}")
    print("="*50)

# Chạy kịch bản
# LƯU Ý: Đổi 'ol_dump_editions.txt' thành đường dẫn tới file 59GB của bạn
extract_novels_from_massive_dump(data_path, 'clean_novel_isbns.txt')