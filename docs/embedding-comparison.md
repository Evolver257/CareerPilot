# Embedding 模型对比实验

实测日期：2026-09-05。

## 已完成的实验

实验脚本：`services/api/evaluation/compare_embeddings.py`。

为了不改动线上现有 384 维 pgvector 索引，实验在独立内存 SQLite 中复用生产 V3 切块器，使用同一份冻结岗位语料和同一批问题规则，直接在内存中编码与排序。当前先完成 30 个岗位、324 个知识块、80 个问题的方向性子集；标签仍是 silver 标注，未经过人工金标复核。

|方案|状态|维度|测试集 Recall@5|测试集 nDCG@5|测试集 MRR@5|查询 P50/P95|
|---|---|---:|---:|---:|---:|---:|
|Qwen/Qwen3-Embedding-0.6B dense|已实跑|1024|0.533|0.585|0.748|1207/1332 ms|
|MiniLM dense（现有基线）|已实跑|384|0.484|0.486|0.630|157/255 ms|
|MiniLM dense + 词汇混合|已实跑|384|0.593|0.605|0.741|160/202 ms|
|text-embedding-3-small|未完成|API|—|—|—|缺少 API key|
|BGE-M3 dense|未完成|1024|—|—|—|权重下载受限|
|BGE-M3 + BM25 sparse|未完成|1024|—|—|—|依赖 BGE 权重|
|BGE-M3 + BM25 + BGE reranker|未完成|1024|—|—|—|依赖 BGE 权重|

Qwen 相对 MiniLM 单路 dense 在这个子集上 Recall@5 提高 0.049、nDCG@5 提高 0.099、MRR@5 提高 0.118，但 CPU 查询 P50 约为 7.6 倍；这支持“Qwen 质量更有潜力、需要缓存/批量化”的工程判断。MiniLM 加词汇混合后质量仍优于 Qwen dense，说明岗位检索不能只依赖单路向量，技术术语应保留 sparse/lexical 通道。

首次 Qwen 文档编码耗时约 576 秒；之后通过 `.npy` 向量缓存重跑查询。这个成本必须在后台索引任务中异步执行，不能放在用户请求链路。

## 未完成项与原因

- `text-embedding-3-small`：当前环境没有 `OPENAI_API_KEY` 或 `EMBEDDING_API_KEY`。现有系统配置是 Anthropic/DeepSeek 兼容 provider，它不能冒充 OpenAI embedding，因此只记录 unavailable。
- BGE-M3：官方站点在本机获取权重连接超时，镜像可以读到模型元数据，但 2.27GB 权重未能稳定下载；脚本没有产生 BGE 假结果。
- BGE 的 sparse leg 使用了依赖无关的 BM25-style 稀疏实现，完整方案还需要 BGE-M3 dense 权重和 `BAAI/bge-reranker-v2-m3` 权重后才能量化。
- 当前结果是 30 岗位 pilot，不是 899 岗位生产结论。扩大样本时保持语料、标签和参数不变，并单独写入新输出目录。

## 复现方式

从 `services/api` 执行：

```powershell
$env:SEMANTIC_CACHE_DIR='C:/absolute/path/to/qi/outputs/model-cache'
$env:EVAL_MAX_SEQ_LENGTH='512'
$env:EVAL_BATCH_SIZE='16'
python -m evaluation.compare_embeddings `
  --corpus ../../outputs/evaluation-v3-fixed-corpus/corpus.json `
  --output ../../outputs/evaluation-embeddings-pilot30 `
  --max-jobs 30 `
  --models all
```

配置 OpenAI key 后只重跑 OpenAI：

```powershell
$env:OPENAI_API_KEY='仅在当前进程设置，不要写入仓库'
python -m evaluation.compare_embeddings `
  --corpus ../../outputs/evaluation-v3-fixed-corpus/corpus.json `
  --output ../../outputs/evaluation-embeddings-pilot30 `
  --max-jobs 30 `
  --models openai_text_embedding_3_small
```

完整 120 岗位实验去掉 `--max-jobs 30`，但 Qwen/BGE CPU 文档编码成本较高；建议在 GPU 或独立 Worker 上运行。每次重试会合并已有模型结果，不会覆盖已完成方案。

## 输出文件

- [pilot 报告](../outputs/evaluation-embeddings-pilot30/report.md)
- [pilot 指标](../outputs/evaluation-embeddings-pilot30/manifest.json)
- [逐题结果](../outputs/evaluation-embeddings-pilot30/results.json)
- [silver 标注](../outputs/evaluation-embeddings-pilot30/labels.json)

