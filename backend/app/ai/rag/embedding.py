"""Embedding 提供方（：bge-m3 本地向量化，1024 维，无 API 成本/无数据出境）。

- 生产：BgeM3EmbeddingProvider（sentence-transformers 懒加载，模型首次调用时才加载；
   增强：model_path 未配置时自动发现 HuggingFace 本地缓存快照，优先离线加载）
- 测试/未部署环境：FakeEmbeddingProvider（确定性伪嵌入，仅链路验证）
"""
import hashlib
import logging
import os
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger("careerai.ai.rag")


class EmbeddingProvider(Protocol):
    dim: int

    def is_available(self) -> bool: ...

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class BgeM3EmbeddingProvider:
    """bge-m3（BAAI/bge-m3）本地向量化。模型懒加载：首次 encode 才加载权重。"""

    def __init__(self, model_name: str, model_path: str = "", device: str = "cpu") -> None:
        self.model_name = model_name
        self.model_path = model_path
        self.device = device
        self.dim = 1024
        self._model = None

    def is_available(self) -> bool:
        try:
            import sentence_transformers # noqa: F401
        except ImportError:
            logger.warning("sentence-transformers 未安装，bge-m3 不可用")
            return False
        return True

    def resolve_source(self) -> str:
        """返回实际加载来源（显式 model_path > 本地缓存快照 > model_name 在线）。"""
        if self.model_path:
            return self.model_path
        snapshot = self._resolve_local_snapshot(self.model_name)
        if snapshot:
            return snapshot
        return self.model_name

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            source = self.resolve_source()
            logger.info("loading bge-m3 from %s (device=%s)", source, self.device)
            if source != self.model_name:
                os.environ.setdefault("HF_HUB_OFFLINE", "1") # 本地快照加载，禁止联网探测
            self._model = SentenceTransformer(source, device=self.device)
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [vec.tolist() for vec in vectors]

    @classmethod
    def _resolve_local_snapshot(cls, model_name: str) -> str:
        """从 HuggingFace 本地缓存发现模型完整快照（：无网络依赖加载）。

        判定完整：快照目录含 config.json 且含权重文件（model.safetensors / pytorch_model.bin）。
        多个快照取最新；无完整快照返回空串（回退 model_name 在线加载）。
        """
        try:
            from huggingface_hub.constants import HF_HUB_CACHE
        except Exception: # noqa: BLE001 huggingface_hub 未安装
            return ""
        repo_dir = os.path.join(HF_HUB_CACHE, f"models--{model_name.replace('/', '--')}")
        snapshots_dir = os.path.join(repo_dir, "snapshots")
        if not os.path.isdir(snapshots_dir):
            return ""
        candidates: list[str] = []
        for entry in os.listdir(snapshots_dir):
            snap_path = os.path.join(snapshots_dir, entry)
            if not os.path.isdir(snap_path):
                continue
            has_config = os.path.isfile(os.path.join(snap_path, "config.json"))
            has_weights = any(
                os.path.isfile(os.path.join(snap_path, name))
                for name in ("model.safetensors", "pytorch_model.bin")
            )
            if has_config and has_weights:
                candidates.append(snap_path)
        if not candidates:
            return ""
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]


class FakeEmbeddingProvider:
    """确定性伪嵌入（1024 维）：仅测试/DEBUG 环境用于链路验证，禁止用于生产数据。

    语义近似：按字符重叠构造向量（共享字符越多 → 余弦越高），使阈值/排序测试可验证。
    """
    dim = 1024

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def is_available(self) -> bool:
        return True

    def encode(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for ch in text:
                bucket = int(hashlib.md5(ch.encode("utf-8")).hexdigest(), 16) % self.dim
                sign = 1.0 if (int(hashlib.md5((ch + "#s").encode("utf-8")).hexdigest(), 16) % 2) else -1.0
                vec[bucket] += sign
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """按配置返回可用 provider：
    - 测试/DEBUG：FakeEmbeddingProvider（带警告）
    - 生产：BgeM3EmbeddingProvider（sentence-transformers 不可用时 is_available()=False，RAG 降级）
    - 进程级单例：bge-m3 权重约 2GB，仅首次调用加载；多任务/多查询复用同一实例
    """
    s = get_settings()
    if s.TESTING or s.DEBUG:
        logger.warning("embedding: 使用 FakeEmbeddingProvider（仅测试/DEBUG 环境）")
        return FakeEmbeddingProvider()
    return BgeM3EmbeddingProvider(
        model_name=s.BGE_M3_MODEL_NAME, model_path=s.BGE_M3_MODEL_PATH, device=s.BGE_M3_DEVICE
    )
