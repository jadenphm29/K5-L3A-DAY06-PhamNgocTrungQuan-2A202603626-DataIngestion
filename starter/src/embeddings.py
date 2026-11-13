"""Local LM Studio Embedding Provider.
Connects to LM Studio's OpenAI-compatible server at http://127.0.0.1:1234/v1.
Model: paraphrase-multilingual-MiniLM-L12-v2 (mykor/paraphrase-multilingual-MiniLM-L12-v2.gguf)
Dimensions: 384
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol
from dotenv import load_dotenv

# Tự động đọc biến môi trường từ starter/.env
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, question: str) -> list[float]:
        ...


class MyEmbedder:
    """Hiện thực Embedder kết nối với LM Studio qua endpoint /v1/embeddings."""

    def __init__(
            self,
            model_name: str | None = None,
            base_url: str | None = None,
    ) -> None:
        self.base_url = (
                base_url
                or os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
        ).rstrip("/")
        self.model_name = (
                model_name
                or os.getenv("EMBEDDING_MODEL")
                or "paraphrase-multilingual-MiniLM-L12-v2"
        )
        self.endpoint = f"{self.base_url}/embeddings"

        # Tự động gửi thử 1 từ để kiểm tra kết nối và đo số chiều (dimensions)
        self.dimensions = self._detect_dimensions()

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Gửi văn bản tới LM Studio và nhận về danh sách vector."""
        if not texts:
            return []

        payload = {
            "model": self.model_name,
            "input": texts,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer lm-studio",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                items = sorted(res_json.get("data", []), key=lambda x: x.get("index", 0))
                return [item["embedding"] for item in items]
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Không thể kết nối đến LM Studio tại {self.endpoint}: {e}. "
                "Đảm bảo trong LM Studio nút 'Status: Running' màu xanh đang bật."
            ) from e

    def _detect_dimensions(self) -> int:
        """Tự động kiểm tra model và độ dài vector do LM Studio trả về."""
        # 1. Thử tự động lấy tên model đang nạp trong LM Studio
        try:
            req = urllib.request.Request(f"{self.base_url}/models", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                models = res_json.get("data", [])
                if models:
                    active_id = models[0].get("id")
                    if active_id:
                        self.model_name = active_id
        except Exception:
            pass

        # 2. Gửi thử 1 từ để đo số chiều vector thực tế
        try:
            sample = self._call_api(["ping"])
            dim = len(sample[0])
            print(f"[OK] Kết nối LM Studio thành công!")
            print(f"     Model: {self.model_name} | Số chiều vector: {dim}")
            return dim
        except Exception as e:
            print(f"[LỖI] {e}")
            raise

    def embed_documents(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        """Tạo vector cho danh sách các chunks (chia theo batch để tránh quá tải)."""
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            vectors = self._call_api(batch)
            all_vectors.extend(vectors)
        return all_vectors

    def embed_query(self, question: str) -> list[float]:
        """Tạo vector cho 1 câu hỏi."""
        vectors = self._call_api([question])
        return vectors[0]