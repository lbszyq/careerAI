"""市场数据导入校验测试（纯函数，不连真实 DB）。

覆盖：数据文件完整性、字段合法性、幂等键唯一性、11 专业大类覆盖、
source_type/quarter/city_tier 约束、占位值剔除、_MAJOR_MAP 覆盖现状记录。
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("TESTING", "true")

from scripts.seed_market_data import (  # noqa: E402
    MAJOR_CATEGORIES,
    QUARTER_RE,
    VALID_CITY_TIERS,
    VALID_SOURCE_TYPES,
    build_backfill_plan,
    category_coverage_ok,
    dedup_key,
    default_data_path,
    insert_new_records,
    load_records,
    validate_record,
    validate_records,
)

DATA_PATH = default_data_path()


@pytest.fixture(scope="module")
def records():
    return load_records(DATA_PATH)


def test_data_file_exists_and_size(records):
    """标准 1：JSON 文件存在且条数在合理区间（存量 307 + 互联网新增，当前 332）。"""
    assert len(records) >= 330, f"JSON 记录数不足：{len(records)}（存量 307 + 互联网新增 ≥23）"
    assert len(records) <= 850 # 存量 307 + 互联网目标 500，留余量


def test_all_fields_valid(records):
    """标准 3：全量字段合法性（source_type/quarter/city_tier/占位值）。"""
    check = validate_records(records)
    assert check["errors"] == [], f"校验错误 {len(check['errors'])} 条：{check['errors'][:10]}"


def test_no_duplicate_dedup_keys(records):
    """标准 4：幂等键 (data_quarter, city, industry, job_title, data_source) 无重复。"""
    check = validate_records(records)
    assert check["duplicates"] == [], f"重复幂等键：{check['duplicates'][:10]}"


def test_source_type_restriction(records):
    """标准 3：source_type ∈ {official_stat, job_post}，禁止 ai_infer。"""
    types = {r["source_type"] for r in records}
    assert types <= VALID_SOURCE_TYPES, f"非法 source_type：{types - VALID_SOURCE_TYPES}"
    assert "ai_infer" not in types


def test_quarter_uniform(records):
    """标准 3：data_quarter 统一为 YYYYQn。"""
    quarters = {r["data_quarter"] for r in records}
    assert all(QUARTER_RE.match(q) for q in quarters), f"非法 data_quarter：{quarters}"
    assert quarters == {"2026Q2"}, f"data_quarter 不统一：{quarters}"


def test_city_tier_valid(records):
    """标准 3：city_tier 全合法。"""
    tiers = {r["city_tier"] for r in records}
    assert tiers <= VALID_CITY_TIERS, f"非法 city_tier：{tiers - VALID_CITY_TIERS}"


def test_no_placeholder_values(records):
    """标准 3：不存在「未明确」行业/「全国」城市/占位岗位。"""
    bad_industry = [r for r in records if "未明确" in (r.get("industry") or "")]
    bad_city = [r for r in records if r.get("city") in ("全国", "未知", "暂无")]
    bad_title = [r for r in records if (r.get("job_title") or "").strip() in ("未明确", "暂无", "未知")]
    assert not bad_industry, f"含「未明确」行业：{bad_industry[:5]}"
    assert not bad_city, f"含占位城市：{bad_city[:5]}"
    assert not bad_title, f"含占位岗位：{bad_title[:5]}"


def test_major_coverage_each_category(records):
    """标准 2：11 个专业大类每类 ≥20（按数据文件 category 字段核对）。"""
    missing = category_coverage_ok(records, minimum=20)
    assert not missing, f"专业大类覆盖不足：{missing}"


def test_salary_is_monthly_yuan(records):
    """薪资为元/月（正数或 null；仅 3 条川渝来源只有中位数 p25/p75 为 null）。"""
    for r in records:
        for key in ("salary_p25", "salary_p50", "salary_p75"):
            val = r.get(key)
            if val is not None:
                assert val > 0, f"{r['job_title']}@{r['city']} {key}={val} 非正数"
    # 全量至少有一个薪资分位
    no_salary = [r for r in records if all(r.get(k) is None for k in ("salary_p25", "salary_p50", "salary_p75"))]
    assert not no_salary, f"无任何薪资分位的记录：{no_salary[:5]}"


def test_data_source_not_empty(records):
    """标准 1：全部记录 data_source 非空且为真实来源名。"""
    empty = [r for r in records if not (r.get("data_source") or "").strip()]
    assert not empty, "存在空 data_source 记录"


def test_major_map_coverage_snapshot(records):
    """norm 映射修复后快照（硬断言）：
    - 标准 1：数据文件 307 条 job_title 经 map_major_category 落入 11 大类 ≥95%
    - 标准 3：映射结果与数据文件 category 标注一致性 ≥90%
    映射实现见 app/ai/norm/benchmarks._MAJOR_MAP（基于 job_title 关键词，不依赖 category 字段）。
    """
    from collections import Counter

    from app.ai.norm.benchmarks import DEFAULT_MAJOR_CATEGORY, map_major_category

    counts = Counter(map_major_category(r["job_title"]) for r in records)
    covered = sum(n for cat, n in counts.items() if cat != DEFAULT_MAJOR_CATEGORY)
    rate = covered / len(records)
    for cat in MAJOR_CATEGORIES:
        print(f"[snapshot] _MAJOR_MAP {cat}: {counts.get(cat, 0)} 条")
    print(f"[snapshot] 其他: {counts.get(DEFAULT_MAJOR_CATEGORY, 0)} 条")
    assert rate >= 0.95, f"覆盖比例不足：{covered}/{len(records)} = {rate:.1%}"
    diff = [r["job_title"] for r in records if r["category"] != map_major_category(r["job_title"])]
    consistency = 1 - len(diff) / len(records)
    assert consistency >= 0.90, (
        f"与数据文件 category 一致性不足：{consistency:.1%}（差异 {len(diff)} 条：{sorted(set(diff))[:10]}）"
    )


def test_dedup_key_logic():
    """幂等键逻辑：五元组任一不同则键不同；相同则键相同。"""
    base = {
        "data_quarter": "2026Q2", "city": "北京", "industry": "互联网",
        "job_title": "后端开发工程师", "data_source": "测试来源",
    }
    same = dict(base)
    assert dedup_key(base) == dedup_key(same)
    for field in ("city", "industry", "job_title", "data_source", "data_quarter"):
        changed = dict(base)
        changed[field] = "不同值"
        assert dedup_key(base) != dedup_key(changed), f"字段 {field} 未参与幂等键"


def test_validate_record_rejects_bad_source_type():
    errs = validate_record({
        "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
        "data_quarter": "2026Q2", "city_tier": "一线",
        "source_type": "ai_infer", "data_source": "测试来源",
    })
    assert any("source_type" in e for e in errs), errs


def test_validate_record_rejects_bad_quarter_and_placeholder():
    errs = validate_record({
        "city": "全国", "industry": "未明确", "job_title": "未知",
        "data_quarter": "2026", "city_tier": "超一线",
        "source_type": "official_stat", "data_source": "测试来源",
    })
    joined = " | ".join(errs)
    assert "全国" in joined and "未明确" in joined and "data_quarter" in joined and "city_tier" in joined

# ============ ：source_type 回填与列落地 ============


def test_market_model_has_source_type_column():
    """标准 1：MarketData 模型含 source_type 列（迁移后 schema 与 ORM 对齐）。"""
    from app.models.market import MarketData

    col = MarketData.__table__.columns.get("source_type")
    assert col is not None, "MarketData 缺 source_type 列"


def test_market_model_has_education_responsibilities_columns():
    """标准 1：MarketData 模型含 education_requirement / responsibilities 两列。"""
    from app.models.market import MarketData

    edu = MarketData.__table__.columns.get("education_requirement")
    resp = MarketData.__table__.columns.get("responsibilities")
    assert edu is not None, "MarketData 缺 education_requirement 列"
    assert resp is not None, "MarketData 缺 responsibilities 列"
    assert edu.nullable and resp.nullable, "两列应为 nullable"


def test_backfill_plan_matches_json_source_type():
    """标准 1：按幂等键匹配 JSON 的记录回填 JSON 的 source_type。"""
    records = [{
        "data_quarter": "2026Q2", "city": "北京", "industry": "互联网",
        "job_title": "后端开发工程师", "data_source": "官方来源", "source_type": "official_stat",
    }]
    rows = [("r1", "2026Q2", "北京", "互联网", "后端开发工程师", "官方来源")]
    updates, unmatched = build_backfill_plan(records, rows)
    assert [(u.id, u.source_type) for u in updates] == [("r1", "official_stat")]
    assert unmatched == []


def test_backfill_plan_tc033_job_post():
    """标准 7：存量 legacy-jd 记录默认 job_post。"""
    rows = [("r1", "2026Q2", "上海", "金融", "分析师", "legacy-jd-示例JD")]
    updates, unmatched = build_backfill_plan([], rows)
    assert [(u.id, u.source_type) for u in updates] == [("r1", "job_post")]
    assert unmatched == []


def test_backfill_plan_unmatched_not_silent():
    """标准 6：无法匹配的记录进 unmatched 列表，禁止静默置空/猜测赋值。"""
    rows = [("r1", "2026Q2", "上海", "金融", "分析师", "无法匹配的来源")]
    updates, unmatched = build_backfill_plan([], rows)
    assert updates == []
    assert len(unmatched) == 1
    assert unmatched[0].id == "r1"
    assert unmatched[0].key == ("2026Q2", "上海", "金融", "分析师", "无法匹配的来源")


def test_backfill_plan_idempotent():
    """标准 3：相同输入重复构建回填计划结果不变（DB 侧 UPDATE 亦按值比较跳过）。"""
    records = [
        {"data_quarter": "2026Q2", "city": "北京", "industry": "互联网",
         "job_title": "后端开发工程师", "data_source": "A来源", "source_type": "official_stat"},
        {"data_quarter": "2026Q2", "city": "深圳", "industry": "互联网",
         "job_title": "前端开发工程师", "data_source": "B来源", "source_type": "job_post"},
    ]
    rows = [
        ("r1", "2026Q2", "北京", "互联网", "后端开发工程师", "A来源"),
        ("r2", "2026Q2", "深圳", "互联网", "前端开发工程师", "B来源"),
        ("r3", "2026Q2", "杭州", "电商", "运营", "legacy-jd-x"),
    ]
    first = build_backfill_plan(records, rows)
    second = build_backfill_plan(records, rows)
    assert first == second, "回填计划应确定性/幂等"
    assert {u.id: u.source_type for u in first[0]} == {"r1": "official_stat", "r2": "job_post", "r3": "job_post"}


def test_backfill_plan_uses_json_source_type_not_guess():
    """标准 1/6：JSON 中 job_post 记录不得被猜测为 official_stat（严格取 JSON 值）。"""
    records = [{
        "data_quarter": "2026Q2", "city": "广州", "industry": "互联网",
        "job_title": "产品经理", "data_source": "招聘平台JD聚合", "source_type": "job_post",
    }]
    rows = [("r1", "2026Q2", "广州", "互联网", "产品经理", "招聘平台JD聚合")]
    updates, _unmatched = build_backfill_plan(records, rows)
    assert [(u.id, u.source_type) for u in updates] == [("r1", "job_post")]


def test_insert_new_records_writes_optional_columns_when_present():
    """标准 1/5：三可选列（source_type/education_requirement/responsibilities）均存在 → ORM 直接写入。"""
    import asyncio
    from unittest.mock import AsyncMock

    from app.db.base import AsyncSession

    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    rec = {
        "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
        "salary_p50": 20000, "data_source": "招聘平台JD-示例", "confidence": 0.7,
        "data_quarter": "2026Q2", "city_tier": "一线", "source_type": "job_post",
        "education_requirement": "本科及以上",
        "responsibilities": ["负责后端服务开发", "参与系统架构设计"],
    }
    inserted, skipped = asyncio.run(insert_new_records(
        session, [rec],
        columns={"source_type", "education_requirement", "responsibilities"},
    ))
    assert (inserted, skipped) == (1, 0)
    added = session.add.call_args[0][0]
    assert added.source_type == "job_post"
    assert added.education_requirement == "本科及以上"
    assert added.responsibilities == ["负责后端服务开发", "参与系统架构设计"]


def test_insert_new_records_skips_optional_columns_without_column():
    """标准 8：旧库（三可选列均无）降级：Core INSERT 显式列清单，SQL 不含三可选列。"""
    import asyncio
    from unittest.mock import AsyncMock

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.dml import Insert

    from app.db.base import AsyncSession

    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    rec = {
        "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
        "salary_p50": 20000, "data_source": "招聘平台JD-示例", "confidence": 0.7,
        "data_quarter": "2026Q2", "city_tier": "一线", "source_type": "job_post",
        "education_requirement": "本科及以上",
        "responsibilities": ["负责后端服务开发"],
    }
    inserted, skipped = asyncio.run(insert_new_records(session, [rec], columns=set()))
    assert (inserted, skipped) == (1, 0)
    # 无列库必须走 Core INSERT（显式列清单），不得走 ORM 全列 INSERT（会带可选列报 UndefinedColumn）
    assert session.add.call_count == 0, "无列库不应走 ORM session.add"
    insert_calls = [
        c.args[0] for c in session.execute.call_args_list if isinstance(c.args[0], Insert)
    ]
    assert insert_calls, "应存在 Core INSERT 语句"
    sql = str(insert_calls[-1].compile(dialect=postgresql.dialect()))
    assert "source_type" not in sql, f"Core INSERT 不应包含 source_type 列：{sql}"
    assert "education_requirement" not in sql, f"Core INSERT 不应包含 education_requirement 列：{sql}"
    assert "responsibilities" not in sql, f"Core INSERT 不应包含 responsibilities 列：{sql}"
    assert "market_data" in sql


def test_insert_new_records_partial_columns_uses_core_insert():
    """标准 8：source_type 有列但 education/responsibilities 未落地 → Core INSERT 只写 source_type。"""
    import asyncio
    from unittest.mock import AsyncMock

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.dml import Insert

    from app.db.base import AsyncSession

    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    rec = {
        "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
        "salary_p50": 20000, "data_source": "招聘平台JD-示例", "confidence": 0.7,
        "data_quarter": "2026Q2", "city_tier": "一线", "source_type": "job_post",
        "education_requirement": "本科及以上",
        "responsibilities": ["负责后端服务开发"],
    }
    inserted, skipped = asyncio.run(insert_new_records(session, [rec], columns={"source_type"}))
    assert (inserted, skipped) == (1, 0)
    # 部分可选列缺失 → 必须走 Core INSERT（显式列清单），不得走 ORM（会带缺失列报 UndefinedColumn）
    assert session.add.call_count == 0, "部分可选列缺失时不应走 ORM session.add"
    insert_calls = [
        c.args[0] for c in session.execute.call_args_list if isinstance(c.args[0], Insert)
    ]
    assert insert_calls, "应存在 Core INSERT 语句"
    sql = str(insert_calls[-1].compile(dialect=postgresql.dialect()))
    assert "source_type" in sql, f"Core INSERT 应包含 source_type 列：{sql}"
    assert "education_requirement" not in sql, f"Core INSERT 不应包含 education_requirement 列：{sql}"
    assert "responsibilities" not in sql, f"Core INSERT 不应包含 responsibilities 列：{sql}"


# ============ ：education_requirement / responsibilities 字段校验与 RAG 注入 ============


def test_validate_record_rejects_bad_education():
    """标准 5：education_requirement 值域非法（非 不限/大专/本科/硕士/博士 及其「及以上」）。"""
    for bad in ("研究生", "本科以上", "", "博士及以上", "不限及以上", "高中"):
        errs = validate_record({
            "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
            "data_quarter": "2026Q2", "city_tier": "一线",
            "source_type": "job_post", "data_source": "测试来源",
            "education_requirement": bad,
        })
        assert any("education_requirement" in e for e in errs), (bad, errs)


def test_validate_record_accepts_education_variants():
    """标准 5：education_requirement 合法值域全部通过。"""
    for edu in (None, "不限", "大专", "本科", "硕士", "博士", "大专及以上", "本科及以上", "硕士及以上"):
        errs = validate_record({
            "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
            "data_quarter": "2026Q2", "city_tier": "一线",
            "source_type": "job_post", "data_source": "测试来源",
            "education_requirement": edu,
        })
        assert not any("education_requirement" in e for e in errs), (edu, errs)


def test_validate_record_rejects_bad_responsibilities():
    """标准 5：responsibilities 必须为字符串数组（元素非空字符串）。"""
    errs = validate_record({
        "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
        "data_quarter": "2026Q2", "city_tier": "一线",
        "source_type": "job_post", "data_source": "测试来源",
        "responsibilities": ["负责开发", 123],
    })
    assert any("responsibilities" in e for e in errs), errs
    errs2 = validate_record({
        "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
        "data_quarter": "2026Q2", "city_tier": "一线",
        "source_type": "job_post", "data_source": "测试来源",
        "responsibilities": "负责开发",
    })
    assert any("responsibilities" in e for e in errs2), errs2
    errs3 = validate_record({
        "city": "北京", "industry": "互联网", "job_title": "后端开发工程师",
        "data_quarter": "2026Q2", "city_tier": "一线",
        "source_type": "job_post", "data_source": "测试来源",
        "responsibilities": ["负责开发", ""],
    })
    assert any("responsibilities" in e for e in errs3), errs3


def _mk_hit(**overrides):
    """构造 MarketHit（补齐必需字段，学历/职责可用 override 覆盖）。"""
    from app.ai.rag.retriever import MarketHit

    base = dict(
        id="t1", city="北京", industry="互联网", job_title="后端开发工程师",
        salary_p25=15000, salary_p50=20000, salary_p75=25000, trend="稳定", heat="高",
        required_skills=["Java", "MySQL"], data_source="招聘平台JD", confidence=0.7,
        data_quarter="2026Q2", city_tier="一线", similarity=0.85, source_type="job_post",
        education_requirement="本科及以上",
        responsibilities=["负责后端服务开发", "参与系统架构设计"],
    )
    base.update(overrides)
    return MarketHit(**base)


def test_to_context_block_contains_education_responsibilities():
    """标准 5：RAG 注入——to_context_block() 输出含学历/职责。"""
    block = _mk_hit().to_context_block()
    assert "本科及以上" in block, block
    assert "负责后端服务开发" in block, block
    assert "参与系统架构设计" in block, block
    assert "学历要求" in block and "职责" in block, block


def test_to_context_block_missing_education_responsibilities_not_fabricated():
    """标准 5：命中无学历/职责（存量/官方统计）时标注缺失，不编造。"""
    block = _mk_hit(education_requirement=None, responsibilities=[]).to_context_block()
    assert "暂无学历要求" in block, block
    assert "暂无职责说明" in block, block


def test_jd_summary_from_hits_fills_education_responsibilities():
    """标准 5：RAG 注入——_jd_summary_from_hits 返回的 jd_summary 不再恒置 None/[]。"""
    from app.ai.agents.market import _jd_summary_from_hits

    summary = _jd_summary_from_hits([_mk_hit()], "后端开发工程师")
    assert summary["education_requirement"] == "本科及以上"
    assert summary["responsibilities"] == ["负责后端服务开发", "参与系统架构设计"]


def test_jd_summary_from_hits_empty_pool_still_placeholder():
    """标准 5：无命中时学历/职责保持 None/[]（宁缺毋滥，不编造）。"""
    from app.ai.agents.market import _jd_summary_from_hits

    summary = _jd_summary_from_hits([], "后端开发工程师")
    assert summary["education_requirement"] is None
    assert summary["responsibilities"] == []


def test_jd_summary_from_direction_fills_education_responsibilities():
    """标准 5：RAG 注入——_jd_summary_from_direction 学历/职责以命中记录补充（不再恒置 None/[]）。"""
    from app.ai.agents.market import _jd_summary_from_direction

    direction = {
        "job_title": "后端开发工程师",
        "salary": {"p25": 15000, "p50": 20000, "p75": 25000},
        "trend": "稳定", "heat": "高",
        "data_source": "招聘平台JD", "data_grade": "B",
        "education_requirement": None, # LLM 未给学历 → 回落命中
    }
    summary = _jd_summary_from_direction(
        direction, "后端开发工程师",
        [{"name": "Java", "required_level": "core"}],
        hits=[_mk_hit()],
    )
    assert summary["education_requirement"] == "本科及以上"
    assert summary["responsibilities"] == ["负责后端服务开发", "参与系统架构设计"]


# ============ ：互联网行业岗位数据完整性 ============


def _new_internet_records(records):
    """新增互联网记录（source_batch 标记；存量记录无该字段/无学历字段）。"""
    return [r for r in records if r.get("source_batch") == "internet-job"]


def test_internet_job_data_added(records):
    """标准 2：新增互联网行业岗位数据，覆盖后端/前端/算法/数据/测试/运维/产品/设计/运营/架构等家族。"""
    new = _new_internet_records(records)
    assert len(new) >= 20, f"互联网新增记录不足：{len(new)}"
    titles = " ".join(r["job_title"] for r in new)
    for family in ("后端", "前端", "算法", "数据", "测试", "运维", "产品", "设计", "运营", "架构"):
        assert family in titles, f"缺少岗位家族：{family}"
    industries = {r["industry"] for r in new}
    assert industries <= {"软件/信息技术", "人工智能", "互联网/软件", "金融科技", "信息安全", "游戏/互联网", "电子商务"}, industries


def test_new_internet_job_post_ratio(records):
    """标准 4：新增记录 job_post 占比 ≥70%（核心目标——真实 JD 技能不落空）。"""
    new = _new_internet_records(records)
    assert new, "无新增互联网记录"
    job_post = [r for r in new if r["source_type"] == "job_post"]
    assert len(job_post) / len(new) >= 0.7, f"job_post 占比不足：{len(job_post)}/{len(new)}"


def test_new_job_post_skills_nonempty_ratio(records):
    """标准 4：新增 job_post 记录 required_skills 非空比例 ≥90%。"""
    new = _new_internet_records(records)
    job_post = [r for r in new if r["source_type"] == "job_post"]
    nonempty = [r for r in job_post if r.get("required_skills")]
    assert len(nonempty) / len(job_post) >= 0.9, f"技能非空比例不足：{len(nonempty)}/{len(job_post)}"


def test_new_job_post_education_ratio(records):
    """标准 5：新增 job_post 记录 education_requirement 非空比例 ≥80%。"""
    new = _new_internet_records(records)
    job_post = [r for r in new if r["source_type"] == "job_post"]
    nonempty = [r for r in job_post if r.get("education_requirement")]
    assert len(nonempty) / len(job_post) >= 0.8, f"学历非空比例不足：{len(nonempty)}/{len(job_post)}"


def test_new_job_post_responsibilities_ratio(records):
    """标准 5：新增 job_post 记录 responsibilities 非空比例 ≥80%（职责为字符串数组）。"""
    new = _new_internet_records(records)
    job_post = [r for r in new if r["source_type"] == "job_post"]
    nonempty = [r for r in job_post if r.get("responsibilities")]
    assert len(nonempty) / len(job_post) >= 0.8, f"职责非空比例不足：{len(nonempty)}/{len(job_post)}"
