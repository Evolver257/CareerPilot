# CareerPilot RAG 人工金标评测集 V2

这是独立于 V1 的版本化 RAG 评测数据集。`corpus.jsonl` 是只读生产岗位接口的快照；`queries.jsonl` 只描述求职信息需求，不包含自动金标；`candidate_pool.jsonl` 是多个召回通道的并集。

## 状态约定

初始状态为 `awaiting_review`。正则、向量检索、LLM 预标注都只能作为 silver/prelabel，不能进入正式质量结论。只有每个 query-job 对由两位不同标注者独立提交、冲突经过仲裁，并且加权 Cohen's Kappa ≥ 0.7 后，才能将报告标记为稳定金标。

## 文件

| 文件 | 用途 |
|---|---|
| `corpus.jsonl` | 固定去重岗位快照，包含完整 JD 与分层字段 |
| `corpus_manifest.json` | 版本、哈希、抽样种子、去重和分布信息 |
| `queries.jsonl` | 200 条可扩充求职问题，含 split 与人工复核标记 |
| `candidate_pool.jsonl` | 每题 20–40 个候选岗位及召回通道来源 |
| `annotations.jsonl` | 两位标注者的原始独立标注，可暂停恢复 |
| `adjudications.jsonl` | 冲突仲裁记录 |
| `splits.json` | 按模板组冻结的 train/dev/test 切分 |
| `baseline_report.json/.md` | 当前基线的可复现运行记录；无金标时只输出 awaiting_review |

## 生成与复现

在 `services/api` 目录运行：

```text
python -m evaluation.rag_v2.cli --api http://127.0.0.1:8010 --sample-size 400 --seed 20260910
```

全量快照：

```text
python -m evaluation.rag_v2.cli --all --seed 20260910
```

快照只执行岗位读取请求，不写入岗位生产表；V1 的 `outputs/evaluation-*` 文件不会被覆盖。

## 标注页面

开发环境打开 `/evaluations/rag-v2`。输入标注者 ID 后，页面按题目和候选岗位显示结构化条件、完整 JD 与证据输入。模型分数不返回到标注视图。数字键 `0`–`3` 和 `-` 设置相关性，`Ctrl/Cmd+Enter` 暂存并进入下一条，左右方向键切换候选。
