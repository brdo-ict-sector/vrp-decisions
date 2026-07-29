"""
Convert raw decision files (.docx, .doc, .rtf) into Markdown.

- .docx is converted directly with Docling.
- .doc / .rtf are first converted to .docx with headless LibreOffice
  (Docling does not ingest legacy .doc / .rtf), then run through Docling.

Already-converted files are skipped, so a nightly run only touches the acts
stage 12 has just downloaded.

Usage:
    python 13_transform_raw_to_md.py                 # data/acts/raw → data/acts/md
    python 13_transform_raw_to_md.py <input> <output>
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docling.document_converter import DocumentConverter

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "data" / "acts" / "raw"
OUTPUT_DIR = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE_DIR / "data" / "acts" / "md"

SUPPORTED = {".docx", ".doc", ".rtf"}
LEGACY = {".doc", ".rtf"}  # need LibreOffice → .docx first


def libreoffice_to_docx(src: Path, dst_dir: Path) -> Path:
    """Convert a legacy .doc/.rtf to .docx using headless LibreOffice."""
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "docx", "--outdir", str(dst_dir), str(src)],
        check=True,
        capture_output=True,
    )
    out = dst_dir / f"{src.stem}.docx"
    if not out.exists():
        raise RuntimeError(f"LibreOffice did not produce {out}")
    return out


def run_ingestion():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    converter = DocumentConverter()

    files = sorted(f for f in INPUT_DIR.iterdir() if f.suffix.lower() in SUPPORTED)
    print(f"🚀 Converting {len(files)} files from {INPUT_DIR}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="raw2md_"))
    ok, skipped, failed = 0, 0, 0
    try:
        for i, f in enumerate(files, 1):
            output_file = OUTPUT_DIR / f"{f.stem}.md"
            if output_file.exists():
                skipped += 1
                continue

            print(f"[{i}/{len(files)}] {f.name} ...", flush=True)
            try:
                source = libreoffice_to_docx(f, tmp_dir) if f.suffix.lower() in LEGACY else f
                result = converter.convert(source)
                output_file.write_text(result.document.export_to_markdown(), encoding="utf-8")
                ok += 1
            except Exception as e:
                failed += 1
                print(f"   ❌ {f.name}: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n✅ Done. {ok} converted, {skipped} already present, {failed} failed → {OUTPUT_DIR}")


if __name__ == "__main__":
    run_ingestion()
