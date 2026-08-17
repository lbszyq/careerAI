"""Stage1 方向推荐 RAG 检索失效修复测试：query 改为「完整岗位名 + 岗位要求 技能」维度。"""
from app.ai.agents.market import _build_queries, _job_titles_for_major
from app.ai.norm.benchmarks import DEFAULT_MAJOR_CATEGORY, map_major_to_category


class _FakeResult:
    """模拟 session.execute(...) 返回的可迭代行（每行 (job_title,)）。"""

    def __init__(self, titles):
        self._titles = titles

    def __iter__(self):
        return iter([(t,) for t in self._titles])


class _FakeSession:
    def __init__(self, titles):
        self._titles = titles

    async def execute(self, stmt):
        return _FakeResult(self._titles)


def test_map_major_to_category_handles_pure_major_names():
    """纯专业名（岗位名关键词不含其词根）也能映射到大类。"""
    assert map_major_to_category("计算机科学与技术") == "计算机类"
    assert map_major_to_category("数据科学与大数据技术") == "计算机类"
    assert map_major_to_category("人工智能") == "计算机类"
    assert map_major_to_category("软件工程") == "计算机类"
    assert map_major_to_category("会计学") == "经济金融类"
    assert map_major_to_category("法学") == "法学类"
    assert map_major_to_category(None) == DEFAULT_MAJOR_CATEGORY
    assert map_major_to_category("星际探险专业") == DEFAULT_MAJOR_CATEGORY


async def test_job_titles_for_major_filters_by_category():
    """从数据库 distinct job_title 按专业大类筛选（完整岗位名，非反查关键词）。"""
    session = _FakeSession(["后端开发工程师", "算法工程师", "软件测试工程师", "会计", "律师"])
    titles = await _job_titles_for_major(session, {"major": "计算机科学与技术"})
    assert "后端开发工程师" in titles
    assert "软件测试工程师" in titles
    assert "会计" not in titles, "非计算机类岗位名不应混入"
    assert "律师" not in titles


async def test_build_queries_stage1_uses_complete_job_titles_with_suffix():
    """Stage1：每个完整岗位名单独一条 query，且加「岗位要求 技能」后缀。"""
    session = _FakeSession(["后端开发工程师", "算法工程师", "软件测试工程师", "会计"])
    profile = {"major": "计算机科学与技术", "skills": ["Python", "Java", "SQL"]}
    queries = await _build_queries(profile, ["北京"], ["互联网"], None, session)
    assert queries, "Stage1 query 不应为空"
    for q in queries:
        assert q.endswith("岗位要求 技能"), "Stage1 query 应加「岗位要求 技能」后缀"
        assert "岗位 薪资" not in q, "Stage1 query 不应是技能泛词"
    assert any("后端开发工程师" in q for q in queries)
    assert any("软件测试工程师" in q for q in queries)
    assert all("会计" not in q for q in queries)


async def test_build_queries_stage1_falls_back_when_major_missing():
    """专业缺失/映射不到大类：退回原泛词 query 兜底。"""
    session = _FakeSession(["后端开发工程师"])
    profile = {"skills": ["Python", "Java", "SQL"]}
    queries = await _build_queries(profile, ["北京"], ["互联网"], None, session)
    assert queries
    assert "岗位 薪资" in queries[0], "无专业时应退回泛词 query"


async def test_build_queries_stage2_unchanged():
    """Stage2（有 target_job）：现有 query 构造保持不变。"""
    session = _FakeSession([])
    profile = {"major": "计算机科学与技术", "skills": ["Python", "Java", "SQL"]}
    queries = await _build_queries(profile, ["北京"], ["互联网"], "后端开发工程师", session)
    assert queries[0] == "后端开发工程师 岗位要求 技能"
    assert any("岗位 薪资 技能要求" in q for q in queries)
