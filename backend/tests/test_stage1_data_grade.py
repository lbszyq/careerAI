"""Stage1 方向 data_grade 注入不完整修复测试：hits 覆盖全部 queries。"""
from app.ai.agents import market as market_module
from app.ai.agents.deps import AgentDeps
from app.ai.agents.market import _inject_direction_data_grade, market_research_node
from app.ai.rag.retriever import MarketHit
from app.ai.schemas import initial_state


class _FakeRows:
    """模拟 session.execute(...) 返回的可迭代行（每行 (job_title,)）。"""

    def __init__(self, titles):
        self._titles = titles

    def __iter__(self):
        return iter([(t,) for t in self._titles])


class _FakeSession:
    def __init__(self, titles):
        self._titles = titles

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        return _FakeRows(self._titles)


class _FakeEmbedding:
    def is_available(self):
        return True


def _hit(job_title: str, source_type: str | None = "job_post") -> MarketHit:
    return MarketHit(
        id=f"id-{job_title}",
        city="北京",
        industry="互联网",
        job_title=job_title,
        salary_p25=None,
        salary_p50=10000,
        salary_p75=None,
        trend=None,
        heat="中",
        required_skills=[],
        data_source="legacy-jd",
        confidence=None,
        data_quarter="2026Q2",
        city_tier="一线",
        similarity=0.8,
        source_type=source_type,
    )


async def test_market_research_node_collects_hits_from_all_queries(monkeypatch):
    """hits 遍历全部 queries（非仅前 2），使每个候选岗位名都有命中可注入 data_grade。"""
    called_queries = []

    async def fake_search_market(session, query, **kwargs):
        called_queries.append(query)
        return []

    async def fake_build_market_context(session, queries, **kwargs):
        return ""

    monkeypatch.setattr(market_module, "search_market", fake_search_market)
    monkeypatch.setattr(market_module, "build_market_context", fake_build_market_context)

    session = _FakeSession(["后端开发工程师", "算法工程师", "软件测试工程师"])
    deps = AgentDeps(llm=None, embedding=_FakeEmbedding(), rag_session_factory=lambda: session)
    state = initial_state(profile={"major": "计算机科学与技术", "skills": ["Python"]}, stage="stage1")
    await market_research_node(state, deps)

    # 3 个岗位名 query，search_market 应被调用 3 次（全部），而非仅前 2
    assert len(called_queries) == 3, (
        f"search_market 应遍历全部 query，实际 {len(called_queries)} 次：{called_queries}"
    )
    assert any("后端开发工程师" in q for q in called_queries)
    assert any("算法工程师" in q for q in called_queries)
    assert any("软件测试工程师" in q for q in called_queries)


def test_inject_direction_data_grade_from_hit_in_later_query():
    """命中记录来自任意 query 的岗位名时，方向 data_grade 可正确注入（job_post → B）。"""
    hits = [
        _hit("后端开发工程师", source_type="job_post"),
        _hit("算法工程师", source_type="official_stat"),
    ]
    direction = {"job_title": "后端开发工程师"}
    result = _inject_direction_data_grade(direction, hits)
    assert result["data_grade"] == "B", f"data_grade 应注入 B，实际 {result['data_grade']}"


def test_inject_direction_data_grade_null_when_no_hit():
    """无命中时 data_grade=null（不编造）。"""
    result = _inject_direction_data_grade({"job_title": "前端开发工程师"}, [_hit("后端开发工程师")])
    assert result["data_grade"] is None
