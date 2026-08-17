"""RAG 检索评估脚本：recall@k / 命中率 / 相关度。

用法（在 ``backend`` 目录下）：
    python -m scripts.eval_rag [--data DIR] [--mode auto|mock|real] [--json] [--out FILE]

设计要点（面试证据链 / 无 key 无权重可跑）：
- 默认 ``--mode auto``：优先走真实检索链路（DB market_data + bge-m3）；
  任一前置缺失（DB 不可达 / 空向量库 / embedding 权重缺失 / provider 不可用）→
  自动降级为 mock 模式并在输出中明确标注「mock 模式」与降级原因。
- ``--mode mock``：强制使用 ``evaluation_data/market_corpus.json`` 合成语料 +
  ``FakeEmbeddingProvider``（确定性伪嵌入，纯 Python，无任何外部依赖）。
- ``--mode real``：强制真实链路，前置缺失时报错退出（exit 1），不静默降级。
- 环境检查固定输出：DEEPSEEK_API_KEY 缺失提示（RAG 评估不依赖 LLM，仅提示）、
  embedding provider、向量库来源，保证「缺 key / 缺权重」场景下输出明确标注。

本脚本对 ``app/ai/`` 现有逻辑仅只读引用（retriever/embedding），不修改任何业务代码。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.ai.evaluation import (  # noqa: E402
    EVALUATION_DATA_DIR,
    load_market_corpus,
    load_rag_cases,
    market_record_to_text,
    schema_description,
)
from app.ai.evaluation.schemas import MarketCorpusRecord, RagEvalCase  # noqa: E402

DEFAULT_KS = (1, 3, 5, 10)


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    case_id: str
    query: str
    expected: list[str]
    retrieved: dict[int, list[tuple[str, float]]] = field(default_factory=dict)
    recall: dict[int, float] = field(default_factory=dict)
    hit: dict[int, float] = field(default_factory=dict)
    relevance: dict[int, float | None] = field(default_factory=dict)
    expected_in_corpus: dict[str, bool] = field(default_factory=dict)
    # 负向断言与反例标记（2b/2d）
    must_not_hit: list[str] = field(default_factory=list)
    must_not_hit_violations: dict[int, list[str]] = field(default_factory=dict)
    is_negative: bool = False # 无命中反例：单列断言，不计入 recall/hit/coverage 聚合

    def compute(self, ks: tuple[int, ...], expected_set: set[str]) -> None:
        for k in ks:
            hits = self.retrieved.get(k, [])
            titles = [t for t, _ in hits]
            hits_set = set(titles)
            n = len(expected_set) or 1
            self.recall[k] = round(len(expected_set & hits_set) / n, 4)
            self.hit[k] = 1.0 if expected_set & hits_set else 0.0
            rel = [s for t, s in hits if t in expected_set]
            self.relevance[k] = round(sum(rel) / len(rel), 4) if rel else None
            # must_not_hit 负向断言：Top-K 不得包含黑名单岗位
            if self.must_not_hit:
                violations = [t for t in titles if t in set(self.must_not_hit)]
                if violations:
                    self.must_not_hit_violations[k] = violations

    def to_dict(self, ks: tuple[int, ...]) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "expected_job_titles": self.expected,
            "expected_in_corpus": self.expected_in_corpus,
            "must_not_hit": self.must_not_hit,
            "must_not_hit_violations": {
                str(k): v for k, v in sorted(self.must_not_hit_violations.items())
            },
            "is_negative": self.is_negative,
            "retrieved@k": {
                str(k): [t for t, _ in self.retrieved.get(k, [])] for k in ks
            },
            "recall@k": {str(k): self.recall.get(k) for k in ks},
            "hit@k": {str(k): self.hit.get(k) for k in ks},
            "relevance@k": {str(k): self.relevance.get(k) for k in ks},
        }


def _aggregate(results: list[CaseResult], ks: tuple[int, ...]) -> dict[str, float]:
    # （2d）：反例不计入 recall/hit/relevance/coverage 聚合
    positive = [r for r in results if not r.is_negative]
    n = len(positive) or 1
    out: dict[str, float] = {}
    for k in ks:
        out[f"recall@{k}"] = round(sum(r.recall[k] for r in positive) / n, 4)
        out[f"hit@{k}"] = round(sum(r.hit[k] for r in positive) / n, 4)
        rels = [r.relevance[k] for r in positive if r.relevance[k] is not None]
        out[f"relevance@{k}"] = round(sum(rels) / len(rels), 4) if rels else None
    # ground truth 覆盖度（仅正例）：期望岗位在评估语料中实际存在的比例（区分「语料缺真值」与「检索失败」）
    all_expected = [t for r in positive for t in r.expected]
    covered = [t for r in positive for t, ok in r.expected_in_corpus.items() if ok]
    out["ground_truth_coverage"] = round(len(covered) / len(all_expected), 4) if all_expected else 1.0
    # must_not_hit 负向断言通过率（仅正例，按 Top-10 判定；反例不参与 precision 断言）
    mn_passed = 0
    mn_total = 0
    max_k = max(ks)
    for r in positive:
        if not r.must_not_hit:
            continue
        mn_total += 1
        if max_k not in r.must_not_hit_violations:
            mn_passed += 1
    out["must_not_hit_pass"] = round(mn_passed / mn_total, 4) if mn_total else 1.0
    out["must_not_hit_total"] = float(mn_total)
    # 反例单列断言（2d）：返回空命中/不含 expected —— Top-K 无任何命中视为通过
    neg_total = len([r for r in results if r.is_negative])
    neg_pass = 0
    for r in results:
        if not r.is_negative:
            continue
        titles = [t for t, _ in r.retrieved.get(max_k, [])]
        if not titles or not (set(r.expected) & set(titles)):
            neg_pass += 1
    out["negative_pass"] = round(neg_pass / neg_total, 4) if neg_total else 1.0
    out["negative_total"] = float(neg_total)
    return out


# ---------------------------------------------------------------------------
# mock 检索（确定性伪嵌入，内存余弦检索）
# ---------------------------------------------------------------------------
def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return dot / (na * nb)


def _mock_eval(cases: list[RagEvalCase], corpus: list[MarketCorpusRecord], ks: tuple[int, ...], threshold: float) -> list[CaseResult]:
    """mock 检索：FakeEmbeddingProvider 内存余弦（确定性底座）。

    ：当 RERANK_ENABLED=true 时，模拟真实链路形态——向量召回候选池
    （RERANK_CANDIDATE_POOL）→ FakeReranker 重排 → 截断 Top-K，作为
    「真实环境缺失时 mock+FakeReranker 中间证据」（验证标准 3 兜底）。
    """
    from app.ai.rag.embedding import FakeEmbeddingProvider
    from app.ai.rag.reranker import FakeReranker
    from app.core.config import get_settings

    settings = get_settings()
    rerank_enabled = settings.RERANK_ENABLED
    pool_size = settings.RERANK_CANDIDATE_POOL if rerank_enabled else max(ks)
    reranker = FakeReranker() if rerank_enabled else None

    provider = FakeEmbeddingProvider()
    texts = [market_record_to_text(r) for r in corpus]
    corpus_vecs = provider.encode(texts) if texts else []
    results: list[CaseResult] = []
    for case in cases:
        qv = provider.encode([case.query])[0]
        sims = [_cosine(qv, cv) for cv in corpus_vecs]
        order = sorted(range(len(corpus)), key=lambda i: sims[i], reverse=True)
        res = CaseResult(
            case_id=case.case_id, query=case.query, expected=list(case.expected_job_titles),
            must_not_hit=list(case.must_not_hit), is_negative=case.is_negative,
        )
        corpus_titles = {r.job_title for r in corpus}
        res.expected_in_corpus = {t: t in corpus_titles for t in case.expected_job_titles}
        # 候选池：前 pool_size（模拟 RRF 融合放大候选）
        pool = [(corpus[i].job_title, round(sims[i], 4)) for i in order[:pool_size] if sims[i] >= threshold]
        if reranker is not None and pool:
            docs = [t for t, _ in pool]
            scores = reranker.scores(case.query, docs)
            pool = sorted(zip(docs, scores, strict=False), key=lambda x: x[1], reverse=True)
        for k in ks:
            res.retrieved[k] = [(t, s) for t, s in pool[:k]]
        res.compute(ks, set(case.expected_job_titles))
        results.append(res)
    return results


# ---------------------------------------------------------------------------
# real 检索（真实链路：market_data + bge-m3；前置缺失时抛出降级原因）
# ---------------------------------------------------------------------------
def _real_eval(cases: list[RagEvalCase], ks: tuple[int, ...], args: argparse.Namespace) -> list[CaseResult]:
    """真实检索链路。前置检查按「轻量优先」排序，避免无权重环境被重型依赖阻塞：

    1. provider 类型（Fake 不可用于真实链路）；
    2. 权重本地可用性（model_path 目录 / HF 缓存快照）——不触发 sentence-transformers 导入；
    3. DB 可达 + 向量数据非空；
    4. 仅当以上全通过才导入 retriever / 触发 encode（此时才可能慢速加载权重）。
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.ai.rag.embedding import FakeEmbeddingProvider, get_embedding_provider
    from app.core.config import get_settings

    settings = get_settings()
    # 抑制 HF/safetensors 权重加载进度条（仅真实链路生效，避免污染结构化输出）
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    try:
        from transformers.utils import logging as _hf_logging

        _hf_logging.disable_progress_bar()
    except Exception: # transformers 未安装时忽略
        pass

    async def _run() -> list[CaseResult]:
        provider = get_embedding_provider()
        if isinstance(provider, FakeEmbeddingProvider):
            raise RuntimeError("embedding provider 为 Fake（TESTING/DEBUG 环境），真实检索要求 bge-m3")
        # 权重可用性预检（轻量，不导入 sentence-transformers）
        source = provider.resolve_source()
        if source == provider.model_name and not args.allow_download:
            raise RuntimeError(
                "bge-m3 模型权重未在本地发现（model_path 未配置且无 HF 缓存快照）；"
                "如需在线下载请加 --allow-download"
            )

        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=args.db_timeout)
                count = (
                    await conn.execute(
                        text("SELECT count(*) FROM market_data WHERE embedding IS NOT NULL")
                    )
                ).scalar_one()
            if not count:
                raise RuntimeError("market_data 表无向量数据（空向量库）")

            # 到这里说明权重与向量库都真实可用，才导入检索器（重依赖延迟加载）
            from app.ai.rag.retriever import search_market

            corpus_titles: set[str] = set()
            async with AsyncSession(engine) as session:
                for row in (await session.execute(text("SELECT DISTINCT job_title FROM market_data"))).all():
                    if row[0]:
                        corpus_titles.add(str(row[0]))
            max_k = max(ks)
            results: list[CaseResult] = []
            async with AsyncSession(engine) as session:
                for case in cases:
                    hits = await search_market(session, case.query, top_k=max_k, provider=provider)
                    res = CaseResult(
                        case_id=case.case_id, query=case.query, expected=list(case.expected_job_titles),
                        must_not_hit=list(case.must_not_hit), is_negative=case.is_negative,
                    )
                    res.expected_in_corpus = {t: t in corpus_titles for t in case.expected_job_titles}
                    for k in ks:
                        res.retrieved[k] = [(h.job_title, h.similarity) for h in hits[:k]]
                    res.compute(ks, set(case.expected_job_titles))
                    results.append(res)
            return results
        finally:
            await engine.dispose()

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# 有界执行（真实链路可能首载模型权重耗时数分钟，必须硬超时保护）
# ---------------------------------------------------------------------------
def _run_with_timeout(fn, timeout: float, timeout_msg: str) -> Any:
    """在守护线程中执行 fn，超过 timeout 秒抛 RuntimeError。

    - 守护线程：超时后脚本继续降级/退出，不等待后台加载完成；
    - 正常完成时透传返回值或异常。
    """
    import threading

    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc: # 透传任意异常给主线程
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise RuntimeError(timeout_msg)
    if "error" in box:
        raise box["error"]
    return box["result"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _env_checks(mode: str, degraded: str | None) -> dict[str, str]:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    checks: dict[str, str] = {
        "deepseek_api_key": "缺失（已提示：RAG 检索评估不依赖 LLM key；如需 LLM-as-judge 扩展需配置）"
        if not key
        else "已配置（本评估当前不使用 LLM）",
    }
    rerank = os.environ.get("RERANK_ENABLED", "")
    if rerank:
        checks["rerank"] = "开启（--rerank/环境变量 RERANK_ENABLED=true；候选池放大→重排→截断 Top-K）" if rerank.lower() == "true" else "关闭（--no-rerank/RERANK_ENABLED=false；对照组）"
    else:
        checks["rerank"] = "跟随配置（RERANK_ENABLED 未显式指定，按 config.py 默认）"
    if mode == "mock":
        checks["embedding_provider"] = "FakeEmbeddingProvider（确定性伪嵌入，仅 mock 链路）"
        checks["vector_db"] = "内存合成语料（evaluation_data/market_corpus.json）"
    else:
        checks["embedding_provider"] = "BgeM3EmbeddingProvider（真实 bge-m3）"
        checks["vector_db"] = "market_data（pgvector 余弦检索）"
    if degraded:
        checks["degraded_reason"] = degraded
    return checks


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAG 检索评估：recall@k / 命中率 / 相关度")
    p.add_argument("--data", default=str(EVALUATION_DATA_DIR), help="评测数据目录（默认 evaluation_data）")
    p.add_argument("--mode", choices=("auto", "mock", "real"), default="auto", help="auto=优先真实链路，缺失自动降级 mock")
    p.add_argument("--ks", default="1,3,5,10", help="Top-K 列表，逗号分隔（默认 1,3,5,10）")
    p.add_argument("--threshold", type=float, default=0.0, help="mock 模式相似度阈值（默认 0.0=仅排序；真实链路阈值由 RAG_SIMILARITY_THRESHOLD 决定）")
    p.add_argument("--db-timeout", type=float, default=5.0, help="真实链路 DB 探测超时秒数（默认 5）")
    p.add_argument("--real-timeout", type=float, default=120.0, help="真实链路整体硬超时秒数（默认 120；首次加载 bge-m3 权重约 1 分钟）")
    p.add_argument("--allow-download", action="store_true", help="允许 bge-m3 在线下载权重（真实链路，默认禁止）")
    p.add_argument("--rerank", action="store_true", help="强制开启 Rerank 重排（覆盖 RERANK_ENABLED 环境变量/配置；对比实验用）")
    p.add_argument("--no-rerank", action="store_true", help="强制关闭 Rerank 重排（覆盖 RERANK_ENABLED 环境变量/配置；对照组）")
    p.add_argument("--json", action="store_true", help="仅输出 JSON")
    p.add_argument("--out", help="将 JSON 结果写入文件（同时保留人类可读输出）")
    p.add_argument("--schema", action="store_true", help="输出评测集 schema 说明并退出")
    return p.parse_args(argv)


def _render(results: list[CaseResult], agg: dict[str, float], checks: dict[str, str], mode: str, degraded: str | None, data_dir: str, corpus_n: int, cases_n: int, ks: tuple[int, ...]) -> str:
    lines: list[str] = []
    lines.append("=" * 62)
    lines.append("RAG 检索评估（AI Evaluation ·）")
    lines.append(f"模式: {mode}" + ("（mock 模式）" if mode == "mock" else "") + (f"｜降级原因: {degraded}" if degraded else ""))
    lines.append("-" * 62)
    for k, v in checks.items():
        lines.append(f" - {k}: {v}")
    lines.append(f"数据集: {data_dir}（cases={cases_n}，corpus={corpus_n}，schema v1.0）")
    cov = agg.get("ground_truth_coverage")
    lines.append(f"ground_truth 覆盖度: {cov:.1%}（期望岗位在评估语料中存在的比例；低于 100% 时 recall 偏低为语料缺真值，而非检索失败）")
    mn_pass = agg.get("must_not_hit_pass")
    mn_total = agg.get("must_not_hit_total")
    neg_pass = agg.get("negative_pass")
    neg_total = agg.get("negative_total")
    lines.append(f"must_not_hit 负向断言通过率: {mn_pass:.1%}（{int(mn_total)} 个含负向断言的用例，按 Top-10 判定不得命中）")
    lines.append(f"反例断言通过率: {neg_pass:.1%}（{int(neg_total)} 个无命中反例，Top-K 返回空/不含 expected）")
    lines.append("-" * 62)
    lines.append(f"{'Top-K':<8}{'recall@k':<12}{'hit@k':<12}{'relevance(相关度)':<18}")
    for k in ks:
        rel = agg.get(f"relevance@{k}")
        lines.append(f"{k:<8}{agg[f'recall@{k}']:<12.4f}{agg[f'hit@{k}']:<12.4f}{(f'{rel:.4f}' if rel is not None else 'N/A'):<18}")
    k_show = ks[0] if ks else 1
    lines.append("-" * 62)
    lines.append(f"逐条明细（展示 @{k_show}）：")
    for r in results:
        recall_k = r.recall.get(k_show)
        hit_k = r.hit.get(k_show)
        got = "、".join(t for t, _ in r.retrieved.get(k_show, [])) or "（无命中）"
        tag = " [反例]" if r.is_negative else ""
        mn = f" must_not_hit违规={r.must_not_hit_violations}" if r.must_not_hit_violations else ""
        lines.append(f" [{r.case_id}{tag}] 期望={r.expected} recall@{k_show}={recall_k} hit@{k_show}={hit_k}{mn} | 前{k_show}: {got}")
    lines.append("=" * 62)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.schema:
        print(schema_description())
        return 0
    # --rerank/--no-rerank 显式覆盖配置（必须在 get_settings() 首次调用前生效）
    if args.rerank:
        os.environ["RERANK_ENABLED"] = "true"
    if args.no_rerank:
        os.environ["RERANK_ENABLED"] = "false"
    data_dir = Path(args.data)
    ks = tuple(sorted({int(x) for x in args.ks.split(",") if x.strip()}, reverse=False)) or DEFAULT_KS

    try:
        cases = load_rag_cases(data_dir)
        corpus = load_market_corpus(data_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[eval_rag] 错误：{exc}", file=sys.stderr)
        return 2

    mode = args.mode
    degraded: str | None = None
    results: list[CaseResult] = []
    if mode == "mock":
        results = _mock_eval(cases, corpus, ks, args.threshold)
    elif mode == "real":
        print("[eval_rag] 真实链路执行中（DB + bge-m3，首次加载权重约 1 分钟）……", file=sys.stderr)
        try:
            results = _run_with_timeout(
                lambda: _real_eval(cases, ks, args), args.real_timeout,
                f"真实链路超时（>{args.real_timeout:.0f}s，通常为首载 bge-m3 权重），请加 --mode mock 或增大 --real-timeout",
            )
        except Exception as exc: # 强制 real 失败 = 错误
            print(f"[eval_rag] 错误（--mode real 前置缺失或超时）：{exc}", file=sys.stderr)
            return 1
    else: # auto
        print("[eval_rag] 尝试真实链路（DB + bge-m3）；前置缺失/超时自动降级 mock……", file=sys.stderr)
        try:
            results = _run_with_timeout(
                lambda: _real_eval(cases, ks, args), args.real_timeout,
                f"真实链路超时（>{args.real_timeout:.0f}s，通常为首载 bge-m3 权重），已降级 mock",
            )
        except Exception as exc: # 自动降级 mock
            degraded = str(exc)
            results = _mock_eval(cases, corpus, ks, args.threshold)
            mode = "mock"

    if not cases:
        print("[eval_rag] 警告：评测集为空（cases=0），输出降级结果（全 0），不崩溃", file=sys.stderr)
    if not corpus:
        print("[eval_rag] 警告：语料为空（corpus=0，空向量库），输出降级结果（全 0），不崩溃", file=sys.stderr)

    agg = _aggregate(results, ks)
    payload: dict[str, Any] = {
        "tool": "eval_rag",
        "schema_version": "1.0",
        "mode": mode,
        "mock_mode": mode == "mock",
        "degraded_reason": degraded,
        "env_checks": _env_checks(mode, degraded),
        "dataset": {"data_dir": str(data_dir), "cases": len(cases), "corpus": len(corpus)},
        "metrics": agg,
        "cases": [r.to_dict(ks) for r in results],
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render(results, agg, payload["env_checks"], mode, degraded, str(data_dir), len(corpus), len(cases), ks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
