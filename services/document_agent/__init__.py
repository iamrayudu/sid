"""Document agent — watches a folder, extracts content from PDF/text/markdown,
and feeds it through the same memory pipeline as voice chunks.

Auto-watch: ~/Documents/SID/ (or $SID_DOCS_DIR)
Supported: .pdf (PyMuPDF), .txt, .md, .markdown
Each file → one or more RawChunks → processing queue → memory
"""
from services.document_agent.watcher import DocumentWatcher, get_doc_watcher

__all__ = ["DocumentWatcher", "get_doc_watcher"]
