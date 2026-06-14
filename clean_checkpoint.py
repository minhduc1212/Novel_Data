import json
import os
import re

def main():
    log_file = "goodreads_scraper.log"
    checkpoint_file = "goodreads_checkpoint.json"
    
    if not os.path.exists(log_file):
        print(f"Log file {log_file} not found.")
        return
        
    if not os.path.exists(checkpoint_file):
        print(f"Checkpoint file {checkpoint_file} not found.")
        return

    # Pattern to match: Book '403 Forbidden' for ISBN 9780547531021 ...
    # or any message indicating 403 Forbidden for a specific ISBN
    pattern = re.compile(r"Book '403 Forbidden' for ISBN (\d+)")
    
    blocked_isbns = set()
    
    print("Reading log file to find blocked ISBNs...")
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                blocked_isbns.add(match.group(1))
                
    if not blocked_isbns:
        print("No blocked ISBNs (403 Forbidden) found in log file.")
        # Fallback check: find any line containing '403 Forbidden' and 'ISBN'
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if "403 Forbidden" in line:
                    isbn_match = re.search(r"ISBN:?\s*(\d+)", line)
                    if isbn_match:
                        blocked_isbns.add(isbn_match.group(1))
                    else:
                        # try matches like: for ISBN 9781250109545
                        isbn_match2 = re.search(r"ISBN\s+(\d+)", line)
                        if isbn_match2:
                            blocked_isbns.add(isbn_match2.group(1))
                            
    print(f"Found {len(blocked_isbns)} unique ISBNs that were blocked by 403 Forbidden.")
    
    if not blocked_isbns:
        print("Nothing to clean.")
        return

    # Load checkpoint
    with open(checkpoint_file, 'r', encoding='utf-8') as f:
        checkpoint = json.load(f)
        
    failed_isbns = checkpoint.get("failed_isbns", [])
    original_failed_count = len(failed_isbns)
    
    # Remove blocked ISBNs
    cleaned_failed_isbns = [isbn for isbn in failed_isbns if isbn not in blocked_isbns]
    removed_count = original_failed_count - len(cleaned_failed_isbns)
    
    checkpoint["failed_isbns"] = cleaned_failed_isbns
    
    # Save checkpoint
    with open(checkpoint_file, 'w', encoding='utf-8') as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=4)
        
    print(f"Successfully cleaned checkpoint file:")
    print(f"  - Original failed ISBNs count: {original_failed_count}")
    print(f"  - Restored ISBNs count: {removed_count}")
    print(f"  - New failed ISBNs count: {len(cleaned_failed_isbns)}")

if __name__ == "__main__":
    main()
