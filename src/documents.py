"""Read supported documents into bounded passages with page/block references."""
import re
from zipfile import ZipFile

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}
MAX_CHUNKS = 1000


class DocumentError(ValueError):
    pass


def split_passage(text):
    """Bounded overlapping windows, preferring sentence and word boundaries."""
    start = 0
    while start < len(text):
        end = min(start + 1000, len(text))
        if end < len(text):
            boundaries = [m.end() for m in re.finditer(r"[.!?](?:\s|$)", text[start:end])]
            boundary = boundaries[-1] if boundaries else 0
            if boundary >= 600:
                end = start + boundary
            else:
                space = text.rfind(" ", start + 600, end)
                if space != -1:
                    end = space
        yield text[start:end].strip()
        if end == len(text):
            break
        next_start = max(start + 1, end - 150)
        # Move forward to a word boundary without losing any text coverage.
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 else next_start


def extract(path):
    """Yield text and stable human-readable locations, without rendering uploads."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise DocumentError("Supported file types: PDF, DOCX, TXT and MD.")
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise DocumentError("Password-protected PDFs are not supported.")
            if len(reader.pages) > 500:
                raise DocumentError("PDFs are limited to 500 pages.")
            sections = [(f"Page {i}", page.extract_text() or "")
                        for i, page in enumerate(reader.pages, 1)]
        elif suffix == ".docx":
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            with ZipFile(path) as archive:
                if sum(info.file_size for info in archive.infolist()) > 50 * 1024 * 1024:
                    raise DocumentError("The expanded DOCX exceeds 50 MiB.")
            doc = Document(path)
            sections = []
            for i, block in enumerate(doc.iter_inner_content(), 1):
                text = block.text if isinstance(block, Paragraph) else "\n".join(
                    " | ".join(cell.text for cell in row.cells) for row in block.rows)
                sections.append((f"Block {i}", text))
        else:
            text = path.read_text(encoding="utf-8-sig")
            if "\x00" in text:
                raise DocumentError("Text files must contain UTF-8 text, not binary data.")
            sections = [(f"Paragraph {i}", part) for i, part in
                        enumerate(re.split(r"\n\s*\n", text), 1)]
    except DocumentError:
        raise
    except Exception as error:
        raise DocumentError("Cannot read this document. Use a valid PDF, DOCX or UTF-8 text file.") from error
    if sum(len(text) for _, text in sections) > 2_000_000:
        raise DocumentError("Extracted text exceeds two million characters. Split the document.")
    chunks = []
    for location, text in sections:
        text = " ".join(text.split())
        # Small overlapping chunks keep embeddings below the model context limit.
        for chunk in split_passage(text):
            if chunk.strip():
                chunks.append({"location": location, "text": chunk})
    if not chunks:
        raise DocumentError("No readable text found. Scanned PDFs need OCR before upload.")
    if len(chunks) > MAX_CHUNKS:
        raise DocumentError("Document has too many passages. Split it into smaller documents.")
    return chunks


