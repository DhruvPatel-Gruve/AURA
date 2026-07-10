"""Convert a single document file to Markdown using markitdown.

Supports: PDF, DOCX, PPTX, XLSX, HTML, TXT, MD, CSV, JSON.
All formats are normalised to plain Markdown before chunking so the
DynamicChunker can apply consistent header-aware splitting.

Only the extensions in ALLOWED_EXTENSIONS are accepted. markitdown also
ships converters for archives (.zip — silently unpacks and converts every
file inside), images, audio, epub, etc. Those are intentionally excluded
here: uploading a single knowledge-base document should never fan out into
an unbounded number of unrelated chunks.
"""

import tempfile
from pathlib import Path

from charset_normalizer import from_bytes
from markitdown import MarkItDown, StreamInfo

from app.core.logging import get_logger

log = get_logger(__name__)

_converter = MarkItDown()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".html", ".htm", ".csv", ".json"}

# Extensions whose markitdown converters decode text using stream_info.charset.
# markitdown itself only samples the first 4KB to guess that charset (via magika),
# so a non-ASCII byte later in the file can be missed, producing a strict
# UnicodeDecodeError instead of a correct decode. We re-detect from the full
# file content and pass it in explicitly to avoid that.
_TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".csv", ".json"}


def convert_to_markdown(file_bytes: bytes, filename: str) -> str:
    """Convert raw file bytes to a Markdown string.

    Writes to a temp file (markitdown requires a path), converts, then cleans up.
    Raises ValueError if the extension is not in ALLOWED_EXTENSIONS, the file
    looks like a directory upload (no filename/extension), or markitdown
    returns empty content.
    """
    suffix = Path(filename).suffix.lower()

    if not suffix or suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(
            f"Unsupported file type '{suffix or '(none)'}' for '{filename}'. "
            f"Allowed: {allowed}"
        )

    stream_info = None
    if suffix in _TEXT_EXTENSIONS:
        detected = from_bytes(file_bytes).best()
        if detected is not None:
            stream_info = StreamInfo(charset=str(detected.encoding))

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        result = _converter.convert(tmp_path, stream_info=stream_info)
        markdown = result.text_content or ""
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not markdown.strip():
        raise ValueError(f"markitdown returned no content for '{filename}'")

    log.debug("document_converter.converted", filename=filename, chars=len(markdown))
    return markdown
