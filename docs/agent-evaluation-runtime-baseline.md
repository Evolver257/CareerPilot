# CareerPilot Agent 评测与运行时基线

更新时间：2026-09-07

## 审计结论

改造前已经存在 Tool Manifest、调用前校验、结果语义校验、步骤事件、基础重试和
RAG 检索对照实验。稳定的 BOSS/智联采集和投递流程不在本次改造范围内，也未被
重构。

原有缺口：

- Tool Governance 的 39 个用例只验证调用前 guardrail，不评估真实工具选择、参数、
  调用顺序、最终完成率、延迟和 Token/成本。
- RAG 仅提供 Recall/nDCG/MRR，规则生成标签属于 silver data，不是双人复核金标。
- OpenAI/Anthropic 尚无统一 Tool Message；没有 MCP Client 和动态工具隔离层。
- AgentStep 可记录步骤，但不存在独立、幂等、可审计的 tool invocation 记录。
- 现有 Agent Run 在请求内执行，尚未进入 BackgroundWork 的租约/心跳恢复队列。
- 不存在隐私可控的长期语义记忆表和用户管理界面。

## 本轮已落地

1. 新增版本化 Tool/RAG 评测 Schema，并阻止未双人标注、未裁决的数据被标记为
   human gold。
2. 新增工具选择 Precision/Recall/F1、必要工具召回、顺序成功、参数字段与整调用准确率、
   禁止/缺失/重复/多余/无效调用率、任务完成率、P50/P95、Token 与成本指标。
3. RAG 新增 Precision@K、Hit Rate、Context Precision/Recall、Hard Negative Rejection、
   No-answer retrieval accuracy；回答评测支持 Faithfulness、Citation Correctness、
   Answer Relevancy 和 Refusal Accuracy 的外部标注聚合。
4. 评测输出采用时间戳目录，记录数据集哈希、Git commit/dirty、随机种子、环境和标签状态，
   不覆盖历史结果。
5. 新增 OpenAI/Anthropic 原生工具协议适配和统一状态模型。
6. 新增官方 MCP Python SDK Client：Streamable HTTP/stdio、动态 ListTools、CallTool、连接级
   namespace、默认禁用、工具白名单、远端 HTTPS、输入 Schema 再校验。
7. 新增 `agent_tool_invocations`，持久化 call ID、幂等键、参数、结果、错误、重试属性和耗时；
   提供 `/api/agent-runs/{run_id}/tool-invocations` 查询接口。
8. 新增全局 Deadline 和工具超时预算、错误分类、有界指数退避策略基础组件。

## 可复现基线

- 旧 Tool Governance：39/39 通过。该数字只代表调用前策略回归，不代表端到端 Agent 准确率。
- 完整 API 回归：230 passed, 10 skipped。
- 数据库迁移：`0026_agent_tool_protocol (head)`。
- 运行健康：API/PostgreSQL/Redis 正常，worker 正常启动。

种子集位于 `services/api/evaluation/datasets/tool_calls_seed_v1.jsonl`，其状态明确为
`seed_requires_dual_review`。完成双人独立标注和第三方裁决后，才允许使用
`--require-gold` 输出正式质量结论。

## 后续增量（2026-09-07）

- 职业顾问现已优先使用 OpenAI Function Calling / Anthropic Tool Use；Provider 不支持或
  原生调用失败时，才显式降级到旧结构化 JSON 决策。
- Agent Run 已可进入 BackgroundWork，保留 Checkpoint，并依据原始 started_at 计算剩余
  Deadline；重复入队由现有唯一工作单元约束拦截。
- RAG 已开放 RRF k、Dense/Sparse 权重，新增分阶段消融、graded nDCG、Hard Negative、
  false evidence 和回答引用完整性评测。
- 长期记忆默认关闭；已支持候选确认、敏感信息拒绝、语义/词法检索、TTL、软删除恢复、
  编辑、批量删除和导出，并在设置页提供用户控制。
- MCP 连接现已持久化并按用户隔离，凭据加密、默认禁用；支持 HTTPS Streamable HTTP、
  运维白名单内的 Stdio、动态工具发现、Schema Hash 和工具失效标记。

当前完整回归为 `271 passed, 10 skipped`；前端为 `39 passed`，lint、类型检查和生产构建
通过；浏览器扩展的 TypeScript 检查和 production build 通过。数据库迁移为
`0029_evaluation_runs (head)`。

后续安全与可靠性收尾包括：职业顾问仅装载启用、未过 TTL、且属于只读权限域的 MCP
工具；MCP 结果进入回答前会截断并标记为不可信外部数据；HTTP 连接执行生产调用前检查
DNS 解析结果，拒绝私网、回环、链路本地及保留地址。Agent Runtime 恢复时会复用已成功
调用的结果，对状态不明确的非幂等写操作停止自动重放。

仍然没有可合法声称为人工金标的质量分数。真实历史问题脱敏、两人独立标注和第三方裁决
属于数据治理工作，不能由代码或模型自行伪造；正式结果必须在这些数据到位后使用
`--require-gold` 运行。
