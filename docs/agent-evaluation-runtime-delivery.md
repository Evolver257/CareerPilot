# CareerPilot Agent Evaluation / Runtime / Memory 交付记录

日期：2026-09-07

## 已实现并测试

- Provider 无关的 Tool Definition、Tool Call、Tool Result 和错误/重试协议。
- OpenAI 原生 Function Calling 与 Anthropic Tool Use，显式兼容降级。
- Tool Schema 校验、权限治理、重复调用拦截、调用预算、结果验证和持久化调用记录。
- MCP Streamable HTTP / Stdio Client、动态发现、连接命名空间、工具白名单和连接级会话；
  启用且在发现 TTL 内的只读工具会进入职业顾问的原生工具选择目录。
- MCP 数据库连接管理、加密凭据、用户隔离、Schema Hash、移除工具失效标记和设置页入口。
- Agent 全局 Deadline、单工具超时、错误分类、有界指数退避、幂等键、Checkpoint、后台入队、
  取消、失败重试和 Worker 恢复入口；恢复时复用成功结果，阻止状态不明确的非幂等写操作重放。
- Tool Calling 版本化数据 Schema、双人标注一致性工具、完整指标聚合和不可覆盖的时间戳输出。
- RAG graded Recall/Precision/MRR/nDCG、Context Precision/Recall、Hard Negative、无答案和
  False Evidence 指标。
- 有边界的分阶段 RAG 消融矩阵：Chunk、Overlap、Dense/Sparse、RRF、Top-K、Reranker、
  Query Rewrite、Metadata Filter 和无答案阈值。
- Answer Evaluation：Faithfulness、Citation Correctness/Completeness、Relevancy、拒答准确率、
  False Refusal 和 Unsupported Answer；按 case_id 对齐观测，拒绝未知/重复用例，并增量保存进度。
- 受控长期记忆：默认关闭、候选确认、敏感信息/Prompt Injection 拒绝、内容哈希去重、TTL、
  Dense + Lexical + Recency + Confidence 排序、Token 限制式注入、软删除恢复和导出。
- 设置页的记忆管理与 MCP 连接管理，沿用全局日夜主题适配。
- 隐藏的 `/evaluations` 管理员评测页：数据集、后台运行、进度、取消、重试、运行对比与
  JSON/CSV/Markdown 导出、完整 RAG 参数和失败案例，不加入普通求职导航。
- MCP 描述及结果均按不可信输入处理；限制 Schema/结果大小，过滤危险凭据 Header，并在
  生产 HTTP 调用前拒绝解析到私网、回环、链路本地或保留地址的目标。
- 长期记忆对显式、高置信、非敏感且无冲突的事实支持受控自动保存；职业目标变化和冲突
  仍进入待确认候选。

## 数据库迁移

- `0026_agent_tool_protocol`：新增 `agent_tool_invocations`。
- `0027_agent_memory`：新增 `agent_memory_settings`、`agent_memories`、`memory_candidates`。
- `0028_mcp_connections`：新增 `mcp_connections`、`mcp_discovered_tools`。
- `0029_evaluation_runs`：新增 `evaluation_datasets`、`evaluation_runs`，并复用
  `background_work` 的 Lease/Fencing 队列。

四次迁移均有 downgrade，已在现有 PostgreSQL 数据库升级到 head。

## 验证结果

- API：271 passed，10 skipped。
- Web：39 passed；TypeScript、ESLint、Next.js production build 通过。
- Extension：TypeScript 检查与 Chrome MV3 production build 通过。
- 运行：API 健康检查 200；PostgreSQL、Redis、API、Worker、Web 容器正常。
- 迁移：`0029_evaluation_runs (head)`。

Skipped 项为需要 PostgreSQL 并发/故障注入环境的测试，不被描述为已通过。

## 已实现但缺少真实数据验证

- MCP 动态发现已通过本地 Mock Client 测试，尚未接入用户提供的真实第三方 MCP Server。
- OpenAI/Anthropic 消息转换与解析已测试，端到端质量仍取决于用户模型、Prompt 和真实问题集。
- RAG 消融框架可重复运行，但 Chunk Size/Overlap 的比较需要为每个候选配置建立独立索引快照；
  不允许在同一个生产索引上伪装成完整消融。
- Memory 的向量召回会复用当前 Qwen Embedding；数据量上升后应把 Python 候选排序切换为
  pgvector ANN，并继续保持 user_id 前置过滤。

## 尚未完成的外部工作

- 真实用户问题脱敏与至少两名人工标注者的独立标注、冲突仲裁。
- 用固定岗位数据快照执行修改前/修改后正式质量对比。现有修改前记录仅为工程回归基线，
  不能逆向伪造工具准确率或人工 RAG 指标。
- 生产 MCP 凭据轮换、DNS 解析与实际连接之间的强制地址绑定/出口代理，以及组织级高风险
  权限审批。当前已拒绝解析结果中的私网等危险地址，但最终生产边界仍建议由网络层兜底。
- 真实金标评测仍需人工数据治理；在线控制台和 CLI 都会阻止把待标注种子集作为正式金标运行。
- 职业顾问现有 SSE 回答仍是请求级流；通用 AgentRun 已支持 BackgroundWork 恢复，但“浏览器
  断线后继续回放同一段回答流”尚未升级为持久化事件流，不能描述为已经完成。

## 复现实验

在 `services/api` 下使用：

```text
python -m evaluation.run_agent_eval --dataset <tool-gold.jsonl> --observations <observed.jsonl> --output ../../outputs/agent-evaluation --require-gold
python -m evaluation.rag_ablation --dataset <rag-gold.jsonl> --observations <retrieval.jsonl> --output ../../outputs/rag-ablation --require-gold
```

种子集必须先完成双人标注与第三方裁决；`--require-gold` 会拒绝未完成仲裁的数据。

## 最终验收矩阵

### 已经实现并测试

- 架构：在现有 FastAPI、Next.js、PostgreSQL/pgvector、Redis、Worker 和职业顾问上增量扩展，
  未重写稳定的采集、投递、简历与知识库主流程。详细修改集中在 `services/api/evaluation`、
  Tool/Agent/MCP/Memory service、迁移 `0026`—`0029`、`apps/web/app/evaluations` 和设置页组件。
- Unified Tool Message：统一 Definition/Call/Result、稳定 call_id、结构化状态、错误、延迟和截断
  标记；OpenAI 映射为 `tools/tool_calls`，Anthropic 映射为 `tool_use/tool_result`，仅在 Provider
  不支持时显式记录兼容降级。
- MCP 与权限：连接、凭据、Session、namespace、发现缓存和调用均按 user_id/connection_id 隔离；
  CareerAdvisor 自动暴露范围仅限 `knowledge.read`、`resume.read`、`job.read`、
  `application.read`、`browser.read`、`external.read`。写入和高风险工具不允许模型自行授权。
- Runtime：状态推进、Deadline、工具超时、错误分类重试、带抖动退避、调用预算、Token 预算、
  Checkpoint、BackgroundWork Lease/Fencing、用户取消和失败重试均有代码与测试。幂等键包含
  run、step、tool 和规范化参数；成功结果可复用，状态不明确的写操作停止自动重放。
- Memory：默认关闭、候选确认、去重、冲突、过期、软删除/恢复、永久删除、用户隔离、敏感内容
  拒绝、受限 Prompt 注入和导出已覆盖；前端支持开关、筛选和维护。
- Evaluation：Tool Calling、RAG Ablation 和 Answer Evaluation 均支持版本化数据、双人标注约束、
  case_id 完整性、增量进度、取消、重试、对比、导出和失败案例。
- 运行数据：岗位知识库 `1532/1532` 兼容，`36717/36717` 个 Chunk 已使用
  `Qwen/Qwen3-Embedding-0.6B` 完成向量化，健康状态为 `ready`。

### 已经实现但缺少真实数据验证

- Tool Calling 种子集共 10 条，数据库标签为 `seed_requires_dual_review`；它用于验证数据管道，
  不构成人工金标，也不能据此声称 F1 达标。
- RAG 消融支持 Prompt 要求的变量和分阶段实验，但必须先冻结岗位快照并为 Chunk Size/Overlap
  建立独立索引，再由双人金标运行，当前不能给出“最优参数”。
- Answer Evaluation 能聚合 Faithfulness、引用正确/完整、相关性、拒答与 Unsupported Answer，
  但尚无人工核验后的生产分数。
- 原生 OpenAI/Anthropic 与 Mock MCP 已做自动化验证；实际延迟、Token、成本、重连表现仍取决于
  用户配置的 Provider 和真实 MCP Server。

### 只完成设计

- 生产环境建议以固定出口代理或地址绑定进一步防止 DNS rebinding；应用层目前已做解析结果检查。
- Memory 数据量显著增长后迁移到 user_id 前置过滤的 pgvector ANN；当前规模仍使用有界候选排序。
- 对真实用户问题进行脱敏、双人独立标注、第三方仲裁和定期 Judge 校准属于人工数据治理流程，
  代码只能约束其格式与准入，不能代替人类完成。

### 尚未实现

- 职业顾问 SSE 仍为请求级流，尚未将每个文本 delta 持久化为可回放事件；页面断线后可读取最终
  消息，但不能从精确断点恢复逐字流。通用 AgentRun 的后台恢复已经完成，两者不能混为一谈。
- 因缺少合法人工金标和修改前固定生产快照，尚无可发布的基线/修改后 Tool F1、RAG Recall、
  Answer Faithfulness、P95、Token/成功任务及成本对比，也没有声称达到 Phase 12 的质量阈值。

## 当前可发布结论

本轮可以发布的是评测基础设施、统一工具协议、只读 MCP 动态接入、通用 Agent 可靠性和受控
Memory；不能发布的是“真实效果已经达到目标阈值”。后者必须在人工金标、固定数据快照和真实
Provider/MCP 环境到位后，从 `/evaluations` 启动同配置对照实验，并保留全部失败案例。
