# AI 评估数据集

本目录是 AI 最小评估体系的评测集：**全部为合成样例，不含任何真实用户隐私数据**。

## 文件清单

| 文件 | 用途 | 条数 |
|------|------|------|
| `resume_cases.json` | 简历原文输入（预留简历解析评估） | 8 |
| `portrait_cases.json` | 职业画像对象（report.portrait 同构） | 8 |
| `report_cases.json` | 最终报告（reports-contract 结构） | 8 |
| `rag_cases.json` | RAG 检索查询 + 期望命中岗位（ground truth） | 11 |
| `market_corpus.json` | 合成市场语料（mock 模式检索底座，字段对齐 market_data） | 30 |

三类输入覆盖：**简历 / 画像 / 报告**（共 24 条，≥20 条验证达标）。

## Schema 说明

统一文件结构：

```json
{
  "_meta": { "schema_version": "1.0", "category": "...", "description": "...", "structure": "..." },
  "cases": [ ... ]
}
```

`_meta` 为人类可读说明（加载器不校验）；`cases` 由 `backend/app/ai/evaluation/schemas.py`
中的 Pydantic 模型严格校验（`extra="forbid"`，未知字段即报错），**该文件是 schema 的唯一权威**。

- `resume_cases.json`：`cases[] = {case_id, category:"resume", description, input:{resume_text}, expected:{must_have_fields, expected_name, expected_education, expected_skills, must_contain_text, must_not_contain_text}}`
- `portrait_cases.json`：`cases[] = {case_id, category:"portrait", description, input:{画像对象}, expected:{must_have_fields, overall_score_min, overall_score_max, dimensions_required, confidence_allowed}}`
- `report_cases.json`：`cases[] = {case_id, category:"report", description, report:{报告对象}, expected:{must_have_fields, must_not_contain, directions_min/max, gap_items_min, plan_tasks_min, suggestion}}`
- `rag_cases.json`：`cases[] = {case_id, category:"rag", description, query, expected_job_titles, expected_skills, expected_city}`
- `market_corpus.json`：`cases[] = {id, city, industry, job_title, salary_p25, salary_p50, salary_p75, trend, heat, required_skills, data_source, confidence, data_quarter, city_tier, source_type}`

## 负例说明

`portrait_cases.json`（007/008）与 `report_cases.json`（005/006/007/008）包含**故意构造的反例**
（超界评分、缺字段、占位文案、非法 level、空报告等），用于证明规则引擎能捕获问题——
因此评测通过率**不应为 100%**，通过率下降即为质量回退信号（对齐 门禁：指标下降 >5% 阻止合并）。

## 使用

```bash
cd backend
python -m scripts.eval_rag --help
python -m scripts.eval_report_quality --help
```

自定义数据目录：`python -m scripts.eval_rag --data <dir>`（目录内需含对应 JSON 文件）。
