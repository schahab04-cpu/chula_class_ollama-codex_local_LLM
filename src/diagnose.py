"""Read-only extraction/index audit; optional live retrieval and evidence probe."""
import argparse
import hashlib
import json
import logging
import math
import sqlite3
from pathlib import Path

from .rag import KnowledgeBase, SUPPORTED, answer, extract, normalized, terms


def audit(folder):
    folder = Path(folder)
    index = folder / "knowledge.sqlite3"
    rows = {}
    if index.exists():
        db = sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = {row[0]: row for row in db.execute("SELECT id, fingerprint, model, chunks FROM documents")}
        finally:
            db.close()
    reports = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.is_symlink() or "--" not in path.name or path.suffix.lower() not in SUPPORTED:
            continue
        report = {"file": path.name, "warnings": []}
        reports.append(report)
        try:
            chunks = extract(path)
            report.update(extracted_characters=sum(len(c["text"]) for c in chunks),
                          extracted_chunks=len(chunks), locations=list(dict.fromkeys(c["location"] for c in chunks)))
            if path.suffix.lower() == ".pdf":
                from pypdf import PdfReader
                reader = PdfReader(path)
                counts = [len((page.extract_text() or "").strip()) for page in reader.pages]
                report["pdf_page_characters"] = counts
                report["pdf_pages_with_images"] = [i for i, page in enumerate(reader.pages, 1) if len(page.images)]
                if any(count < 50 for count in counts):
                    report["warnings"].append("Some pages contain little or no extractable text; inspect the PDF visually.")
                if report["pdf_pages_with_images"]:
                    report["warnings"].append("Images are not indexed. Diagram text may require OCR; text extraction cannot establish completeness.")
            row = rows.get(path.name)
            report["indexed"] = row is not None
            if not row:
                continue
            stored = json.loads(row[3])
            for chunk in stored:
                normalized(chunk["vector"])
            report.update(model=row[2], fingerprint_matches=row[1] == hashlib.sha256(path.read_bytes()).hexdigest(),
                          stored_chunks=len(stored), vector_dimensions=sorted({len(c["vector"]) for c in stored}),
                          vector_norms=[round(math.sqrt(sum(v*v for v in c["vector"])), 6) for c in stored],
                          extraction_matches_index=[{k:c[k] for k in ("location", "text")} for c in stored] == chunks)
        except (ValueError, OSError, KeyError, TypeError) as error:
            report["error"] = str(error)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", help="Run a live query using the existing index; does not reindex documents.")
    parser.add_argument("--answer", action="store_true", help="Also run Gemma quote selection (requires --question).")
    args = parser.parse_args()
    if args.answer and not args.question:
        parser.error("--answer requires --question")
    logging.basicConfig(level=logging.INFO)
    folder = Path(__file__).resolve().parent.parent / "uploads"
    report = {"documents": audit(folder)}
    if args.question:
        if not (folder / "knowledge.sqlite3").exists():
            parser.error("No index exists. Index documents in Filemanager first.")
        sources = KnowledgeBase(folder).retrieve(args.question)
        report["retrieval"] = [{**source, "missing_question_terms": sorted(terms(args.question) - terms(source["text"]))}
                               for source in sources]
        if args.answer:
            report["answer"], report["citations"] = answer(args.question, sources, "gemma3:1b")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
