# 岗位 ETL / Job Knowledge Pipeline

岗位进入系统后统一经过“原始快照 → 清洗 → 标准化 → 分段 → 结构化提取 → 证据校验 → 质量评估 → 去重/生命周期 → 知识库索引”流程。BOSS 直聘、智联招聘、普通创建和批量导入都复用同一份管线契约，平台适配器只负责把来源数据转换为 `RawJobRecord`。

## 数据与可追溯性

- `jobs` 保存当前岗位、标准化管线结果、质量等级、生命周期和重复组。
- `job_raw_snapshots` 按 `job_id + content_hash` 保存不可变原始快照，重复回填不会生成重复快照；删除岗位时快照仍保留并解除关联。
- `jobs.normalized_data.pipeline` 保存当前规范化结果、分段、证据、解析器版本和内容哈希，便于详情页、RAG 和后续重放。
- `GET /api/jobs/{job_id}/pipeline` 提供只读调试信息，包括快照数量、质量、生命周期和规范化结果。

## 处理规则

清洗阶段移除脚本、样式和页面噪声，但保留原始描述；标准化阶段统一标题、岗位族、地点、薪资单位、学历、经验、工作类型和技能别名；分段阶段识别职责、任职要求、加分项、福利和摘要。结构化字段只有在原文或可定位的技能证据存在时才通过证据校验，避免把模型推断写成事实。

质量分由标题、JD 完整度、公司/地点/薪资、职责/要求、技能和证据覆盖率共同计算，分为 `high`、`medium`、`low`。生命周期默认按最近采集时间判断：14 天后进入 `possibly_expired`，30 天后进入 `expired`；RAG 默认排除已过期且质量低于阈值的岗位。

## 增量与全量回填

岗位创建、更新、导入和招聘平台刷新都会先运行 ETL；内容没有变化时复用当前快照，内容变化时新增快照并将岗位加入现有知识索引任务。索引任务沿用已有 Worker 的批量、进度、失败记录和断点恢复机制。

已有数据全量回填：

```powershell
docker compose exec api python -m scripts.backfill_job_pipeline --batch-size 100
```

只做 ETL、不创建索引任务：

```powershell
docker compose exec api python -m scripts.backfill_job_pipeline --batch-size 100 --skip-index
```

检查单个岗位：

```powershell
docker compose exec api python -m tools.inspect_job <job-id>
```

## 检索使用方式

知识库继续复用现有 PostgreSQL 全文检索、向量检索、可选重排和证据包生成能力。每个结果带有岗位来源、原文证据、质量和数据新鲜度信息，职业顾问可以据此生成薪资、学历、技能和学习建议。

## 当前边界

- 当前抽取器以规则优先，保留了解析器版本和证据字段；后续可在低质量或分段不确定时接入受约束的 LLM 抽取，但必须经过同一证据校验，不能直接覆盖原文事实。
- 去重目前先按来源外部 ID、公司、标题和相似度筛选候选；数据规模进一步增长后可增加 trigram/ANN 候选索引。
- 快照保留期限、敏感信息脱敏和质量监控看板尚未设置统一策略，应在生产部署前补充数据治理规则。
