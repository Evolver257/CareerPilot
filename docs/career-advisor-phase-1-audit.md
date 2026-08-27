# CareerPilot 职业顾问 Agent：Phase 1 审计与实施设计

审计日期：2026-08-28

本阶段只完成现状审计、可复用边界确认和实施设计，不改动现有稳定业务代码。

## 1. 审计结论

当前项目已经具备实现职业顾问 Agent 的主要基础，但还没有形成岗位知识库和聊天会话层。

现有可用能力包括：

- `apps/web` 使用 Next.js 15、React 19、TypeScript 和 Tailwind，已有职位、简历、职业洞察、智能匹配、Agent Run、投递计划和 LLM 设置页面。
- `services/api` 使用 FastAPI、SQLAlchemy 2、Alembic 和 PostgreSQL；测试使用 SQLite 内存数据库。
- `Job`、`JobSkill` 和 `Job.normalized_data` 已保存岗位原始信息和岗位解析结果。
- `JobNormalizer`、`JobParser`、`SkillExtractor` 和 `RequirementExtractor` 已能提取职责、任职条件、技能、学历、经验和薪资。
- `ResumeChunk`、`EmbeddingType`、Embedding Provider 和 `ResumeRAG` 已提供简历向量检索基础。
- `MarketInsightAggregator` 已能基于岗位集合计算薪资、学历、经验、技能、职责主题、岗位族群和学习路线。
- LLM Provider 已支持 Mock、OpenAI Chat Completions 和 Anthropic Messages，并允许聊天模型与 Embedding Provider 独立配置。
- Agent Runtime 已提供工具注册、步骤追踪、事件、暂停、恢复、取消、超时和重试能力。
- 市场洞察和排名已有持久化状态、轮询、缓存和 API 重启恢复模式，可作为知识库任务的参考。
- 现有职位详情页可以作为职业顾问引用岗位的跳转目标。

当前缺口包括：

- 没有 `job_versions`，岗位 JD 变化时无法保留历史版本。
- 没有岗位知识文档、语义知识块和岗位 Embedding 索引。
- 没有技能标准化、技能别名和岗位—技能事实表。
- 现有职位搜索主要使用 SQL `LIKE/ILIKE`，市场洞察主要在内存中计算相关性，尚未形成 SQL、全文和向量混合检索。
- 没有职业顾问聊天会话、消息、引用、会话摘要和长期职业偏好模型。
- `MarketInsightReport` 是一次性异步报告，不适合直接承载多轮对话；可以复用其统计和任务模式，但不应把聊天状态塞入报告表。
- `services/worker` 当前只是 Redis 连通性占位程序，没有真正消费持久化任务。
- 当前项目没有认证中间件，业务主要通过默认用户工作；第一版应保持现状，同时为后续用户隔离保留 `user_id` 边界。

## 2. 稳定边界与复用策略

### 直接复用

- 复用 `Job`、`JobSkill`、`JobService` 和现有岗位解析结果，避免改写岗位导入链路。
- 复用 `ResumeChunk` 的 Embedding Provider 调用和简历检索逻辑。
- 复用 `LLMSettingsService` 的 Provider 选择、密钥脱敏和运行时 Provider 获取。
- 复用 `MarketInsightAggregator` 的确定性统计规则，并将其后续逐步抽取为可由职业顾问工具调用的聚合服务。
- 复用现有异步状态字段、任务恢复和报告缓存设计。
- 复用 Agent Runtime 的事件与追踪思想，但职业顾问 Agent 使用独立的只读工具白名单。
- 复用前端 `apps/web/lib/api.ts` 的请求封装、主题系统和现有职位详情路由。

### 不应直接复用或修改

- 不把岗位知识块写入 `resume_chunks`，岗位知识和简历知识的生命周期、过滤条件和引用语义不同。
- 不让职业顾问 Agent 使用 `create_campaign`、`queue_application`、Browser Task 或其他投递工具。
- 不让 LLM 从原始 JD 自行统计薪资、比例和岗位数量；这些数据必须由结构化查询返回。
- 不在第一阶段引入 Elasticsearch、独立向量数据库或复杂 GraphRAG。当前 PostgreSQL + pgvector + 全文检索足够支撑 MVP。
- 不把所有岗位原文和全部历史聊天记录放入 Prompt。

## 3. 推荐的最小目标架构

```text
现有岗位采集/导入
        |
        v
岗位解析与标准化 ----> Job / JobSkill（现有）
        |
        +------------> 岗位版本、知识文档、语义知识块、Embedding
        |
        +------------> 岗位技能事实、市场统计快照
                                      |
用户问题 -> 意图和筛选条件 -> SQL 统计 + 全文检索 + 向量检索 + 简历检索
                                      |
                                      v
                              融合、去重、轻量重排
                                      |
                                      v
                       职业顾问 Agent + 引用 + 可执行学习路线
```

核心架构决策：

1. 结构化事实负责数字，知识块负责语义，LLM 负责解释和规划。
2. 职业顾问 Agent 与投递 Agent 分离，但可以共享底层 Runtime 和 Provider。
3. 岗位引用必须能追溯到 `job_id`、知识块和岗位详情页。
4. 知识库采用增量更新，岗位内容未变化时不重新切块和向量化。

## 4. Phase 2 数据库设计基线

下一阶段建议新增以下实体，具体字段可根据当前命名规范落地：

### `job_versions`

保存岗位 JD 的版本快照：`job_id`、版本号、原始标题、原始描述、原始载荷、内容哈希、来源、采集时间、解析器版本、是否当前版本。

### `job_knowledge_documents`

保存某个岗位版本的知识文档元数据：`job_id`、`job_version_id`、标准岗位族、标准标题、城市、学历、经验、薪资、工作类型、知识版本和有效状态。

### `job_knowledge_chunks`

保存语义区块：`document_id`、`job_id`、`section_type`、正文、内容哈希、Token 数、Embedding、Embedding Provider、模型、维度、签名和元数据。

区块至少支持：`overview`、`responsibilities`、`requirements`、`required_skills`、`preferred_skills`、`education`、`experience`、`salary_benefits`、`business_domain`、`other`。

### `skill_taxonomy`、`skill_aliases`、`job_skill_facts`

用于保存标准技能、技能别名、岗位中技能的要求类型、证据和置信度。第一版应支持“大模型/LLM”“RAG/检索增强生成”“AI Agent/智能体”“PyTorch/Torch”“ROS/ROS2”等归一化。

### `market_insight_snapshots`

缓存按方向、城市、学历、经验和时间范围计算的样本量、薪资分布、学历分布、技能频率、岗位分布和数据版本。

### 职业顾问会话实体

建议新增：

- `chat_sessions`：用户、会话标题、Agent 类型、简历、职业目标、筛选条件和更新时间。
- `chat_messages`：角色、内容、状态、模型、Token、延迟和错误信息。
- `chat_citations`：消息、岗位、知识块、引用序号和证据片段。

Embedding 维度风险：当前 `ResumeChunk.embedding` 和迁移使用固定 384 维。为避免破坏现有数据，Phase 2 的岗位 Embedding 第一版应沿用当前维度，并用 `embedding_signature` 区分模型；如果未来允许任意维度，需要单独设计按模型分表或迁移方案，不应直接修改现有向量列。

## 5. Phase 3 混合检索设计

建议实现独立的 `JobKnowledgeRAG` 服务和仓储：

1. 查询理解：提取岗位方向、城市、学历、经验、工作类型和时间窗口。
2. 结构化聚合：返回岗位数量、薪资、学历、经验、技能频率和趋势。
3. 全文召回：精确匹配岗位名称、技能、缩写、公司和 JD 词汇。
4. 向量召回：匹配语义相近的岗位职责和任职条件。
5. 简历召回：在用户开启“结合我的简历”时调用现有 Resume RAG。
6. 元数据过滤：城市、学历、经验、岗位类型和有效状态。
7. RRF 或加权融合，再做轻量重排。
8. 按岗位和公司去重，保证证据多样性。
9. 最终只向 LLM 传递约 8～12 个代表性区块。

当前 PostgreSQL 方案建议使用 pgvector、HNSW、PostgreSQL 全文检索和 GIN/BTREE 索引；SQLite 测试环境保留 Python/LIKE 降级路径，不在测试中依赖 PostgreSQL 专用 SQL。

## 6. Phase 4 职业顾问 Agent 设计

Agent 类型建议为 `career_advisor`，仅注册以下只读或计划生成工具：

- `search_job_knowledge`
- `aggregate_job_market`
- `compare_role_profiles`
- `analyze_resume_gap`
- `build_learning_roadmap`
- `recommend_jobs`
- `explain_skill_demand`
- `estimate_job_coverage`
- `retrieve_resume_evidence`

需要识别的意图：`market_research`、`learning_roadmap`、`resume_gap`、`role_comparison`、`job_recommendation`、`salary_analysis`、`skill_analysis`、`follow_up` 和 `general_career_chat`。

简单问题使用单工具或固定流程，复杂问题才使用多步规划。最终输出区分“数据事实”和“AI 建议”，同时返回样本量、时间窗口、数据更新时间和引用。

## 7. Phase 5 前端设计基线

新增“职业顾问”一级导航和页面，建议采用：

- 左侧：历史会话、职业目标和学习计划入口。
- 中间：流式聊天、停止生成、重新生成、快捷问题和保存学习计划。
- 顶部：城市、学历、经验、工作类型、时间窗口和是否结合简历。
- 右侧：统计口径、样本量、数据更新时间、引用岗位和 JD 证据。

引用岗位跳转到现有 `/jobs/{id}`。所有新增状态、表格、引用面板、Markdown、弹窗和错误提示都必须兼容日间与夜间模式。

## 8. 任务与持久化策略

Phase 2 的知识库索引任务应具备：

- 全量回填和新增岗位增量索引。
- 基于内容哈希的幂等处理。
- 每个岗位成功、失败、跳过和失败原因统计。
- 取消、重试和服务重启恢复。
- 单个岗位失败不影响其他岗位。
- 已完成知识块和 Embedding 持久化后再推进进度。

当前 Worker 只是占位程序。最小方案可以沿用现有 API 内任务调度和启动恢复模式，但必须把任务状态和检查点持久化；后续再将真正的任务消费迁移到 Worker，避免在本阶段引入过大的基础设施变更。

## 9. 基线测试结果

2026-08-28 在当前干净工作树执行：

- API：`80 passed in 14.86s`
- Web：`npm run typecheck` 通过
- Web：`npm run lint` 通过
- Web：`npm run build` 通过，生成 15 个页面
- Extension：`npm run typecheck` 通过
- Extension：`npm run build` 通过

当前没有为职业顾问 Agent 和岗位知识库新增代码，因此没有新增失败项，也没有修改现有迁移或稳定业务逻辑。

## 10. 风险清单

### 高风险

- 直接修改固定 384 维 Embedding 列可能破坏已有简历数据和 SQLite 测试。
- 依赖 API 进程内 `asyncio.Task` 会在进程终止时丢失执行上下文，因此必须依靠持久化检查点恢复。
- 没有认证中间件时，未来多用户聊天和引用数据存在隔离风险。

### 中风险

- 岗位 JD 质量不一致，需先复用现有解析结果，再逐步完善技能标准化。
- 同一岗位可能来自不同采集批次，必须使用外部 ID、内容哈希和版本组合去重。
- 薪资单位可能混合日薪、月薪和年薪，统计时必须按单位分组，不能直接求平均。
- 中文全文检索能力取决于 PostgreSQL 配置，第一版应保留标题/技能/描述的兼容降级。

### 产品风险

- 岗位样本不足时，Agent 容易给出过于确定的行业结论。
- 只展示自然语言结论、不提供引用，会降低用户对系统的信任。
- 把职业顾问与投递动作混在同一个 Agent 中，会造成误操作和安全边界不清。

## 11. 后续实施顺序

### Phase 2：岗位知识库

数据库迁移、岗位版本、语义切块、技能事实、增量索引、Embedding 缓存、任务进度和恢复。

### Phase 3：混合检索

结构化统计、全文检索、向量检索、简历检索、融合重排、去重、检索缓存和岗位引用。

### Phase 4：职业顾问 Agent

会话、消息、引用、意图识别、只读工具、流式输出、上下文摘要、简历差距和学习路线。

### Phase 5：职业顾问前端

会话管理、证据面板、过滤条件、Markdown、岗位跳转、学习计划和日夜模式。

### Phase 6：质量与创新能力

评测集、Token 优化、技能邻接、趋势分析、岗位覆盖度模拟器和学习计划联动。

## 12. Phase 1 结论

建议进入下一阶段时先落地岗位版本、知识文档、知识块和增量索引的最小闭环，再实现聊天 Agent。这样可以先验证“岗位数据是否能被稳定检索和引用”，避免先完成聊天界面后发现回答没有可靠数据依据。
