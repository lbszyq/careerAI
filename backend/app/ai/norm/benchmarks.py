"""常模基准（B-002）：norm_benchmarks 查询 + 聚合逻辑。

- 表由 迁移创建（architecture.md 增量 3），本模块代码先行：
  表/列不存在 → 返回 None（降级「样本不足」，不输出精确分位，C-009）。
- 聚合：从 market_data 按「城市等级 × 专业大类」分组计算薪资分位，写入 norm_benchmarks。
- 专业大类映射：岗位→专业大类 近似映射（B-002 方案），本地版本 内置常用映射，缺省「其他」。
"""
import logging
import statistics
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("careerai.ai.norm")

NORM_MIN_SAMPLE = 30 # 单元样本 <30 降级「样本不足」（C-009 / ，理想 ≥100）


@dataclass
class NormBenchmark:
    graduation_year: int | None
    city_tier: str | None
    major_category: str | None
    sample_size: int
    p25: float | None
    p50: float | None
    p75: float | None
    contains_employed: bool | None
    confidence: str | None
    data_quarter: str | None

    @property
    def insufficient_sample(self) -> bool:
        return self.sample_size < NORM_MIN_SAMPLE

    def to_dict(self, *, cohort: str) -> dict | None:
        """常模载荷（reports-contract v1.1；诚实下线语义）。

        - **隐藏语义（唯一形态）**：样本不足（<30，C-009）→ 返回 **None**——
          调用方将 norm 载荷整体置 None（scores.norm / norm_benchmark / portrait.norm
          均为 None），**不再输出 band=None+sample_size=12 的降级载荷**（审计：
          旧降级载荷会让前端渲染「当前样本量不足」占位文案，本身即不诚实）。
        - **≥30 防删分支**：有真实常模数据时正常输出（含 p25/p50/p75 等真实字段）。
          band 恒为 None——band 的真实语义（画像得分 vs 常模分布分位）由真重建 Backlog
          定义，本任务不输出任何占位/恒定 band 值（：旧死代码恒「中 50%」）。
        - disclaimer：固定免责文案（该指数用于能力画像参考，不代表实际就业概率）；
        - confidence_reasons：supporting/concerns 确定性组装（仅引用样本口径数据）；
        - 口径：当前 本地版本 样本量约 120、可靠等级中等，不保留「≥1000」表述。
        """
        if self.insufficient_sample:
            return None
        return {
            "matched": True,
            "cohort": cohort,
            "band": None, # band 真实语义由真重建 Backlog 定义，不输出占位/恒定值
            "sample_size": self.sample_size,
            "p25": self.p25,
            "p50": self.p50,
            "p75": self.p75,
            "contains_employed": self.contains_employed,
            "confidence": self.confidence or "中",
            "note": "常模样本可能含在职人员，应届生起薪通常低于市场均值" if self.contains_employed else None,
            "disclaimer": _DISCLAIMER,
            "confidence_reasons": _norm_confidence_reasons(self, cohort),
        }

# 岗位 → 专业大类 近似映射（B-002 本地版本 口径，缺省「其他」；扩充官方统计职业名与存量模板岗位名）
# 顺序即匹配优先级：先精确词（避免「设计」「机械」等泛词误伤），后泛化词。
_MAJOR_MAP: dict[str, str] = {
    # —— 计算机类（软件开发/工程岗 + 官方统计职业名）——
    "软件开发": "计算机类", "后端开发": "计算机类", "前端开发": "计算机类",
    "算法工程师": "计算机类", "数据分析": "计算机类", "数据挖掘": "计算机类",
    "测试开发": "计算机类", "网络安全": "计算机类",
    "开发工程师": "计算机类", "程序设计": "计算机类", "软件": "计算机类",
    "信息系统": "计算机类", "信息通信": "计算机类", "信息安全": "计算机类",
    "信息技术": "计算机类", "机器学习": "计算机类", "运维": "计算机类",
    "运行维护": "计算机类", "统计专业人员": "计算机类", "统计调查员": "计算机类",
    "后端": "计算机类", "前端": "计算机类", "实施工程师": "计算机类",
    # —— 经济金融类 ——
    "会计": "经济金融类", "财务": "经济金融类", "银行": "经济金融类",
    "证券": "经济金融类", "风控": "经济金融类", "投资": "经济金融类",
    "审计": "经济金融类", "金融": "经济金融类", "经济": "经济金融类",
    "保险": "经济金融类", "期货": "经济金融类", "信贷": "经济金融类", "柜员": "经济金融类",
    # —— 新闻传播类（「新媒体」前置，先于工商管理类「运营」，新媒体运营归传播岗）——
    "新媒体": "新闻传播类",
    # —— 工商管理类 ——
    "市场营销": "工商管理类", "人力资源": "工商管理类", "运营": "工商管理类",
    "销售": "工商管理类", "营销": "工商管理类", "市场": "工商管理类",
    "行政": "工商管理类", "商务": "工商管理类", "人事": "工商管理类",
    "负责人": "工商管理类", "经理": "工商管理类", "产品经理": "工商管理类",
    # —— 教育类 ——
    "教师": "教育类", "教学": "教育类", "教育学": "教育类",
    # —— 机械类（「电气机械」前置避免「机械」抢先）——
    "电气机械": "电气类",
    "机械": "机械类", "模具": "机械类", "金属加工": "机械类",
    "工程机械": "机械类", "泵、阀门": "机械类",
    # —— 电气类 ——
    "电气": "电气类", "电力": "电气类", "电线电缆": "电气类",
    "电机": "电气类", "输配电": "电气类", "电工": "电气类",
    # —— 土木类（「建筑」前置避免「设计」误伤）——
    "土木工程": "土木类", "建筑": "土木类", "监理": "土木类",
    "造价": "土木类", "勘察": "土木类", "桥隧": "土木类", "岩土": "土木类", "市政": "土木类",
    # —— 医学类（药师/药学属医学学科门类，数据文件标「其他」见回报差异说明）——
    "临床": "医学类", "护士": "医学类", "医师": "医学类",
    "护理": "医学类", "卫生": "医学类", "医疗": "医学类",
    "药学": "医学类", "药师": "医学类", "检验": "医学类",
    # —— 法学类 ——
    "法律": "法学类", "律师": "法学类",
    # —— 艺术设计类（精确词收窄，不再用裸「设计」防误伤程序设计/建筑设计）——
    "设计师": "艺术设计类", "设计人员": "艺术设计类",
    "设计工程技术人员": "艺术设计类", "设计服务": "艺术设计类",
    "视觉传达": "艺术设计类", "装潢": "艺术设计类", "工艺美术": "艺术设计类",
    # —— 新闻传播类 ——
    "编辑": "新闻传播类", "记者": "新闻传播类", "主持人": "新闻传播类",
    "播音": "新闻传播类", "新闻": "新闻传播类", "出版": "新闻传播类", "剪辑": "新闻传播类",
}

DEFAULT_MAJOR_CATEGORY = "其他"

# 专业名词根 → 专业大类：_MAJOR_MAP 是「岗位名关键词 → 大类」，对「计算机科学与技术」
# 「数据科学与大数据技术」「法学」「人工智能」等纯专业名会落「其他」（岗位名关键词不含这些词根）；
# 此处补充专业名词根映射，供 Stage1 方向推荐把 profile.major 反查到专业大类（只读补充，不改 _MAJOR_MAP）。
_MAJOR_NAME_KEYWORDS: dict[str, str] = {
    "计算机": "计算机类", "数据科学": "计算机类", "大数据": "计算机类",
    "人工智能": "计算机类", "智能科学": "计算机类", "物联网": "计算机类",
    "法学": "法学类",
    "通信": "电气类", "电子": "电气类", "自动化": "电气类",
    "广告": "新闻传播类", "传媒": "新闻传播类",
    "教育": "教育类", "师范": "教育类",
    "美术": "艺术设计类", "数字媒体": "艺术设计类",
    "医学": "医学类",
}


def map_major_category(job_title: str | None) -> str:
    if not job_title:
        return DEFAULT_MAJOR_CATEGORY
    for keyword, category in _MAJOR_MAP.items():
        if keyword in job_title:
            return category
    return DEFAULT_MAJOR_CATEGORY


def map_major_to_category(major: str | None) -> str:
    """专业名 → 专业大类：先 _MAJOR_MAP 关键词匹配，再 _MAJOR_NAME_KEYWORDS 专业名词根兜底。

    map_major_category 按「岗位名关键词」匹配，对「计算机科学与技术」等纯专业名会落「其他」；
    此处补充专业名词根映射，使 Stage1 方向推荐能据此从数据库 job_title 按大类筛选岗位名。
    """
    category = map_major_category(major)
    if category != DEFAULT_MAJOR_CATEGORY or not major:
        return category
    for keyword, category in _MAJOR_NAME_KEYWORDS.items():
        if keyword in major:
            return category
    return DEFAULT_MAJOR_CATEGORY


async def _has_table(session: AsyncSession, table: str) -> bool:
    stmt = text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = :t"
    )
    rows = await session.execute(stmt, {"t": table})
    return rows.first() is not None


async def _table_columns(session: AsyncSession, table: str) -> set[str]:
    stmt = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = :t"
    )
    rows = await session.execute(stmt, {"t": table})
    return {r[0] for r in rows}


_EXPECTED = {
    "graduation_year", "city_tier", "major_category", "sample_size",
    "salary_p25", "salary_p50", "salary_p75", "contains_employed",
    "confidence", "data_quarter",
}


async def lookup_norm_benchmark(
    session: AsyncSession,
    *,
    graduation_year: int | None,
    city_tier: str | None,
    major_category: str | None,
) -> NormBenchmark | None:
    """查询常模命中单元；表/列缺失或无匹配 → None（调用方降级「样本不足」）。"""
    if not await _has_table(session, "norm_benchmarks"):
        return None
    columns = await _table_columns(session, "norm_benchmarks")
    missing = _EXPECTED - columns
    if missing:
        logger.warning("norm: norm_benchmarks 缺列 %s，降级 None", sorted(missing))
        return None
    stmt = text(
        "SELECT graduation_year, city_tier, major_category, sample_size, "
        "salary_p25, salary_p50, salary_p75, contains_employed, confidence, data_quarter "
        "FROM norm_benchmarks "
        "WHERE graduation_year = :y AND city_tier = :t AND major_category = :m "
        "ORDER BY data_quarter DESC NULLS LAST LIMIT 1"
    )
    try:
        rows = await session.execute(
            stmt,
            {
                "y": graduation_year,
                "t": city_tier or "其他",
                "m": major_category or DEFAULT_MAJOR_CATEGORY,
            },
        )
    except Exception as exc: # noqa: BLE001 结构未就绪
        logger.warning("norm: 查询失败降级 None: %s", type(exc).__name__)
        return None
    row = rows.first()
    if row is None:
        return None
    return NormBenchmark(
        graduation_year=row.graduation_year,
        city_tier=row.city_tier,
        major_category=row.major_category,
        sample_size=int(row.sample_size or 0),
        p25=float(row.salary_p25) if row.salary_p25 is not None else None,
        p50=float(row.salary_p50) if row.salary_p50 is not None else None,
        p75=float(row.salary_p75) if row.salary_p75 is not None else None,
        contains_employed=bool(row.contains_employed) if row.contains_employed is not None else None,
        confidence=row.confidence,
        data_quarter=row.data_quarter,
    )


async def aggregate_norm_benchmarks(
    session: AsyncSession,
    *,
    graduation_year: int | None = None,
) -> int:
    """聚合管道（代码先行，运行时依赖 表结构）。

    从 market_data 按「城市等级 × 专业大类」分组，以 salary_p50 计算 P25/P50/P75
    分位阈值，upsert 到 norm_benchmarks。返回写入/更新的单元数；
    表或所需列缺失时返回 0（不崩溃，由数据管道在迁移落地后调度）。
    """
    if not await _has_table(session, "norm_benchmarks"):
        logger.info("norm: norm_benchmarks 表不存在，聚合跳过")
        return 0
    mkt_cols = await _table_columns(session, "market_data")
    nb_cols = await _table_columns(session, "norm_benchmarks")
    need_mkt = {"city_tier", "industry", "job_title", "salary_p50"}
    if not need_mkt <= mkt_cols:
        logger.warning("norm: market_data 缺列（%s），聚合跳过", sorted(need_mkt - mkt_cols))
        return 0
    if not _EXPECTED <= nb_cols:
        logger.warning("norm: norm_benchmarks 缺列，聚合跳过")
        return 0

    stmt = text(
        "SELECT city_tier, industry, job_title, salary_p50, data_quarter FROM market_data "
        "WHERE salary_p50 IS NOT NULL"
    )
    rows = await session.execute(stmt)
    groups: dict[tuple[str, str], list[float]] = {}
    quarters: dict[tuple[str, str], str | None] = {}
    for row in rows:
        tier = row.city_tier or "其他"
        category = map_major_category(row.job_title or "") or map_major_category(row.industry or "")
        key = (tier, category)
        groups.setdefault(key, []).append(float(row.salary_p50))
        q = row.data_quarter
        if q and (quarters.get(key) is None or q > quarters[key]):
            quarters[key] = q

    updated = 0
    for (tier, category), salaries in groups.items():
        data_quarter = quarters.get((tier, category))
        if data_quarter is None:
            # data_quarter NOT NULL（）：无季度数据不编造，跳过该单元
            logger.warning("norm: 单元 %s×%s 无 data_quarter，跳过", tier, category)
            continue
        if len(salaries) < NORM_MIN_SAMPLE:
            # 样本不足仍记录单元（sample_size 供查询端降级），不输出分位
            p25 = p50 = p75 = None
        else:
            p25, p50, p75 = statistics.quantiles(salaries, n=4, method="inclusive")
        upsert = text(
            "INSERT INTO norm_benchmarks "
            "(id, graduation_year, city_tier, major_category, sample_size, "
            "salary_p25, salary_p50, salary_p75, contains_employed, data_quarter, "
            "created_at, updated_at) "
            "VALUES (:id, :y, :t, :m, :n, :p25, :p50, :p75, false, :dq, now(), now()) "
            "ON CONFLICT (graduation_year, city_tier, major_category, data_quarter) "
            "DO UPDATE SET sample_size = EXCLUDED.sample_size, "
            "salary_p25 = EXCLUDED.salary_p25, salary_p50 = EXCLUDED.salary_p50, "
            "salary_p75 = EXCLUDED.salary_p75, updated_at = now()"
        )
        await session.execute(
            upsert,
            {
                "id": uuid.uuid4(),
                "y": graduation_year,
                "t": tier,
                "m": category,
                "n": len(salaries),
                "p25": p25,
                "p50": p50,
                "p75": p75,
                "dq": data_quarter,
            },
        )
        updated += 1
    logger.info("norm: 聚合完成，更新 %d 个单元", updated)
    return updated




_DISCLAIMER = "该指数用于能力画像参考，不代表实际就业概率"


def _norm_confidence_reasons(norm: "NormBenchmark", cohort: str) -> dict:
    """常模置信度原因拆解（确定性组装，仅引用样本口径已有数据，禁止编造）。"""
    supporting = [f"样本与用户专业/城市等级匹配（{cohort}）"]
    concerns: list[str] = []
    if not norm.insufficient_sample:
        supporting.append(f"样本量为 {norm.sample_size}，达到中等可靠等级")
    if norm.contains_employed:
        concerns.append("样本含在职人员，应届生起薪通常低于市场均值")
    if norm.insufficient_sample:
        concerns.append("样本量未达高可靠阈值，参考价值有限")
    else:
        concerns.append("常模样本为预置基准，与个体实际情况可能存在偏差")
    return {"supporting": supporting, "concerns": concerns}


def normalize_norm_payload(norm: dict | None) -> dict | None:
    """v1.1：LLM/上游 norm 载荷归一化补全（LLM 路径恒含 v1.1 字段）。

    - disclaimer：固定免责文案（覆盖 LLM 自写措辞，禁止 LLM 编造/改写）。
    - confidence_reasons：缺失或非法时按载荷已有字段确定性组装（禁止凭空建议）；
      已含 supporting/concerns 时保留上游输出（保真，不覆盖）。
    - 空/非 dict 原样返回（无常模数据时不伪造 norm 对象）。

    ⚠️ 接地 seam：本函数**只补文案字段**（disclaimer/confidence_reasons），
    **不校验/不修改事实字段**（band/sample_size/cohort/contains_employed/note/confidence/
    p25/p50/p75）——本函数无 code 层参考参数（report_assembler.finalize_report 也调用它），
    无法单独接地。事实字段接地由 `ground_norm_to_code` 在 career_analysis._analyze_with_llm
    （norm_payload 局部可得）完成，本函数只承接已接地载荷的文案补全。
    """
    if not isinstance(norm, dict) or not norm:
        return norm
    out = dict(norm)
    out["disclaimer"] = _DISCLAIMER
    reasons = out.get("confidence_reasons")
    if not isinstance(reasons, dict) or not reasons.get("supporting"):
        out["confidence_reasons"] = _norm_confidence_reasons_from_dict(out)
    return out


# 常模事实字段（反幻觉底线）：只能来自 code 层 norm_payload，LLM 不得修改。
# code payload 无的键（如 sample_size<30 时无 p25/p50/p75）一律剔除；LLM 只允许补文案。
_NORM_FACT_KEYS = frozenset(
    {
        "band",
        "sample_size",
        "cohort",
        "contains_employed",
        "note",
        "confidence",
        "p25",
        "p50",
        "p75",
    }
)


def ground_norm_to_code(llm_norm: dict | None, code_norm: dict | None) -> dict | None:
    """常模事实字段接地（反幻觉底线；接地 seam 由 career_analysis._analyze_with_llm 调用）。

    事实字段（band/sample_size/cohort/contains_employed/note/confidence/p25/p50/p75）
    只能来自 code 层 code_norm（NormBenchmark.to_dict 或上游 dict）：
    - code_norm 为 None（无常模数据）→ 丢弃 LLM norm，返回 None（不伪造 norm 对象），不报错；
    - 其余情况（含 LLM norm 为 None / 非 dict / 缺事实字段）→ 以 code_norm 为准重建：
      仅保留 code_norm 拥有的键（code_norm 无 p25/p50/p75 → 一并剔除），LLM norm 不参与
      任何事实取值；confidence_reasons 按 code 事实确定性组装（normalize_norm_payload 补全，
      不保真保留 LLM 文案——防「样本量为 120」等伪造数字绕过接地）。
    """
    if not code_norm:
        # None 或空 dict：无常模事实 → 丢弃 LLM norm，不伪造 norm 对象
        return None
    grounded = {key: code_norm[key] for key in _NORM_FACT_KEYS if key in code_norm}
    grounded["matched"] = code_norm.get("matched", True)
    return normalize_norm_payload(grounded)


def _norm_confidence_reasons_from_dict(norm: dict) -> dict:
    """基于 norm 载荷已有字段确定性组装 supporting/concerns（无 NormBenchmark 实例时）。"""
    supporting: list[str] = []
    cohort = str(norm.get("cohort") or "").strip()
    if cohort:
        supporting.append(f"样本与用户专业/城市等级匹配（{cohort}）")
    try:
        enough = int(norm.get("sample_size")) >= NORM_MIN_SAMPLE
    except (TypeError, ValueError):
        enough = False
    if enough:
        supporting.append(f"样本量为 {norm.get('sample_size')}，达到中等可靠等级")
    if not supporting:
        supporting.append("常模对比基于样本口径数据")
    concerns: list[str] = []
    if norm.get("contains_employed"):
        concerns.append("样本含在职人员，应届生起薪通常低于市场均值")
    if enough:
        concerns.append("常模样本为预置基准，与个体实际情况可能存在偏差")
    else:
        concerns.append("样本量未达高可靠阈值，参考价值有限")
    return {"supporting": supporting, "concerns": concerns}
