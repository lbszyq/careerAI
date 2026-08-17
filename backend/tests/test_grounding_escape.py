"""报告质量-grounding 关键词逃逸修复（审计 P1）测试。

漏洞证据：_jd_source_mapped 在依据池为空时，jd_source 只要含
「未检索/兜底/数据较少/暂无/通用要求」任一关键词就通过——LLM 写一句
「未检索到岗位要求，按通用要求兜底」就能把自己编造的 JD 要求合法送进报告。

修复语义（反幻觉底线）：
- fallback 标注由服务端代码依据「依据池为空（RAG 无结果）」判定，打结构化标记
  jd_source_kind=fallback；LLM 文本自报关键词不再构成通过依据；
- 依据池非空时，LLM 无论写什么都按依据池映射判定（含兜底字样但映射到池 → jd；
  含兜底字样且未映射 → 删除）。

验证标准：
- 标准 1：LLM 输出 jd_source 含「未检索/兜底/数据较少/暂无/通用要求」但服务端实际有依据
  （依据池非空）→ grounding 不通过；LLM 自报 fallback 词不再单独构成通过依据。
- 标准 2：服务端依据池真的为空（RAG 无结果）→ 代码打 jd_source_kind=fallback
  结构化标记（不依赖 LLM 文本），正常放行；依据池非空 → LLM 无论写什么都按依据池判定。
"""

from app.ai.grounding import _jd_source_kind, audit_report_grounding


# ---------------------------------------------------------------------------
# 构造辅助
# ---------------------------------------------------------------------------
def _state(requirements=None, jd_summary=None) -> dict:
    """服务端状态：requirements + jd_summary 即 JD 要求依据池（空 = RAG 无结果）。"""
    return {
        "target_job_requirements": requirements if requirements is not None else [],
        "target_job_jd_summary": jd_summary if jd_summary is not None else {},
    }


def _gap_item(
    skill="Kubernetes",
    jd_source="未检索到岗位要求，按通用要求兜底",
    evidence="用户技能列表无 Kubernetes",
):
    return {"skill": skill, "jd_source": jd_source, "evidence": evidence}


def _report(*items) -> dict:
    return {
        "gap_analysis": {"target_job": "后端开发工程师", "items": list(items)},
        "directions": [],
        "suggestion": None,
    }


def _kept_items(out: dict) -> list:
    return (out.get("gap_analysis") or {}).get("items") or []


# ---------------------------------------------------------------------------
# 标准 1：LLM 自报 fallback 词 + 服务端实际有依据 → 不通过（逃逸口闭合）
# ---------------------------------------------------------------------------
def test_llm_fallback_keywords_with_server_evidence_do_not_pass():
    """标准 1：jd_source 含「未检索/兜底/通用要求」但依据池非空且未映射 → 整项删除。"""
    state = _state(requirements=["Python", "SQL"], jd_summary={"job_title": "后端开发工程师"})
    out = audit_report_grounding(
        _report(_gap_item(jd_source="未检索到岗位要求，按通用要求兜底")), state
    )
    assert _kept_items(out) == []


def test_llm_fallback_keywords_no_longer_standalone_pass_basis():
    """标准 1：LLM 自报「兜底」等词不再单独构成通过依据（关键词本身不映射到池）。"""
    for keyword in ("未检索", "兜底", "数据较少", "暂无", "通用要求"):
        state = _state(requirements=["Python"], jd_summary={})
        out = audit_report_grounding(
            _report(_gap_item(jd_source=f"按{keyword}处理岗位要求")), state
        )
        assert _kept_items(out) == [], f"关键词 {keyword} 不应单独放行"


def test_llm_fallback_words_with_pool_mapping_still_pass_as_jd():
    """标准 1 边界：jd_source 含兜底字样但确实引用依据池内容 → 按依据池判定通过，标注 jd。"""
    state = _state(requirements=["Python", "SQL 窗口函数"], jd_summary={})
    item = _gap_item(
        skill="Kubernetes",
        jd_source="JD 要求：熟练使用 SQL 窗口函数（未检索到岗位要求，按通用要求兜底）",
        evidence="用户技能列表无 SQL 窗口函数",
    )
    out = audit_report_grounding(_report(item), state)
    kept = _kept_items(out)
    assert len(kept) == 1
    assert kept[0]["jd_source_kind"] == "jd"


# ---------------------------------------------------------------------------
# 标准 2：服务端依据池真的为空 → 结构化 fallback 标记，正常放行
# ---------------------------------------------------------------------------
def test_server_empty_pool_stamps_structured_fallback():
    """标准 2：依据池为空（RAG 无结果）→ 代码打 jd_source_kind=fallback，正常放行。"""
    state = _state() # requirements=[] + jd_summary={} → 依据池空
    out = audit_report_grounding(_report(_gap_item()), state)
    kept = _kept_items(out)
    assert len(kept) == 1
    assert kept[0]["jd_source_kind"] == "fallback"


def test_server_empty_pool_stamps_fallback_regardless_of_llm_text():
    """标准 2：依据池为空时，LLM 写具体 JD 要求文本也统一由服务端标注 fallback（不依赖 LLM 文本判定）。"""
    state = _state()
    item = _gap_item(skill="Kubernetes", jd_source="JD 要求：精通 Kubernetes 容器编排")
    out = audit_report_grounding(_report(item), state)
    kept = _kept_items(out)
    assert len(kept) == 1
    assert kept[0]["jd_source_kind"] == "fallback"


def test_pool_empty_but_other_fields_missing_still_fails():
    """标准 2 边界：依据池空只解决 jd_source 判定，skill/evidence 缺失仍不通过。"""
    state = _state()
    out = audit_report_grounding(_report(_gap_item(evidence="")), state)
    assert _kept_items(out) == []
    out2 = audit_report_grounding(_report(_gap_item(skill="")), state)
    assert _kept_items(out2) == []


# ---------------------------------------------------------------------------
# 依据池非空 → 按依据池判定（LLM 无论写什么都按池）
# ---------------------------------------------------------------------------
def test_pool_nonempty_unmapped_jd_source_deleted():
    """依据池非空 + jd_source 未映射（编造）→ 整项删除。"""
    state = _state(requirements=["Python", "SQL"], jd_summary={})
    item = _gap_item(skill="Kubernetes", jd_source="JD 要求：精通 Kubernetes 容器编排")
    out = audit_report_grounding(_report(item), state)
    assert _kept_items(out) == []


def test_pool_nonempty_mapped_jd_source_kept_as_jd():
    """依据池非空 + jd_source 映射到池 → 通过并标注 jd（原有据路径不受影响）。"""
    state = _state(requirements=["Python", "SQL"], jd_summary={})
    item = _gap_item(skill="Kubernetes", jd_source="JD 要求：熟练使用 SQL")
    out = audit_report_grounding(_report(item), state)
    kept = _kept_items(out)
    assert len(kept) == 1
    assert kept[0]["jd_source_kind"] == "jd"


def test_pool_nonempty_skill_association_still_grounds():
    """依据池非空 + skill 名与池关联（skill 是差距对象）→ 通过并标注 jd（原有 skill 关联规则不变）。"""
    state = _state(requirements=["Python", "SQL"], jd_summary={})
    item = _gap_item(skill="SQL", jd_source="未检索到岗位要求，按通用要求兜底")
    out = audit_report_grounding(_report(item), state)
    kept = _kept_items(out)
    assert len(kept) == 1
    assert kept[0]["jd_source_kind"] == "jd"


# ---------------------------------------------------------------------------
# 服务端判定优先（LLM 自报 jd_source_kind 不生效）
# ---------------------------------------------------------------------------
def test_server_overrides_llm_claimed_jd_source_kind():
    """LLM 自报 jd_source_kind 一律被服务端判定覆盖：池空→fallback；池非空未映射→删除。"""
    # LLM 自报 "jd" 但依据池空 → 服务端改标 fallback
    state = _state()
    item = _gap_item()
    item["jd_source_kind"] = "jd"
    out = audit_report_grounding(_report(item), state)
    assert _kept_items(out)[0]["jd_source_kind"] == "fallback"
    # LLM 自报 "fallback" 但依据池非空且未映射 → 删除（自报不能保命）
    state2 = _state(requirements=["Python"], jd_summary={})
    item2 = _gap_item(skill="Kubernetes", jd_source="未检索到岗位要求，按通用要求兜底")
    item2["jd_source_kind"] = "fallback"
    out2 = audit_report_grounding(_report(item2), state2)
    assert _kept_items(out2) == []


# ---------------------------------------------------------------------------
# 不原地修改 + 单元级 _jd_source_kind
# ---------------------------------------------------------------------------
def test_audit_does_not_mutate_original_items():
    """审计在副本上打标注：输入报告的原 item 不被修改（audit_report_grounding 不原地修改契约）。"""
    state = _state()
    item = _gap_item()
    report = _report(item)
    audit_report_grounding(report, state)
    assert "jd_source_kind" not in item


def test_jd_source_kind_unit():
    """_jd_source_kind 单元：池空→fallback；池非空映射→jd；池非空未映射→None。"""
    assert _jd_source_kind("未检索到岗位要求，按通用要求兜底", [], {}, "Kubernetes") == "fallback"
    assert _jd_source_kind("JD 要求：熟练使用 SQL", ["SQL"], {}, "Kubernetes") == "jd"
    assert _jd_source_kind("未检索到岗位要求，按通用要求兜底", ["SQL"], {}, "Kubernetes") is None
    # requirements 为 dict 形态（：{"name"/"skill", "required_level"}）同样进池
    assert (
        _jd_source_kind(
            "JD 要求：熟练使用 Redis 缓存",
            [{"name": "Redis", "required_level": "core"}],
            {},
            "Kubernetes",
        )
        == "jd"
    )


# ---------------------------------------------------------------------------
# 聚合后 jd_summary（技能带 count / 含职责）流经 grounding 仍正确映射
# ---------------------------------------------------------------------------
def test_aggregated_jd_summary_skills_still_map():
    """标准 5：聚合后 required_skills 项保留 name 键（带 count）→ 依据池仍提取技能，映射通过。"""
    jd_summary = {
        "job_title": "后端开发工程师",
        "required_skills": [
            {"name": "Java", "required_level": "core", "count": 3},
            {"name": "SQL", "required_level": "core", "count": 2},
        ],
        "responsibilities": ["负责后端服务开发"], # 职责不进池
    }
    state = _state(requirements=[], jd_summary=jd_summary)
    item = _gap_item(skill="Java", jd_source="JD 要求：熟练使用 Java", evidence="用户技能列表无 Java")
    out = audit_report_grounding(_report(item), state)
    kept = _kept_items(out)
    assert len(kept) == 1
    assert kept[0]["jd_source_kind"] == "jd"


def test_aggregated_jd_summary_responsibilities_not_in_pool():
    """标准 5：职责不进依据池——jd_source 引用职责原文不映射 → 整项删除（反幻觉底线）。"""
    jd_summary = {
        "job_title": "后端开发工程师",
        "required_skills": [{"name": "Java", "required_level": "core", "count": 3}],
        "responsibilities": ["负责后端服务开发", "参与系统架构设计"],
    }
    state = _state(requirements=[], jd_summary=jd_summary)
    # skill 用非池内名称（Kubernetes），确保只有职责原文可被引用时仍不通过
    item = _gap_item(skill="Kubernetes", jd_source="JD 要求：负责后端服务开发",
                     evidence="用户技能列表无 Kubernetes")
    out = audit_report_grounding(_report(item), state)
    assert _kept_items(out) == []


def test_aggregated_jd_summary_unit_source_kind():
    """标准 5：聚合后 jd_summary 经 _jd_source_kind——技能名进池映射 jd、职责不进池映射 None。"""
    jd_summary = {
        "job_title": "后端开发工程师",
        "required_skills": [{"name": "Java", "required_level": "core", "count": 3}],
        "responsibilities": ["负责后端服务开发"],
    }
    assert _jd_source_kind("JD 要求：熟练使用 Java", [], jd_summary, "Kubernetes") == "jd"
    assert _jd_source_kind("JD 要求：负责后端服务开发", [], jd_summary, "Kubernetes") is None
