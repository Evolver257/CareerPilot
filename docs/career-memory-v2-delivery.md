# CareerPilot 长期记忆 V2 实施说明

## 本次完成

- 在现有 `AgentMemory`、`MemoryCandidate` 上增量增加结构化职业事实、记忆类别、稳定性、重要性、生命周期状态、来源证据、提取方式、版本链、固定标记和使用次数。
- 新增 `0030_agent_memory_v2` 迁移。旧记录保留原内容，并补齐默认 key、结构化值、来源证据和 ACTIVE 状态；SQLite upgrade/downgrade 已验证。
- 新增 LLM 结构化候选提取。只接受用户原文中的连续 `source_quote`，安全检查、置信度阈值、候选数量上限和异常降级均在服务层执行；LLM 不直接写入记忆。
- 保留明确第一人称规则提取作为无 LLM 或 LLM 失败时的降级路径。
- 按 `memory_key` 进行 SAME、EXTENDS、UPDATES、CONFLICTS、UNRELATED 的基础属性级判断；用户确认更新会建立 `supersedes_id` 链，旧版本变为 SUPERSEDED。
- 召回增加 ACTIVE、用户、允许类型、有效期和确认状态过滤，使用词法 + 同签名 Embedding + 新鲜度 + 置信度 + 固定/确认加权，并受动态 token budget 限制。
- 职业顾问规划器增加记忆路由字段；仅在规划器判断需要时召回指定类型/key，冲突候选对应的旧记忆不会静默注入回答。
- 新增 `memory_embedding_runs` 与 `0031_memory_embedding_runs`，复用 BackgroundWork/Worker 支持全量/增量回填、逐条进度持久化、取消、失败重试和服务重启恢复。
- 前端记忆面板增加自动保存、允许类型、未确认记忆参与回答、会话摘要开关、预算、回填进度、状态/提取来源筛选、结构化证据、固定、过时、版本历史和回答中的个人记忆标记。

## 关键安全边界

- 长期记忆默认关闭、自动保存默认关闭、未确认记忆默认不参与回答。
- 职业目标、用户画像、岗位偏好、用户确认事实等高影响内容始终需要用户确认。
- 敏感信息和疑似 Prompt Injection 在候选生成前后均会被拒绝。
- 记忆只作为数据上下文注入，不能改变系统权限、触发写工具或绕过审批。
- 岗位知识库与用户个人记忆分开检索和展示。

## 当前限制

- PostgreSQL 生产环境当前沿用有界候选集的兼容实现；尚未在本次改造中加入记忆表的 pgvector ANN/FTS 专用 SQL 查询，后续可在不改变服务契约的情况下替换检索实现。
- 会话摘要目前是受控的短摘要候选，不保存完整对话；尚未加入独立的摘要 LLM 评测集。
- 尚未建立真实人工标注的 Memory Evaluation 金标，因此不能据此宣称 Candidate Precision、Recall、MRR 或回答质量已经达标。

## 验证结果

- 后端：`274 passed, 10 skipped`；追加的 V2 定向测试全部通过。
- 前端：`40 passed`。
- 前端 TypeScript 类型检查、ESLint 和 Next.js 生产构建全部通过。
