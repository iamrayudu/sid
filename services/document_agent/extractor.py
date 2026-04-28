"""Extract text content from PDF, plain text, and markdown files."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

logger = logging.getLogger("sid.document_agent.extractor")

# Max chars per chunk to avoid token overflow in the LLM pipeline
_CHUNK_SIZE = 3000
_CHUNK_OVERLAP = 200


def extract_text(path: Path) -> List[str]:
    """
    Extract text from a file. Returns a list of text chunks.
    Each chunk is sized for the LLM pipeline (~3000 chars).
    Returns [] if the file can't be read or is empty.
    """
    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            return _extract_pdf(path)
        elif suffix in (".txt", ".md", ".markdown"):
            return _extract_text_file(path)
        else:
            logger.debug("Unsupported file type: %s", suffix)
            return []
    except Exception as e:
        logger.error("Failed to extract %s: %s", path.name, e)
        return []


def _extract_pdf(path: Path) -> List[str]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF not installed — PDF extraction disabled. Run: pip install pymupdf")
        return []

    doc = fitz.open(str(path))
    pages = []
    for page in doc:
        text = page.get_text("text").strip()
        if text:
            pages.append(text)
    doc.close()

    full_text = "\n\n".join(pages)
    return _chunk_text(full_text)


def _extract_text_file(path: Path) -> List[str]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    # Strip markdown headers/formatting for cleaner embedding
    text = re.sub(r"#+\s+", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    return _chunk_text(text)


def _chunk_text(text: str) -> List[str]:
    if not text:
        return []

    # Split on paragraph boundaries first
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= _CHUNK_SIZE:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            # Para itself might exceed chunk size — hard split
            if len(para) > _CHUNK_SIZE:
                for i in range(0, len(para), _CHUNK_SIZE - _CHUNK_OVERLAP):
                    chunks.append(para[i:i + _CHUNK_SIZE])
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks
