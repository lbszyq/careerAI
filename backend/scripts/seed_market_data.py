"""真实市场数据幂等入库脚本。

用法（在 backend 目录下）::

    python scripts/seed_market_data.py # 幂等增量：只插入 JSON 中不存在的记录 + 补缺失 embedding
    python scripts/seed_market_data.py --force # 全量重建：删除本 JSON 覆盖记录 → 重插 → 全表 embedding 重刷
    python scripts/seed_market_data.py --dry-run # 只校验与预演，不写库
    python scripts/seed_market_data.py --no-embed # 跳过向量化

- 数据文件：backend/data/market_records_2026Q2.json（字段对齐 app.models.market.MarketData）
- 幂等键：(data_quarter, city, industry, job_title, data_source)——重复执行不产生重复数据
- 真实向量化：DEBUG=false 时使用 bge-m3（1024 维）；DEBUG=true（测试/调试）时使用 FakeEmbedding 仅链路验证
- 表结构兼容：market_data 有 source_type 列时直接写入（迁移落地后生效）；
  旧库（无列）降级：插入不写该列，--backfill-source-type 会明确报错要求先迁移
- source_type 回填：python scripts/seed_market_data.py --backfill-source-type
  （307 条按幂等键匹配 JSON 的 source_type；存量 legacy-jd 28 条标 job_post；未匹配仅日志标注）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import insert, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.ai.rag.vectorize import sync_market_embeddings  # noqa: E402
from app.db.base import AsyncSessionLocal  # noqa: E402
from app.models.market import MarketData  # noqa: E402

VALID_SOURCE_TYPES = {"official_stat", "job_post"} # 禁止 ai_infer（反幻觉）
VALID_CITY_TIERS = {"一线", "新一线", "二线", "三线", "四线及以下"}
VALID_TRENDS = {None, "增长", "稳定", "下降"}
VALID_HEATS = {None, "高", "中", "低"}
# 学历要求值域：不限/大专/本科/硕士/博士；大专/本科/硕士可带「及以上」
EDUCATION_BASES = ("不限", "大专", "本科", "硕士", "博士")
EDUCATION_SUFFIX_BASES = ("大专", "本科", "硕士")
QUARTER_RE = re.compile(r"^\d{4}Q[1-4]$")
REQUIRED_FIELDS = ("city", "industry", "job_title", "data_quarter", "city_tier", "source_type", "data_source")
MAJOR_CATEGORIES = (
    "计算机类", "经济金融类", "工商管理类", "教育类", "机械类",
    "电气类", "土木类", "医学类", "法学类", "艺术设计类", "新闻传播类",
)


def default_data_path() -> Path:
    return _BACKEND_DIR / "data" / "market_records_2026Q2.json"


def load_records(path: Path | str | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path else default_data_path()
    if not p.is_file():
        raise FileNotFoundError(f"数据文件不存在：{p}")
    records = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"数据文件顶层必须为数组：{p}")
    return records


def dedup_key(rec: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(rec.get("data_quarter") or ""),
        str(rec.get("city") or ""),
        str(rec.get("industry") or ""),
        str(rec.get("job_title") or ""),
        str(rec.get("data_source") or ""),
    )


def education_requirement_ok(value: Any) -> bool:
    """学历要求值域：不限/大专/本科/硕士/博士，大专/本科/硕士可带「及以上」。

    - None → 合法（可空列，official_stat 天然无学历字段）；
    - 空串/非字符串 → 非法；
    - 「不限」「博士」为端点，不带「及以上」。
    """
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return False
    if v.endswith("及以上"):
        return v[:-3] in EDUCATION_SUFFIX_BASES
    return v in EDUCATION_BASES


@dataclass(frozen=True)
class BackfillUpdate:
    """单条回填计划：id → 目标 source_type。"""
    id: str
    source_type: str


@dataclass(frozen=True)
class BackfillUnmatched:
    """无法按幂等键匹配的记录（禁止静默置空/猜测赋值，仅日志标注）。"""
    id: str
    key: tuple[str, ...]
    reason: str


def build_backfill_plan(
    records: list[dict[str, Any]],
    db_rows: list[tuple[Any, ...]],
) -> tuple[list[BackfillUpdate], list[BackfillUnmatched]]:
    """构建 source_type 回填计划（纯函数，可独立测试）。

    规则（与 seed 幂等键一致）：
    1. 幂等键 (data_quarter, city, industry, job_title, data_source) 命中 JSON → 取 JSON 的 source_type
    2. 未命中但 data_source 前缀「legacy-jd」→ job_post（存量招聘 JD，交付口径）
    3. 其余 → unmatched（明确标注，禁止置空/猜测）

    db_rows 每行为 (id, data_quarter, city, industry, job_title, data_source)。
    """
    json_by_key = {dedup_key(rec): rec["source_type"] for rec in records}
    updates: list[BackfillUpdate] = []
    unmatched: list[BackfillUnmatched] = []
    for row in db_rows:
        row_id = str(row[0])
        key = (
            str(row[1] or ""), str(row[2] or ""), str(row[3] or ""),
            str(row[4] or ""), str(row[5] or ""),
        )
        src = json_by_key.get(key)
        if src in VALID_SOURCE_TYPES:
            updates.append(BackfillUpdate(row_id, src))
            continue
        data_source = str(row[5] or "")
        if data_source.startswith("legacy-jd"):
            updates.append(BackfillUpdate(row_id, "job_post"))
            continue
        unmatched.append(BackfillUnmatched(row_id, key, "幂等键不在 JSON 且非 存量"))
    return updates, unmatched


async def apply_backfill(session: AsyncSession, updates: list[BackfillUpdate]) -> int:
    """按计划逐行 UPDATE source_type（幂等：值相同跳过，返回实际变更行数）。"""
    changed = 0
    for u in updates:
        res = await session.execute(
            text("UPDATE market_data SET source_type = :st WHERE id = :id AND source_type IS DISTINCT FROM :st"),
            {"st": u.source_type, "id": u.id},
        )
        changed += res.rowcount or 0
    return changed

def validate_record(rec: dict[str, Any]) -> list[str]:
    """单条字段合法性校验，返回错误列表（空 = 合法）。"""
    errs: list[str] = []
    for field in REQUIRED_FIELDS:
        if not rec.get(field):
            errs.append(f"缺少必填字段 {field}")
    job_title = rec.get("job_title") or ""
    if job_title.strip() in ("未明确", "暂无", "未知"):
        errs.append(f"job_title 为占位值：{job_title}")
    industry = rec.get("industry") or ""
    if "未明确" in industry:
        errs.append(f"industry 含占位值「未明确」：{industry}")
    city = rec.get("city") or ""
    if city in ("全国", "未知", "暂无"):
        errs.append(f"city 为占位值：{city}")
    source_type = rec.get("source_type")
    if source_type not in VALID_SOURCE_TYPES:
        errs.append(f"source_type 非法（{source_type}），只允许 {sorted(VALID_SOURCE_TYPES)}")
    quarter = rec.get("data_quarter")
    if not QUARTER_RE.match(str(quarter or "")):
        errs.append(f"data_quarter 非法（{quarter}），应为 YYYYQn")
    city_tier = rec.get("city_tier")
    if city_tier not in VALID_CITY_TIERS:
        errs.append(f"city_tier 非法（{city_tier}），应为 {sorted(VALID_CITY_TIERS)}")
    if rec.get("trend") not in VALID_TRENDS:
        errs.append(f"trend 非法（{rec.get('trend')}），应为 增长/稳定/下降 或空")
    if rec.get("heat") not in VALID_HEATS:
        errs.append(f"heat 非法（{rec.get('heat')}），应为 高/中/低 或空")
    for key in ("salary_p25", "salary_p50", "salary_p75"):
        val = rec.get(key)
        if val is not None:
            try:
                num = float(val)
                if num < 0:
                    errs.append(f"{key} 为负数：{num}")
            except (TypeError, ValueError):
                errs.append(f"{key} 非数值：{val!r}")
    confidence = rec.get("confidence")
    if confidence is not None:
        try:
            conf = float(confidence)
            if not 0 <= conf <= 1:
                errs.append(f"confidence 超出 [0,1]：{conf}")
        except (TypeError, ValueError):
            errs.append(f"confidence 非数值：{confidence!r}")
    skills = rec.get("required_skills")
    if skills is not None and not isinstance(skills, list):
        errs.append(f"required_skills 必须为数组或空：{skills!r}")
    if not education_requirement_ok(rec.get("education_requirement")):
        errs.append(
            f"education_requirement 非法（{rec.get('education_requirement')}），"
            f"应为 不限/大专/本科/硕士/博士（大专/本科/硕士可带「及以上」）"
        )
    responsibilities = rec.get("responsibilities")
    if responsibilities is not None:
        if not isinstance(responsibilities, list):
            errs.append(f"responsibilities 必须为数组或空：{responsibilities!r}")
        else:
            for i, item in enumerate(responsibilities):
                if not isinstance(item, str) or not item.strip():
                    errs.append(f"responsibilities[{i}] 非字符串或为空：{item!r}")
    return errs


def validate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """批量校验：返回 {errors: [(index, job_title, err)], duplicates: [key,...], category_counts: {...}}。"""
    errors: list[tuple[int, str, str]] = []
    seen: dict[tuple[str, ...], int] = {}
    duplicates: list[str] = []
    for i, rec in enumerate(records):
        for err in validate_record(rec):
            errors.append((i, str(rec.get("job_title") or ""), err))
        key = dedup_key(rec)
        if key in seen:
            duplicates.append(str(rec.get("job_title")) + "@" + str(rec.get("city")))
        seen[key] = i
    category_counts = Counter(str(rec.get("category") or "其他") for rec in records)
    return {"errors": errors, "duplicates": duplicates, "category_counts": dict(category_counts)}


def category_coverage_ok(records: list[dict[str, Any]], minimum: int = 20) -> dict[str, int]:
    """11 个专业大类每类 ≥ minimum（按数据文件自带 category 字段核对）。"""
    counts = Counter(str(rec.get("category") or "其他") for rec in records)
    missing = {cat: counts.get(cat, 0) for cat in MAJOR_CATEGORIES if counts.get(cat, 0) < minimum}
    return missing


async def _table_columns(session: AsyncSession) -> set[str]:
    stmt = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'market_data'"
    )
    rows = await session.execute(stmt)
    return {r[0] for r in rows}


async def _existing_keys(session: AsyncSession, quarter: str | None = None) -> set[tuple[str, ...]]:
    if quarter:
        stmt = text(
            "SELECT data_quarter, city, industry, job_title, data_source FROM market_data "
            "WHERE data_quarter = :q"
        )
        rows = await session.execute(stmt, {"q": quarter})
    else:
        stmt = text("SELECT data_quarter, city, industry, job_title, data_source FROM market_data")
        rows = await session.execute(stmt)
    out: set[tuple[str, ...]] = set()
    for row in rows:
        out.add((row[0] or "", row[1] or "", row[2] or "", row[3] or "", row[4] or ""))
    return out


async def insert_new_records(
    session: AsyncSession, records: list[dict[str, Any]], *, columns: set[str], quarter: str = "2026Q2"
) -> tuple[int, int]:
    """幂等插入：只插入 DB 中不存在的记录（按幂等键）。返回 (inserted, skipped)。

    - source_type / education_requirement / responsibilities 三列均存在（迁移已落地）→ ORM 写入；
    - 任一可选列未落地（旧库降级）→ Core INSERT 显式列清单（仅写已存在的列），
      避免 ORM 全列 INSERT 在缺列库报 UndefinedColumn（降级实测发现的同类问题）。
    """
    existing = await _existing_keys(session, quarter=quarter)
    has_source_type = "source_type" in columns
    has_education = "education_requirement" in columns
    has_responsibilities = "responsibilities" in columns
    inserted = 0
    skipped = 0
    for rec in records:
        key = dedup_key(rec)
        if key in existing:
            skipped += 1
            continue
        values = _record_values(rec)
        if has_source_type:
            values["source_type"] = rec.get("source_type")
        if has_education:
            values["education_requirement"] = rec.get("education_requirement")
        if has_responsibilities:
            values["responsibilities"] = rec.get("responsibilities") or []
        if has_source_type and has_education and has_responsibilities:
            session.add(MarketData(**values))
        else:
            await session.execute(insert(MarketData).values(id=uuid.uuid4(), **values))
        existing.add(key)
        inserted += 1
    await session.flush()
    return inserted, skipped


def _record_values(rec: dict[str, Any]) -> dict[str, Any]:
    """ORM/Core 共用的基础插入字段（不含 source_type/education_requirement/responsibilities，
    三个可选列由调用方按列存在性补充）。"""
    return {
        "city": rec["city"],
        "industry": rec["industry"],
        "job_title": rec["job_title"],
        "salary_p25": rec.get("salary_p25"),
        "salary_p50": rec.get("salary_p50"),
        "salary_p75": rec.get("salary_p75"),
        "trend": rec.get("trend"),
        "heat": rec.get("heat"),
        "required_skills": rec.get("required_skills") or [],
        "data_source": rec.get("data_source"),
        "confidence": rec.get("confidence"),
        "data_quarter": rec.get("data_quarter"),
        "city_tier": rec.get("city_tier"),
    }
async def delete_json_covered(
    session: AsyncSession, records: list[dict[str, Any]]
) -> int:
    """全量重建（--force）：删除与本 JSON 幂等键完全相同的现有记录（保留其他来源如）。"""
    json_keys = {dedup_key(rec) for rec in records}
    stmt = text("SELECT id, data_quarter, city, industry, job_title, data_source FROM market_data")
    rows = await session.execute(stmt)
    to_delete: list[str] = []
    for row in rows:
        key = (row[1] or "", row[2] or "", row[3] or "", row[4] or "", row[5] or "")
        if key in json_keys:
            to_delete.append(str(row[0]))
    if to_delete:
        await session.execute(
            text("DELETE FROM market_data WHERE id = ANY(:ids)"),
            {"ids": to_delete},
        )
    return len(to_delete)


def _print_summary(records: list[dict[str, Any]], *, inserted: int, skipped: int, deleted: int,
                   existing_total: int, embedded_total: int, force: bool, dry_run: bool) -> None:
    counts = Counter(str(rec.get("category") or "其他") for rec in records)
    print("=" * 62)
    print(f" 市场数据入库{'（dry-run 预演）' if dry_run else ''}")
    print("-" * 62)
    print(f"数据文件: {default_data_path()}")
    print(f"JSON 记录数: {len(records)}")
    print(f"幂等新增: {inserted}｜跳过(已存在): {skipped}｜{'重建删除: ' + str(deleted) if force else ''}")
    print(f"入库后 DB 总数: {existing_total}（embedding 非空: {embedded_total}）")
    print("专业大类分布（数据文件 category 口径）:")
    for cat in MAJOR_CATEGORIES:
        print(f" {cat}: {counts.get(cat, 0)}")
    other = sum(v for k, v in counts.items() if k not in MAJOR_CATEGORIES)
    if other:
        print(f" 其他: {other}")
    print("=" * 62)


async def backfill_main(session: AsyncSession, records: list[dict[str, Any]]) -> int:
    """回填 source_type：JSON 幂等键匹配 + 存量 job_post。"""
    columns = await _table_columns(session)
    if "source_type" not in columns:
        print("[seed] --backfill-source-type 失败：market_data 无 source_type 列，请先执行 alembic upgrade head", file=sys.stderr)
        return 4
    rows = (await session.execute(
        text("SELECT id, data_quarter, city, industry, job_title, data_source FROM market_data")
    )).fetchall()
    updates, unmatched = build_backfill_plan(records, rows)
    changed = await apply_backfill(session, updates)
    await session.commit()

    dist = Counter(u.source_type for u in updates)
    total = (await session.execute(text("SELECT COUNT(*) FROM market_data"))).scalar_one()
    non_null = (await session.execute(
        text("SELECT COUNT(*) FROM market_data WHERE source_type IS NOT NULL")
    )).scalar_one()
    print("=" * 62)
    print("source_type 回填完成")
    print("-" * 62)
    print(f"回填计划: {len(updates)} 条（实际变更 {changed} 条）｜未匹配 {len(unmatched)} 条")
    print(f"分布: official_stat={dist.get('official_stat', 0)}｜job_post={dist.get('job_post', 0)}")
    print(f"回填后: 全表 {total} 条，source_type 非空 {non_null} 条")
    print("=" * 62)
    for um in unmatched:
        print(f"[seed] 未匹配（未置空/未猜测）id={um.id} 幂等键={um.key} 原因={um.reason}", file=sys.stderr)
    if unmatched:
        print(f"[seed] 警告：{len(unmatched)} 条无法按幂等键匹配，已记录，未静默置空", file=sys.stderr)
    return 0

async def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="真实市场数据幂等入库（校验→入库→向量化）")
    p.add_argument("--data", type=str, default=None, help="数据文件路径（默认 backend/data/market_records_2026Q2.json）")
    p.add_argument("--force", action="store_true", help="全量重建：删除本 JSON 覆盖记录后重插，并全表重刷 embedding")
    p.add_argument("--dry-run", action="store_true", help="只校验与预演，不写库")
    p.add_argument("--no-embed", action="store_true", help="跳过向量化")
    p.add_argument("--backfill-source-type", action="store_true",
                   help="回填 source_type：JSON 幂等键匹配 + legacy-jd→job_post（未匹配仅日志标注）")
    args = p.parse_args(argv)

    records = load_records(args.data)
    check = validate_records(records)
    if check["errors"]:
        print(f"[seed] 校验失败：{len(check['errors'])} 条错误，中止入库", file=sys.stderr)
        for i, title, err in check["errors"][:20]:
            print(f" [{i}] {title}: {err}", file=sys.stderr)
        return 2
    if check["duplicates"]:
        print(f"[seed] 数据文件存在 {len(check['duplicates'])} 个重复幂等键，中止入库", file=sys.stderr)
        for d in check["duplicates"][:10]:
            print(f" {d}", file=sys.stderr)
        return 2
    missing = category_coverage_ok(records)
    if missing:
        print(f"[seed] 专业大类覆盖不足：{missing}（每类需 ≥20）", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as session:
        columns = await _table_columns(session)
        if "source_type" not in columns:
            print("[seed] 提示：market_data 无 source_type 列（旧库降级模式）——插入不写该列，data_grade 不落地；请先执行 alembic upgrade head", file=sys.stderr)

        if args.backfill_source_type:
            return await backfill_main(session, records)

        existing_total = (
            await session.execute(text("SELECT COUNT(*) FROM market_data"))
        ).scalar_one()

        if args.dry_run:
            # 预演：模拟删除/新增数量
            json_keys = {dedup_key(rec) for rec in records}
            rows = (await session.execute(
                text("SELECT data_quarter, city, industry, job_title, data_source FROM market_data")
            )).fetchall()
            existing_keys = {(r[0] or "", r[1] or "", r[2] or "", r[3] or "", r[4] or "") for r in rows}
            would_delete = len(json_keys & existing_keys)
            would_insert = len(json_keys - existing_keys)
            print(f"[dry-run] 将新增 {would_insert} 条、重建删除 {would_delete} 条（--force 时）；当前 DB 共 {existing_total} 条")
            _print_summary(records, inserted=would_insert, skipped=len(records) - would_insert,
                           deleted=would_delete, existing_total=existing_total,
                           embedded_total=existing_total, force=args.force, dry_run=True)
            return 0

        deleted = 0
        if args.force:
            deleted = await delete_json_covered(session, records)
            print(f"[seed] --force：删除本 JSON 覆盖记录 {deleted} 条")
        inserted, skipped = await insert_new_records(session, records, columns=columns)
        await session.commit()

        total = (
            await session.execute(text("SELECT COUNT(*) FROM market_data"))
        ).scalar_one()

        if not args.no_embed:
            from app.ai.rag.embedding import get_embedding_provider
            provider = get_embedding_provider()
            print(f"[seed] 向量化：provider={type(provider).__name__}（force={args.force}）")
            updated = await sync_market_embeddings(session, provider=provider, force=args.force)
            await session.commit()
            print(f"[seed] 向量化完成：更新 {updated} 行")
        else:
            updated = 0

        embedded = (
            await session.execute(text("SELECT COUNT(embedding) FROM market_data"))
        ).scalar_one()
        _print_summary(records, inserted=inserted, skipped=skipped, deleted=deleted,
                       existing_total=total, embedded_total=embedded, force=args.force, dry_run=False)
        if embedded != total:
            print(f"[seed] 警告：embedding 非空比例 {embedded}/{total} 未达 100%", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
