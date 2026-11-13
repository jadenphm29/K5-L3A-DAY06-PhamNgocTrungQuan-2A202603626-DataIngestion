"""Read and normalize source data from PDF.

Corpus: Đừng bao giờ đi ăn một mình (dung-bao-gio-di-an-mot-minh.pdf)
Tác giả: Keith Ferrazzi
"""
import re
import unicodedata
from pathlib import Path
from pypdf import PdfReader
from .models import DocumentPage


def normalize_text(text: str) -> str:
    """Chuẩn hóa Unicode (NFC), loại bỏ ký tự NUL (0x00), watermark và khoảng trắng thừa."""
    if not text:
        return ""
    # 1. Loại bỏ NUL byte (\x00)
    text = text.replace("\x00", "").replace("\u0000", "")
    
    # 2. Loại bỏ watermark đầu trang ebook (Never Eat Alone Designed by Trung Pham Tuan...)
    text = re.sub(
        r"Never Eat Alone\s+Designed by Trung Pham Tuan\s+http://phamtuantrung\.tk\s*(- \d+ -)?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    
    # 3. Chuẩn hóa Unicode NFC
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\r\n|\r", "\n", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def load_pdf(
    path: Path | None = None,
    document_id: str = "dung-bao-gio-di-an-mot-minh",
    source: str = "data/dung-bao-gio-di-an-mot-minh.pdf",
    start_page: int = 1,
    end_page: int = 279,
    min_chars: int = 80,
) -> list[DocumentPage]:
    """Đọc full cuốn sách (279 trang), giữ số trang vật lý và ghi log trang rỗng."""
    if path is None:
        path = Path("data/dung-bao-gio-di-an-mot-minh.pdf")

    reader = PdfReader(str(path))
    total_pages = len(reader.pages)

    pages: list[DocumentPage] = []
    empty_pages_log: list[int] = []

    actual_start = max(1, start_page)
    actual_end = min(total_pages, end_page)

    for p_num in range(actual_start, actual_end + 1):
        raw_page = reader.pages[p_num - 1]
        raw_text = raw_page.extract_text() or ""
        clean_text = normalize_text(raw_text)

        if len(clean_text) < min_chars:
            empty_pages_log.append(p_num)
            continue

        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=p_num,
                text=clean_text,
                metadata={
                    "char_count": len(clean_text),
                },
            )
        )

    print(f"[Ingestion] Đã đọc {len(pages)} trang nội dung hữu ích từ sách '{document_id}' (từ trang {actual_start} đến {actual_end}).")
    if empty_pages_log:
        print(f"[Ingestion Log] Các trang bỏ qua (bìa/trắng/watermark): {len(empty_pages_log)} trang.")

    return pages
