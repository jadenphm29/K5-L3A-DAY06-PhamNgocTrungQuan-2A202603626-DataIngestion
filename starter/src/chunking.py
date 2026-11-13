"""Implement fixed-size and structure-aware (paragraph) chunking.

Corpus: Đừng bao giờ đi ăn một mình (Keith Ferrazzi).
"""
import re
from .models import Chunk, DocumentPage


def _get_page_category(page_num: int) -> str:
    """Phân loại metadata theo 4 phần chính của cuốn sách."""
    if page_num <= 75:
        return "phan_1_tam_the"
    elif page_num <= 155:
        return "phan_2_ky_nang"
    elif page_num <= 225:
        return "phan_3_ket_noi"
    else:
        return "phan_4_ky_thuat_so"


def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Chiến lược A: Chia chunk kích thước cố định với cửa sổ trượt."""
    text = page.text.strip()
    if not text:
        return []

    chunks: list[Chunk] = []
    step = max(1, size - overlap)
    cat = _get_page_category(page.page)

    for idx, start in enumerate(range(0, len(text), step)):
        chunk_text = text[start : start + size].strip()
        if len(chunk_text) < 40:
            continue

        chunk_id = f"{page.document_id}_p{page.page}_fix_{idx:02d}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=page.document_id,
                source=page.source,
                page=page.page,
                text=chunk_text,
                metadata={
                    "strategy": "A_fixed",
                    "category": cat,
                    "char_count": len(chunk_text),
                },
            )
        )
    return chunks


def by_paragraph(page: DocumentPage, max_size: int = 800) -> list[Chunk]:
    """Chiến lược B & C: Chia chunk theo ranh giới đoạn văn (Paragraph)."""
    text = page.text.strip()
    if not text:
        return []

    raw_paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[Chunk] = []
    current_para: list[str] = []
    current_len = 0
    idx = 0
    cat = _get_page_category(page.page)

    def _flush(paras: list[str]) -> None:
        nonlocal idx
        merged_text = "\n\n".join(paras).strip()
        if len(merged_text) >= 40:
            chunk_id = f"{page.document_id}_p{page.page}_para_{idx:02d}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    document_id=page.document_id,
                    source=page.source,
                    page=page.page,
                    text=merged_text,
                    metadata={
                        "strategy": "B_paragraph",
                        "category": cat,
                        "char_count": len(merged_text),
                    },
                )
            )
            idx += 1

    for para in raw_paras:
        para_len = len(para)
        if para_len > max_size:
            if current_para:
                _flush(current_para)
                current_para = []
                current_len = 0

            sentences = re.split(r"(?<=[.!?])\s+", para)
            temp_group: list[str] = []
            temp_len = 0
            for sent in sentences:
                if temp_len + len(sent) > max_size and temp_group:
                    _flush(temp_group)
                    temp_group = [sent]
                    temp_len = len(sent)
                else:
                    temp_group.append(sent)
                    temp_len += len(sent)
            if temp_group:
                _flush(temp_group)
        elif current_len + para_len > max_size:
            _flush(current_para)
            current_para = [para]
            current_len = para_len
        else:
            current_para.append(para)
            current_len += para_len

    if current_para:
        _flush(current_para)

    return chunks
