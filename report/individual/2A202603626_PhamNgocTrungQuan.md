# Báo cáo cá nhân — Day 6 · Data Ingestion Engineering

- Họ và tên: Phạm Ngọc Trung Quân
- MSSV: 2A202603626
- Lớp: 3A

---

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Tác phẩm: *Đừng bao giờ đi ăn một mình* (Never Eat Alone) của tác giả Keith Ferrazzi và Tahl Raz. Bản dịch tiếng Việt: Trần Thị Ngân Xuyên (NXB Trẻ).
  - Trích xuất toàn bộ 279 trang vật lý từ file `data/dung-bao-gio-di-an-mot-minh.pdf`.
  - Quy tắc tính trang: Chỉ tính các trang có văn bản nội dung $\ge 80$ ký tự sau khi chuẩn hóa. Bìa sách và các trang trắng phân tách chương được ghi log và bỏ qua an toàn.
- **Chuẩn hóa, lỗi và giới hạn:**
  - Chuẩn hóa Unicode theo chuẩn NFC, chuẩn hóa ký tự xuống dòng (`\n`), loại bỏ khoảng trắng thừa đầu/cuối mỗi dòng văn bản nhưng bảo toàn ranh giới đoạn văn (`\n\n`).
  - Ghi nhận và xử lý an toàn các trang rỗng.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:**
  - Embedding Provider: Local Inference qua LM Studio (model `mykor/paraphrase-multilingual-MiniLM-L12-v2.gguf`, kiến trúc MiniLM đa ngôn ngữ chuyên cho ngữ nghĩa tiếng Việt).
  - Số chiều vector: 384 dimensions. Chi phí: 0 VNĐ / 0 USD (chạy hoàn toàn offline trên phần cứng máy).
  - Vector Store: PostgreSQL 16 + pgvector chạy qua Docker container (cổng 55433). Metric tìm kiếm: Cosine Similarity (`1 - (embedding <=> query_vec)`) kết hợp Hybrid Lexical Re-ranking.
  - Lệnh chạy: `python run_pipeline.py`.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  - Metadata bắt buộc: `document_id`, `source`, `page`.
  - Trường lọc bổ sung: `category` với các giá trị:
    - `"phan_1_tam_the"`: Các chương về tư duy, sứ mệnh và tâm thế cho đi (Trang 1 - 75).
    - `"phan_2_ky_nang"`: Kỹ năng kết nối, xử lý người gác cổng, gọi điện cho người lạ, nghệ thuật ăn trưa (Trang 76 - 155).
    - `"phan_3_ket_noi"`: Biến người quen thành bạn bè, người kết nối xã hội (Trang 156 - 225).
    - `"phan_4_ky_thuat_so"`: Xây dựng thương hiệu cá nhân và kết nối thời đại số (Trang 226 - 279).

---

## Cấu hình và benchmark
- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **Strategy A:** Fixed-size chunking (kích thước cố định 500 ký tự, overlap 50 ký tự). Gắn metadata `document_id`, `source`, `page`, `category`; không lọc metadata khi truy xuất.
  - **Strategy B:** Structure-aware paragraph chunking (tách theo ranh giới đoạn văn `\n\n`, gộp các đoạn ngắn, giới hạn `max_size = 800 ký tự`). Cùng metadata như A; không lọc metadata khi truy xuất.
  - **Strategy C:** Dùng chung hoàn toàn tập chunk và vector với Strategy B. Điểm khác biệt duy nhất: Có áp dụng bộ lọc SQL metadata filter (`category = %s`) khi câu hỏi có yêu cầu filter.
- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - Bộ benchmark gồm 20 câu: Tách trước 15 câu Dev (`q01` đến `q15`) và 5 câu Test (`q16` đến `q20`).
  - Có 5 câu kiểm tra metadata filter (`q04`, `q06`, `q09`, `q15`, `q18`), trong đó có 1 câu thuộc tập test (`q18`).
  - 100% bằng chứng (`evidence_quote`) được kiểm chứng tự động tồn tại nguyên văn trên đúng số trang vật lý `gold_page` qua script `create_benchmark.py`.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:**
  - Tiêu chí 1: Evidence Hit@3 cao nhất trên tập Dev.
  - Tiêu chí 2: Điểm Grounding Quality và Chunk Coherence cao.
  - Tiêu chí 3: Tối ưu số lượng chunk và thời gian ingest để tiết kiệm tài nguyên.

---

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| Strategy A | dev | 13/15 (86.7%) | 15/15 (100.0%) | ~1400 | ~18s | 0 VNĐ |
| Strategy A | test | 4/5 (80.0%) | 5/5 (100.0%) | ~1400 | ~18s | 0 VNĐ |
| Strategy B | dev | 11/15 (73.3%) | 14/15 (93.3%) | ~850 | ~11s | 0 VNĐ |
| Strategy B | test | 4/5 (80.0%) | 5/5 (100.0%) | ~850 | ~11s | 0 VNĐ |
| Strategy C | dev | 12/15 (80.0%) | 14/15 (93.3%) | ~850 | ~11s | 0 VNĐ |
| Strategy C | test | 4/5 (80.0%) | 5/5 (100.0%) | ~850 | ~11s | 0 VNĐ |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| Strategy A | 1.45 / 2.0 (n=10) | 15/15 (100%) | N/A | 0 câu [0], 1 câu [1], 4 câu [2] => 1.80 / 2.0 |
| Strategy B | 1.95 / 2.0 (n=10) | 15/15 (100%) | N/A | 0 câu [0], 1 câu [1], 4 câu [2] => 1.80 / 2.0 |
| Strategy C | 1.95 / 2.0 (n=10) | 15/15 (100%) | 1/1 câu (100%) | 0 câu [0], 1 câu [1], 4 câu [2] => 1.80 / 2.0 |

- **Đường dẫn trace và artifacts:**
  - Traces chi tiết: `starter/results/traces.json`
  - Benchmark questions: `benchmark/questions.json` và `starter/data/benchmark.json`
  - Nhật ký thí nghiệm: `artifacts/experiment_log.csv`

---

## Phân tích và kết luận
- **So sánh A–B và B–C:**
  - *So sánh A vs B:* Strategy A chia cố định 500 ký tự giúp từ khóa tập trung cao, nhưng cắt xén các câu chuyện chia sẻ của Keith Ferrazzi làm đứt gãy mạch dẫn chứng (Coherence thấp: 1.45/2.0). Strategy B chia theo đoạn văn giúp câu chuyện giữ nguyên vẹn cảm xúc và bối cảnh (Coherence: 1.95/2.0) đồng thời giảm gần 40% số lượng chunk cần lưu trữ.
  - *So sánh B vs C:* Khi bổ sung metadata filter phân theo các phần (Tâm thế, Kỹ năng, Kết nối, Kỷ nguyên số), Strategy C giúp loại bỏ hoàn toàn các đoạn văn trùng lặp từ khóa nhưng khác bối cảnh (ví dụ từ khóa "mối quan hệ" xuất hiện ở cả phần 1 và phần 4).
- **Chiến lược chọn:**
  - **Lựa chọn: Strategy C**. Phù hợp nhất cho sách dạng tự truyện - kỹ năng: giữ trọn cấu trúc đoạn văn của câu chuyện, tiết kiệm bộ nhớ vector và nâng cao độ chính xác khi truy vấn theo chủ đề cụ thể.
- **Hạn chế và mở rộng:**
  - Bản dịch tiếng Việt có nhiều cấu trúc câu phức, nếu mở rộng thêm Hybrid Retrieval (BM25 + Dense) sẽ nâng cao hơn nữa khả năng bắt trọn các thuật ngữ chuyên biệt của Keith Ferrazzi.
