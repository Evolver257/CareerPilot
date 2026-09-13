# CareerPilot RAG Evaluation Dataset V2 验收记录

## 当前状态

V2 已完成数据快照、问题集、候选池、切分、标注存储、仲裁规则、指标和标注页面的工程实现。当前数据集状态为 `awaiting_review`，因为仓库中没有伪造任何人工标注；完成两位真人独立标注及必要仲裁后才能形成稳定 gold。

## Phase 结果

| Phase | 结果 |
|---|---|
| 1 审计 | 保留 V1 `evaluation/run.py` 与既有输出；V2 使用独立 `evaluation/rag_v2` 包 |
| 2 格式/版本 | JSONL + manifest；语料 SHA-256、版本、模型签名和参数写入报告 |
| 3 快照 | 从生产 GET 接口读取 1,535 条，1,531 条有效，去重后 1,395 条，固定 seed 抽取 400 条 |
| 4 问题/候选池 | 200 条问题；每题 30 个候选；9 个召回通道并集并记录来源 |
| 5 双人标注/仲裁 | `annotations.jsonl` 支持 draft/submitted/skipped 与原文证据；冲突写入 `adjudications.jsonl` |
| 6 指标 | Candidate Recall/Hit、Precision/Recall、nDCG、MRR、MAP、证据、引用、无答案、分片和 Bootstrap CI |
| 7 基线 | 8 个基线入口已接入；无 gold 时报告只输出 `awaiting_review`，不输出质量结论 |
| 8 报告 | `baseline_report.json` / `.md` 已生成，携带数据版本、语料哈希、模型签名、环境和 git 状态 |

## 数据快照

- `dataset_version`: `rag-v2.0.0`
- `corpus_sha256`: `eb4a1d4e4862e31efac9caed7a8ce1aae096806c67b078158f4ff406f11c3376`
- `corpus`: 400 条去重岗位
- `queries`: 200 条，train/dev/test = 120/40/40
- `candidate_pool`: 6,000 个 query-job 对
- `sampling_seed` / `split_seed`: `20260910`
- `label_status`: `awaiting_review`
- 候选池保留 9 个通道的来源集合；当前离线快照未注入线上通道结果时使用确定性的本地 fallback，并在 manifest 中显式标记，不把 fallback 分数展示给标注者

## 验证结果

- 后端全量回归：302 passed, 10 skipped；V2 + 既有评测专项：22 passed
- 前端全量回归：14 个测试文件、49 tests passed；新增标注页测试：1 passed
- 前端 TypeScript 与生产构建：passed，`/evaluations/rag-v2` 路由已生成
- V2 Python lint：passed
- V1 `evaluation-embeddings-pilot30/corpus.json` SHA-256 仍为 `6d5982710babc98bcb99e8974f69c256b9d56b236412c21b3aa15ca51231d8e5`

## 仍需真人完成

1. 两位不同标注者完成全部 6,000 个 query-job 对。
2. 对评分差 ≥2、0 vs 2/3、答案可得性冲突、硬约束冲突进行仲裁。
3. 检查加权 Cohen's Kappa；低于 0.7 时保持非稳定 gold。
4. 冻结 test 后再运行正式八路基线并发布逐题失败案例。
