"""Rerank 重排模块（；architecture.md 契约偏离：引入本地交叉编码器 reranker）。

链路：RRF 融合候选池放大（RERANK_CANDIDATE_POOL，默认 40）→ Rerank 对 (query, 候选) 对打分
→ 按分降序重排 → 截断 Top-K。Rerank 只改候选**内部顺序**，不改命中集合/字段（检索链路契约不变）。

- 生产：BgeReranker（sentence-transformers CrossEncoder 懒加载 bge-reranker-v2-m3；
  本地快照优先离线加载，同 embedding.py 三级加载，HF_HUB_OFFLINE=1 零网络依赖）
- 测试/DEBUG：FakeReranker（确定性伪打分，按 query 与候选文本字符重叠度打分，仅链路验证）
- 降级哲学（延续）：任何失败（初始化失败/权重缺失/推理超时/云端 HTTP 错误）
  由调用方捕获并降级到 RRF 原序，Rerank 不阻塞检索。

打分口径：交叉编码器 logits 经 sigmoid 归一化到 0~1（相关度语义，与 MarketHit.similarity 同量纲）。
单次调用超时预算 ≤5s（architecture.md 30s 调用约束内），由 retriever 侧 asyncio.wait_for 执行。
"""
import logging
import math
import os
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger("careerai.ai.rag")


class Reranker(Protocol):
    def is_available(self) -> bool: ...

    def scores(self, query: str, docs: list[str]) -> list[float]: ...


def _sigmoid(x: float) -> float:
    """logits → 0~1 相关度（数值稳定版）。"""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


class BgeReranker:
    """bge-reranker-v2-m3 本地交叉编码器（多语言含中文）。

    模型懒加载：首次 scores() 才加载权重（~2.27GB，进程级单例复用）。
    来源解析：显式 model_path > 本地 HF 缓存快照（离线） > model_name 在线。
    """

    def __init__(self, model_name: str, model_path: str = "", device: str = "cpu") -> None:
        self.model_name = model_name
        self.model_path = model_path
        self.device = device
        self._model = None

    def is_available(self) -> bool:
        try:
            import sentence_transformers # noqa: F401
        except ImportError:
            logger.warning("sentence-transformers 未安装，本地 reranker 不可用")
            return False
        return True

    def resolve_source(self) -> str:
        """实际加载来源：显式 model_path > 本地缓存快照 > model_name 在线。"""
        if self.model_path:
            return self.model_path
        snapshot = self._resolve_local_snapshot(self.model_name)
        if snapshot:
            return snapshot
        return self.model_name

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            source = self.resolve_source()
            logger.info("loading reranker %s from %s (device=%s)", self.model_name, source, self.device)
            if source != self.model_name:
                os.environ.setdefault("HF_HUB_OFFLINE", "1") # 本地快照加载，禁止联网探测
            self._model = CrossEncoder(source, device=self.device, max_length=512)
        return self._model

    def scores(self, query: str, docs: list[str]) -> list[float]:
        """对 (query, doc) 对打分，返回 0~1 相关度列表（顺序与 docs 一致）。"""
        if not docs:
            return []
        model = self._ensure_model()
        pairs = [(query, doc) for doc in docs]
        logits = model.predict(pairs, show_progress_bar=False)
        return [_sigmoid(float(x)) for x in logits]

    @classmethod
    def _resolve_local_snapshot(cls, model_name: str) -> str:
        """从 HuggingFace 本地缓存发现完整快照（同 embedding.py，思路）。

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


class FakeReranker:
    """确定性伪重排（仅测试/DEBUG 环境，禁止用于生产）。

    打分 = query 与 doc 归一化后的字符重叠覆盖率（共享字符越多 → 相关度越高），
    与 FakeEmbeddingProvider 同思路：让排序/降级/候选池放大测试可确定性验证。
    """
    available: bool = True # 测试可置 False 模拟不可用

    def is_available(self) -> bool:
        return self.available

    @staticmethod
    def _norm(text: str) -> str:
        return "".join(ch.lower() for ch in text if ch.isalnum())

    def scores(self, query: str, docs: list[str]) -> list[float]:
        q = set(self._norm(query))
        out: list[float] = []
        for doc in docs:
            d = set(self._norm(doc))
            if not q or not d:
                out.append(0.0)
                continue
            overlap = len(q & d) / max(len(q), len(d))
            out.append(round(overlap, 4))
        return out


@lru_cache(maxsize=1)
def get_reranker() -> Reranker:
    """按配置返回可用 reranker（进程级单例）：
    - 测试/DEBUG：FakeReranker（带警告）
    - 生产：BgeReranker（sentence-transformers 不可用时 is_available()=False，Rerank 降级）
    """
    s = get_settings()
    if s.TESTING or s.DEBUG:
        logger.warning("rerank: 使用 FakeReranker（仅测试/DEBUG 环境）")
        return FakeReranker()
    return BgeReranker(
        model_name=s.RERANK_MODEL, model_path=s.RERANK_MODEL_PATH, device=s.RERANK_DEVICE
    )
