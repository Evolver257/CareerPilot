# 评测与独立 Worker 操作手册

## 1. Worker 启动与职责

仓库根目录：

```powershell
docker compose up -d --build api worker
docker compose logs --tail=50 worker
```

API 启动时执行迁移。Compose 等 API 健康后才启动 Worker，避免首次迁移期间抢跑。独立 Worker 共用 API 的数据库、Provider 和密钥加密配置，但有自己的进程、连接池和生命周期。手动启动时若任务表尚未完成迁移，Worker 会记录错误并继续轮询，不会把启动报错当任务成功。

不用 Docker 时，在两个终端使用相同环境：

```powershell
cd services/api
python -m alembic upgrade head
# 终端一
uvicorn app.main:app --port 8010
# 终端二（同一目录、同一虚拟环境）
python -m app.worker
```

默认 `INDEPENDENT_WORKER=true`。只启动 API 不会执行排名/知识库任务。仅用于旧式本地开发时，可同时配置 `INDEPENDENT_WORKER=false`，此时不应再启动独立 Worker。Compose 明确启用独立模式，不受该回退设置影响。

### 实现语义

1. 创建业务 Run 和 `background_work` 在同一个事务中提交；唯一键 `(kind, run_id)` 去重入队。
2. Worker 使用 PostgreSQL **session advisory lock**，与业务提交共用同一专用连接。连接断开后数据库释放锁；不能用单独短连接抢锁、长连接写业务。
3. flush/commit 前检查锁所有权、持久化取消状态和重试 generation；防止旧 Worker 覆盖取消或新一代任务。
4. 每个岗位/评分阶段沿用现有持久化机制；完成队列确认丢失时根据业务终态收敛，不再执行业务。
5. 异常中断保留可恢复记录；累计领取达到 5 次后失败，要求显式重试。业务自身失败/超时沿用现有状态及重试入口。
6. 知识索引执行全局写锁，排名按 run 加锁。可增加 Worker 进程处理不同排名，但不建议无限增加数据库连接。

迁移 `0019_background_work` 会把旧的 PENDING/RUNNING 排名及 RUNNING 索引迁入队列。旧 PENDING 索引未保存是否自动启动，因此保守保留，需调用其 `/start` 入口。部署前应确认旧任务是否仍需要继续。

只读诊断 SQL：

```sql
SELECT kind, status, count(*) FROM background_work GROUP BY kind, status;
SELECT id, kind, run_id, status, attempts, generation, worker_id, updated_at, error
FROM background_work ORDER BY updated_at DESC LIMIT 20;
```

不要直接用 SQL 把运行任务改为成功；取消、重试应使用现有业务 API。恢复不保证远程请求从未重复，尤其是“远端成功、本地提交前崩溃”的窗口。

## 2. 启用真实语义模型（可选）

生产默认使用 Qwen3 语义检索。模型缓存在本机 `outputs/model-cache/`，使用 `trust_remote_code=False` 和本地 CPU 推理。Qwen3 查询使用 `query` prompt，岗位/简历文档不加 query prompt。自定义模型必须输出与 `EMBEDDING_DIMENSIONS` 一致的向量，并在切换后重建对应索引。

模型：

- Embedding：`Qwen/Qwen3-Embedding-0.6B`（1024 维）。
- Reranker：`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`。

Compose 可选配置：

```powershell
docker compose -f docker-compose.yml -f docker-compose.semantic.yml up -d --build api worker
```

此配置额外安装 CPU Torch / Sentence Transformers，挂载模型缓存，并将 API 与 Worker 的 `EMBEDDING_PROVIDER` 设为 `sentence_transformers`。首次依赖/模型下载需要网络。构建耗时和镜像体积明显增加；基础镜像不预装模型依赖。

切换后必须创建一次知识库回填，不能直接拿原 Hash 向量做真实语义查询：

```powershell
$payload = @{ mode='backfill'; force=$false; auto_start=$true } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8010/api/knowledge/index-runs -ContentType application/json -Body $payload
```

根据返回的任务 ID 查询 `/api/knowledge/index-runs/{id}`。不同模型签名会重新计算所需向量；期间语义覆盖率可能不足，不应在未完成回填时宣布切换成功。已有简历向量也应按原有简历重新解析入口更新。

直接知识库查询可以逐请求选择重排模式：

```json
{
  "query": "让模型先查企业资料再回答，需要哪些技能？",
  "retrieval_mode": "hybrid",
  "rerank_mode": "cross_encoder",
  "top_k": 8
}
```

POST `/api/knowledge/search`。`rerank_mode` 为 `none`、`local` 或 `cross_encoder`，默认 `local`。Cross-Encoder 分数不是匹配概率，也不是无答案判断阈值。

职业顾问 Agentic RAG 的管线重排使用 `RAG_RERANKER=cross_encoder`，默认 `local`。这是服务端配置，尚未增加用户界面的模型切换按钮。不要把 CPU 重排叠加到每次流式 Token；只在检索候选阶段执行。

回退使用基础 Compose 并回填原 Provider 的知识索引。旧版本知识文档保留，但查询只应使用当前模型签名；不应混用向量。

## 3. 复跑评测

在独立虚拟环境安装依赖后，从 `services/api` 执行：

```powershell
pip install -e '.[dev,semantic]'
$env:SEMANTIC_CACHE_DIR='C:/absolute/path/to/qi/outputs/model-cache'
$env:OMP_NUM_THREADS='4'
$env:MKL_NUM_THREADS='4'
# 已缓存模型时可禁止下载
$env:HF_HUB_OFFLINE='1'
python -m evaluation.run --semantic --rerank
python -m evaluation.analyze
```

默认输出 `outputs/evaluation-v1/`。首次只读获取 API 岗位；已有 `corpus.json` 时复用冻结快照，不会悄悄换数据。需要新实验时使用新的 `--output` 目录。`--api` 默认 `http://localhost:8010`，`--jobs` 默认 120。

若要严格比较两个切块或检索版本，应显式传入同一冻结语料，并把结果写到不同目录：

```powershell
python -m evaluation.run --semantic --rerank --corpus ../../outputs/evaluation-v1/corpus.json --output ../../outputs/evaluation-v3-fixed-corpus
python -m evaluation.analyze --output ../../outputs/evaluation-v3-fixed-corpus
```

运行结束后应核对两个 `manifest.json` 的 `corpus_sha256` 完全相同；不能用不同时间抓取的岗位样本宣称版本间提升。

Agent 证据充分性默认要求最高直接相关性达到 0.42。部署时可通过 `RAG_EVIDENCE_MIN_RELEVANCE` 调整，但应使用开发集校准，不能直接用测试集调阈值；阈值过低会把语义近邻当成事实，过高会增加“证据不足”的情况。

不安装模型可执行 `python -m evaluation.run --output ../../outputs/evaluation-baseline`。未能加载真实模型会记录 unavailable，绝不把 Hash 冒充真实模型结果。请求全套对照实验时，交付前必须检查 manifest 的 unavailable 是否为空以及五种模式是否齐全。

人工复核流程：审核 query 的真实意图，查看完整 JD，而不是仅看正则命中片段；修正 `relevance` 中的岗位 ID、二元 grade（0/1）与证据；保持 corpus hash 和主题拆分不变。代码校验重复问题、错误岗位、非法分数和跨集合主题泄漏。

```powershell
python -m evaluation.run --semantic --rerank --labels ../../outputs/reviewed-labels.json
```

下一轮正式金标建议：两人独立审核至少 100 个真实问题，区分核心要求和加分项，补同名技能、否定条件、时间/城市过滤、知识库缺失等难负例。报告应单列检索质量和回答忠实度，不能拿检索指标代替回答准确率。

## 4. 自动化测试

常规测试：

```powershell
cd services/api
python -m pytest -q
```

PostgreSQL 故障注入要求**隔离测试数据库**。数据库名必须以 `careerpilot_eval` 或 `test_` 开头，测试拒绝其他名称。只用测试库凭据设置 `WORKER_TEST_DATABASE_URL` 后执行：

```powershell
python -m pytest tests/test_worker_postgres.py -q --junitxml=worker-tests.xml
```

默认没有设置测试数据库地址时，这部分显示 skipped，**不能把 skipped 当作已通过**。每个测试建立独立 schema；已有 public 同名表也不会被误用。

`.github/workflows/api-reliability.yml` 配置了 PostgreSQL/pgvector、完整迁移与测试，并保留 JUnit 文件。本轮在本机执行了测试；尚未向远端推送或声称远端 CI 已运行。
