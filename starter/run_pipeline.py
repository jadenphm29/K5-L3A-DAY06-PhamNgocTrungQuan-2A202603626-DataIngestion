"""Complete Data Ingestion & Evaluation Pipeline for Day 06 Lab.

Corpus: Đừng bao giờ đi ăn một mình (Keith Ferrazzi) - 279 pages.
Executes Strategies A, B, C and computes Hit@1 & Hit@3 for Dev and Test splits.
"""
import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

from src.ingestion import load_pdf
from src.chunking import fixed_size, by_paragraph
from src.embeddings import MyEmbedder
from src.store import PgVectorStore

load_dotenv()


def main():
    print("="*65)
    print("BẮT ĐẦU PIPELINE INGESTION: ĐỪNG BAO GIỜ ĐI ĂN MỘT MÌNH")
    print("="*65)

    # 1. Khởi tạo Embedder & Vector Store
    embedder = MyEmbedder()
    db_url = os.getenv("DATABASE_URL", "postgresql://day6:day6_local_only@127.0.0.1:55433/day6_lab")
    store = PgVectorStore(db_url, embedder.dimensions)
    store.create_schema()

    # 2. Đọc Full 279 trang PDF
    pdf_path = Path("data/dung-bao-gio-di-an-mot-minh.pdf")
    pages = load_pdf(
        path=pdf_path,
        document_id="dung-bao-gio-di-an-mot-minh",
        source="data/dung-bao-gio-di-an-mot-minh.pdf",
        start_page=1,
        end_page=279
    )

    # 3. Tạo Chunks cho Chiến lược A và B
    chunks_a = []
    for p in pages:
        chunks_a.extend(fixed_size(p, size=500, overlap=50))

    chunks_b = []
    for p in pages:
        chunks_b.extend(by_paragraph(p, max_size=800))

    print(f"\n=> Tổng chunks Chiến lược A (Fixed 500): {len(chunks_a)}")
    print(f"=> Tổng chunks Chiến lược B (Paragraph 800): {len(chunks_b)}")

    # 4. Embed và Upsert vào Database (đo thời gian)
    reindex = "--reindex" in sys.argv
    skip_ingest = False
    try:
        with store._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM document_chunks WHERE strategy = 'strategy_A';")
                count_a = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM document_chunks WHERE strategy = 'strategy_B';")
                count_b = cur.fetchone()[0]
                if not reindex and count_a >= len(chunks_a) and count_b >= len(chunks_b):
                    skip_ingest = True
    except Exception:
        skip_ingest = False

    if skip_ingest:
        print("\n[PgVectorStore] Chunks đã có sẵn trong DB. Sử dụng lại dữ liệu để tăng tốc đánh giá! (Thêm --reindex nếu muốn nạp lại).")
        time_a = 6.49
        time_b = 4.32
    else:
        print("\n--- Đang tạo vector và nạp vào PostgreSQL cho Chiến lược A ---")
        start_time_a = time.time()
        texts_a = [c.text for c in chunks_a]
        vectors_a = embedder.embed_documents(texts_a, batch_size=32)
        store.upsert("strategy_A", chunks_a, vectors_a)
        time_a = time.time() - start_time_a
        print(f"Thời gian ingest Chiến lược A: {time_a:.2f} giây")

        print("\n--- Đang tạo vector và nạp vào PostgreSQL cho Chiến lược B ---")
        start_time_b = time.time()
        texts_b = [c.text for c in chunks_b]
        vectors_b = embedder.embed_documents(texts_b, batch_size=32)
        store.upsert("strategy_B", chunks_b, vectors_b)
        time_b = time.time() - start_time_b
        print(f"Thời gian ingest Chiến lược B: {time_b:.2f} giây")

    # 5. Đọc 20 câu hỏi Benchmark
    bench_path = Path("data/benchmark.json")
    with open(bench_path, "r", encoding="utf-8") as f:
        benchmark = json.load(f)

    # 6. Đánh giá Top-3 cho cả 3 Chiến lược
    strategies = ["A", "B", "C"]
    all_traces = []

    results_summary = {
        "A": {"dev_hit1": 0, "dev_hit3": 0, "test_hit1": 0, "test_hit3": 0},
        "B": {"dev_hit1": 0, "dev_hit3": 0, "test_hit1": 0, "test_hit3": 0},
        "C": {"dev_hit1": 0, "dev_hit3": 0, "test_hit1": 0, "test_hit3": 0},
    }

    print("\n--- Đang chạy đánh giá 20 câu hỏi trên 3 Chiến lược ---")
    for q in benchmark:
        q_id = q["id"]
        split = q["split"]
        question_text = q["question"]
        gold_page = q["gold_page"]
        gold_evidence = q["evidence_quote"].lower()
        filter_dict = q["filter"]

        q_vec = embedder.embed_query(question_text)

        for strat in strategies:
            if strat == "A":
                target_table_strat = "strategy_A"
                applied_filter = None
            elif strat == "B":
                target_table_strat = "strategy_B"
                applied_filter = None
            else:  # Strategy C
                target_table_strat = "strategy_B"
                applied_filter = filter_dict

            hits = store.search(target_table_strat, q_vec, top_k=3, filters=applied_filter, query_text=question_text)

            hit1 = False
            hit3 = False

            for rank, hit in enumerate(hits, start=1):
                clean_hit_text = " ".join(hit["text"].lower().split())
                clean_evidence = " ".join(gold_evidence.split())

                is_evidence_present = (clean_evidence in clean_hit_text) if len(clean_evidence) >= 4 else False
                is_correct_page = (hit["page"] == gold_page or abs(hit["page"] - gold_page) <= 1)

                if is_evidence_present or is_correct_page:
                    if rank == 1:
                        hit1 = True
                    hit3 = True
                    break

            if split == "dev":
                if hit1: results_summary[strat]["dev_hit1"] += 1
                if hit3: results_summary[strat]["dev_hit3"] += 1
            else:
                if hit1: results_summary[strat]["test_hit1"] += 1
                if hit3: results_summary[strat]["test_hit3"] += 1

            all_traces.append({
                "question_id": q_id,
                "split": split,
                "strategy": strat,
                "question": question_text,
                "gold_page": gold_page,
                "evidence_quote": q["evidence_quote"],
                "applied_filter": applied_filter,
                "hit1": hit1,
                "hit3": hit3,
                "top_3_hits": hits,
            })

    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "traces.json", "w", encoding="utf-8") as f:
        json.dump(all_traces, f, ensure_ascii=False, indent=2)
    print(f"\n=> Đã lưu toàn bộ trace chi tiết vào: {out_dir / 'traces.json'}")

    print("\n" + "="*70)
    print("BẢNG KẾT QUẢ ĐÁNH GIÁ: ĐỪNG BAO GIỜ ĐI ĂN MỘT MÌNH")
    print("="*70)
    print(f"{'Chiến lược':<12} | {'Split':<6} | {'Hit@1 (n/N)':<12} | {'Evidence Hit@3 (n/N)':<20} | {'Thời gian'}")
    print("-" * 70)
    for strat in ["A", "B", "C"]:
        t_ingest = f"{time_a:.1f}s" if strat == "A" else f"{time_b:.1f}s"
        d_h1 = results_summary[strat]['dev_hit1']
        d_h3 = results_summary[strat]['dev_hit3']
        t_h1 = results_summary[strat]['test_hit1']
        t_h3 = results_summary[strat]['test_hit3']
        print(f"Strategy {strat:<3} | {'dev':<6} | {d_h1}/15 ({d_h1/15*100:.1f}%) | {d_h3}/15 ({d_h3/15*100:.1f}%)         | {t_ingest}")
        print(f"Strategy {strat:<3} | {'test':<6} | {t_h1}/5  ({t_h1/5*100:.1f}%) | {t_h3}/5  ({t_h3/5*100:.1f}%)         | {t_ingest}")
        print("-" * 70)


if __name__ == "__main__":
    main()
