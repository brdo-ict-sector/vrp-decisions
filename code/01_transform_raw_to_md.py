import os
from pathlib import Path
from docling.document_converter import DocumentConverter

# Configuration
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "data" / "markdown"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run_ingestion():
    # Modern Docling only lists .docx as an allowed Word format by default
    converter = DocumentConverter()
    
    # We only target .docx (and .pdf if you have them)
    files = list(INPUT_DIR.glob("*.docx"))
    
    print(f"🚀 Starting conversion of {len(files)} .docx files...")
    
    for i, f in enumerate(files, 1):
        # Determine output path
        output_file = OUTPUT_DIR / f"{f.stem}.md"
        
        # Skip if already processed to save time
        if output_file.exists():
            continue

        print(f"[{i}/{len(files)}] Processing: {f.name}...", end="\r")
        try:
            result = converter.convert(f)
            md_content = result.document.export_to_markdown()
            
            with open(output_file, "w", encoding="utf-8") as out:
                out.write(md_content)
                
        except Exception as e:
            print(f"\n❌ Error on {f.name}: {e}")
            
    print(f"\n\n✅ Done! Markdown files are in: {OUTPUT_DIR}")

if __name__ == "__main__":
    run_ingestion()
