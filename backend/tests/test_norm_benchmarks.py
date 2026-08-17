"""norm 专业大类映射纯函数测试（不连真实 DB）。

覆盖：官方统计职业名/存量模板岗位名 → 11 大类映射、数据文件覆盖比例（标准 1）、
与 数据文件 category 标注一致性（标准 3）、兜底语义（标准 5）、歧义项归入（标准 6）。
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("TESTING", "true")

from app.ai.norm.benchmarks import ( # noqa: E402
    DEFAULT_MAJOR_CATEGORY,
    map_major_category,
)

DATA_PATH = BACKEND_DIR / "data" / "market_records_2026Q2.json"

# 存量 28 条：库内 market_data 超出数据文件的部分（2026-08-12 docker psql 核对）。
# 去重岗位 20 个；job_title 相同即映射结果相同，故按去重岗位断言等价于 28 条全量覆盖。
LEGACY_JOB_TITLES: list[str] = [
    "AI Agent应用开发工程师",
    "AI算法开发工程师",
    "ERP实施工程师",
    "Golang开发工程师",
    "Java后端工程师",
    "Java开发工程师",
    "Web前端研发工程师",
    "前端工程师",
    "前端开发工程师",
    "后端Golang工程师",
    "后端开发工程师",
    "大模型Agent应用开发工程师",
    "大模型应用开发工程师",
    "数据分析师",
    "测试开发工程师",
    "算法工程师",
    "软件实施工程师",
    "软件测试工程师",
    "软件运维工程师",
    "运维实施工程师",
]

# 官方统计职业名样例（采集，11 大类各取代表岗位）
OFFICIAL_STAT_SAMPLES: dict[str, str] = {
    "信息传输、软件和信息技术服务人员": "计算机类",
    "计算机软件工程技术人员": "计算机类",
    "信息系统运行维护工程技术人员": "计算机类",
    "网络与信息安全管理员": "计算机类",
    "金融服务人员": "经济金融类",
    "经济和金融专业人员": "经济金融类",
    "证券期货基金专业人员": "经济金融类",
    "行政办事及辅助人员": "工商管理类",
    "人力资源服务专业人员": "工商管理类",
    "商务专业人员": "工商管理类",
    "教学人员": "教育类",
    "机械工程技术人员": "机械类",
    "电气机械和器材制造人员": "电气类",
    "电力工程技术人员": "电气类",
    "建筑工程技术人员": "土木类",
    "卫生专业技术人员": "医学类",
    "内科医师": "医学类",
    "律师": "法学类",
    "视觉传达设计人员": "艺术设计类",
    "专业化设计服务人员": "艺术设计类",
    "文字编辑": "新闻传播类",
    "节目主持人": "新闻传播类",
}


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def test_legacy_job_titles_all_covered():
    """标准 1：存量 28 条（去重 20 岗位）全部落入 11 大类，无「其他」。"""
    uncovered = [t for t in LEGACY_JOB_TITLES if map_major_category(t) == DEFAULT_MAJOR_CATEGORY]
    assert not uncovered, f"存量岗位未覆盖：{uncovered}"


def test_data_file_coverage_rate_ge_95(records):
    """标准 1：数据文件 307 条 job_title 落入 11 大类比例 ≥95%。"""
    counts = Counter(map_major_category(r["job_title"]) for r in records)
    covered = sum(n for cat, n in counts.items() if cat != DEFAULT_MAJOR_CATEGORY)
    rate = covered / len(records)
    assert rate >= 0.95, (
        f"覆盖比例不足：{covered}/{len(records)} = {rate:.1%}；"
        f"归「其他」岗位：{[r['job_title'] for r in records if map_major_category(r['job_title']) == DEFAULT_MAJOR_CATEGORY][:20]}"
    )


def test_data_file_category_consistency_ge_90(records):
    """标准 3：映射结果与数据文件 category 标注一致性 ≥90%（快照对比）。"""
    diff = [
        (r["job_title"], r["category"], map_major_category(r["job_title"]))
        for r in records
        if r["category"] != map_major_category(r["job_title"])
    ]
    rate = 1 - len(diff) / len(records)
    assert rate >= 0.90, f"一致性不足：{rate:.1%}；差异 {len(diff)} 条"
    for title, expected, actual in sorted(set(diff)):
        print(f"[consistency-diff] {title} | 数据文件={expected} | map={actual}")


def test_official_stat_titles_mapped():
    """官方统计职业名 → 11 大类映射正确（含脏字符变体）。"""
    for title, expected in OFFICIAL_STAT_SAMPLES.items():
        assert map_major_category(title) == expected, f"{title} → {map_major_category(title)}，期望 {expected}"
    # 脏字符变体（采集源含 0x12 控制字符）
    assert map_major_category("信息传输\u0012软件和信息技术服务人员") == "计算机类"
    assert map_major_category("新闻出版\u0012文化专业人员") == "新闻传播类"
    assert map_major_category("证\u52f8期货基金专业人员") == "经济金融类"


def test_default_fallback_not_raise():
    """标准 5：None/空/未命中均兜底「其他」，不抛错。"""
    assert map_major_category(None) == DEFAULT_MAJOR_CATEGORY
    assert map_major_category("") == DEFAULT_MAJOR_CATEGORY
    assert map_major_category("星际探险家") == DEFAULT_MAJOR_CATEGORY


def test_ambiguous_titles_mapped_to_most_relevant():
    """标准 6：一词可归多类的岗位按最相关大类归入（依据见回报歧义项清单）。"""
    cases = {
        "产品经理": "工商管理类", # 数据文件基准；互联网产品岗位专业常模按工商管理
        "新媒体运营": "新闻传播类", # 数据文件基准；新媒体运营属传播岗位
        "广告设计师": "艺术设计类", # 字面「设计师」优先于行业「广告」
        "企业副总经理（含总设计师、总工程师、总工艺师等同级别人员）": "工商管理类", # 经营管理岗本质
        "药师": "医学类", # 药学属医学学科门类（数据文件标「其他」，见差异说明）
        "统计专业人员": "计算机类", # 数据文件基准（industry=软件/信息技术）
        "电气机械和器材制造人员": "电气类", # 电气机械词优先于泛「机械」
        "计算机程序设计员": "计算机类", # 程序设计词优先于泛「设计」
        "模具设计工程技术人员": "机械类",
        "建筑和市政设计工程技术人员": "土木类",
    }
    for title, expected in cases.items():
        got = map_major_category(title)
        assert got == expected, f"{title} → {got}，期望 {expected}"
