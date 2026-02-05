#!/usr/bin/env python3
"""Split the Epstein files CSV into individual text files for indexing."""

import csv
import sys
from pathlib import Path

def split_csv(
    input_path: str = "/Users/davidmontgomery/epstein-files/EPS_FILES_20K_NOV2025.txt",
    output_dir: str = "/Users/davidmontgomery/epstein-files/documents",
):
    """Split CSV with filename,text columns into individual files."""
    
    input_file = Path(input_path)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    # Handle large fields
    csv.field_size_limit(sys.maxsize)
    
    count = 0
    skipped = 0
    
    with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            filename = (row.get("filename") or "").strip()
            text = (row.get("text") or "").strip()
            
            if not filename or not text:
                skipped += 1
                continue
            
            # Sanitize filename
            safe_name = filename.replace("/", "_").replace("\\", "_")
            if not safe_name.endswith(".txt"):
                safe_name = safe_name + ".txt" if not safe_name.endswith(".txt") else safe_name
            
            # Write file
            out_file = out_path / safe_name
            out_file.write_text(text, encoding="utf-8")
            
            count += 1
            if count % 1000 == 0:
                print(f"Processed {count} files...")
    
    print(f"✓ Wrote {count} files to {out_path}")
    print(f"  Skipped {skipped} empty rows")

if __name__ == "__main__":
    split_csv()
