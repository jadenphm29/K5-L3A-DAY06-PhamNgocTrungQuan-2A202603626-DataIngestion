"""Store and search vectors using PostgreSQL + pgvector."""
import json
import re
from typing import Any
import psycopg
from pgvector.psycopg import register_vector
from .models import Chunk


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        self.database_url = database_url
        self.dimensions = dimensions

    def _get_connection(self):
        conn = psycopg.connect(self.database_url)
        register_vector(conn)
        return conn

    def create_schema(self) -> None:
        """Tạo bảng lưu chunks và vector. Tự động làm mới bảng nếu đổi model/số chiều vector."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

                # Kiểm tra xem bảng document_chunks đã tồn tại chưa
                cur.execute("""
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'document_chunks';
                """)
                table_exists = cur.fetchone() is not None

                if table_exists:
                    # Kiểm tra số chiều của cột embedding hiện tại trong Postgres
                    cur.execute("""
                        SELECT atttypmod 
                        FROM pg_attribute 
                        WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding';
                    """)
                    row = cur.fetchone()
                    if row and row[0] != self.dimensions:
                        print(f"[PgVectorStore] Phát hiện đổi Model/Số chiều ({row[0]} -> {self.dimensions}). Đang làm mới bảng...")
                        cur.execute("DROP TABLE document_chunks CASCADE;")

                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS document_chunks (
                        id VARCHAR(255) PRIMARY KEY,
                        strategy VARCHAR(50) NOT NULL,
                        document_id VARCHAR(255) NOT NULL,
                        source VARCHAR(500) NOT NULL,
                        page INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        metadata JSONB NOT NULL,
                        embedding vector({self.dimensions}) NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_chunks_strategy ON document_chunks(strategy);
                    CREATE INDEX IF NOT EXISTS idx_chunks_metadata ON document_chunks USING gin (metadata);
                """)
            conn.commit()
        print(f"[PgVectorStore] Đã khởi tạo schema với số chiều vector = {self.dimensions}.")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Lưu chunks và vector. Dùng ON CONFLICT để đảm bảo nạp lại không bị trùng lặp."""
        if len(chunks) != len(vectors):
            raise ValueError("Số lượng chunk và vector không khớp nhau!")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                for chunk, vector in zip(chunks, vectors):
                    # Làm sạch triệt để ký tự NUL (\x00) trước khi đẩy vào PostgreSQL
                    clean_text = chunk.text.replace("\x00", "").replace("\u0000", "")
                    clean_id = chunk.chunk_id.replace("\x00", "").replace("\u0000", "")
                    meta_json = json.dumps(chunk.metadata)

                    cur.execute("""
                        INSERT INTO document_chunks (id, strategy, document_id, source, page, text, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            text = EXCLUDED.text,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding;
                    """, (clean_id, strategy, chunk.document_id, chunk.source, chunk.page, clean_text, meta_json, vector))
            conn.commit()
        print(f"[PgVectorStore] Đã nạp thành công {len(chunks)} chunks cho Chiến lược {strategy}.")

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
        query_text: str | None = None,
    ) -> list[dict[str, Any]]:
        """Tìm kiếm Top-K chunk kết hợp Dense Vector (Cosine Distance) và Hybrid Lexical Re-ranking."""
        # Nếu có query_text, lấy top 30 ứng viên có vector gần nhất để re-rank theo từ khóa
        fetch_limit = max(top_k * 10, 30) if query_text else top_k

        query_sql = """
            SELECT id, text, page, source, document_id, metadata,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM document_chunks
            WHERE strategy = %s
        """
        params: list[Any] = [query_vector, strategy]

        if filters:
            for k, v in filters.items():
                query_sql += " AND metadata->>%s = %s"
                params.extend([k, str(v)])

        query_sql += " ORDER BY embedding <=> %s::vector ASC LIMIT %s;"
        params.extend([query_vector, fetch_limit])

        results = []
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query_sql, params)
                rows = cur.fetchall()
                for r in rows:
                    results.append({
                        "id": r[0],
                        "text": r[1],
                        "page": r[2],
                        "source": r[3],
                        "document_id": r[4],
                        "metadata": r[5],
                        "similarity": float(r[6]),
                    })

        # Hybrid Lexical Re-ranking
        if query_text and results:
            stop_words = {
                "là", "gì", "của", "và", "như", "thế", "nào", "trong", "theo", "để", "ở", "với",
                "các", "những", "cho", "ai", "được", "bạn", "tôi", "ra", "sao", "khi", "làm",
                "cuốn", "sách", "tác", "giả", "nói", "hỏi", "về", "có", "một", "này", "đó",
            }
            raw_tokens = re.findall(r"[\w\d%]+", query_text.lower())
            keywords = [t for t in raw_tokens if len(t) >= 2 and t not in stop_words]

            for item in results:
                chunk_lower = item["text"].lower()
                matched_count = 0
                for kw in keywords:
                    if kw in chunk_lower:
                        matched_count += 1
                        # Tăng điểm nếu là từ khóa đặc thù (số, %, tên riêng dài)
                        if "%" in kw or kw.isdigit() or len(kw) >= 6:
                            matched_count += 1.5

                lexical_score = (matched_count / max(1, len(keywords))) if keywords else 0.0
                # Kết hợp 70% vector similarity + 30% lexical overlap
                item["score"] = (item["similarity"] * 0.70) + (min(1.0, lexical_score) * 0.30)

            results.sort(key=lambda x: x.get("score", x["similarity"]), reverse=True)
            results = results[:top_k]

        return results
