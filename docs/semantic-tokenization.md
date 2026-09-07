# CareerPilot 语义 Token 计数

更新时间：2026-09-07

## 当前策略

- 本地 `Qwen/Qwen3-Embedding-0.6B` 通过 Sentence Transformers 加载，并直接复用模型的
  `Qwen2Tokenizer` 进行 JD 与简历 Chunk 的 Token 计数。
- Tokenizer 签名固定包含模型 revision 和 tokenizer family，写入每个 Chunk 的 metadata。
- 无法暴露 tokenizer 的远程 Embedding Provider 使用明确标记的多语言近似计数器；此时
  `token_count_exact=false`，不会把估算值伪装为精确值。
- JD 保留职责、任职条件、必备技能、加分技能、学历和经验等原有语义原子边界，单块上限为
  110 个 Embedding tokens，并保留 1400 字符安全上限。
- 简历继续按项目、经历、技能、教育等结构切块，同时增加 384-token 上限和最多 48-token
  overlap；原文按字符位置切分，避免 tokenizer decode 改写证据文本。
- LLM 对话的 Token 预算与 Embedding Token 计数相互独立。Provider 返回 usage 时以真实 usage
  为准，缺失时才使用估算值并标记来源。

## 数据回填

以下命令只更新 Token 数和 tokenizer metadata，不重算或替换 Embedding：

```text
python -m scripts.backfill_semantic_token_counts --batch-size 1000
```

脚本按批提交、可重复执行，并在当前 Provider 不提供精确 tokenizer 时拒绝运行。当前数据库已
完成 `36717/36717` 个岗位 Chunk 和 `34/34` 个简历 Chunk 的精确计数回填；第二次运行更新数为
0，验证了幂等性。知识库仍为 `ready`，岗位覆盖 `1532/1532`。

## 版本与重建边界

此次没有修改已持久化向量的 Embedding Signature，也没有强制重新切分全部 JD，因此不会让生产
知识库离线。新岗位和内容更新后的岗位会按真实 Token 边界生成 Chunk；旧 Chunk 已获得精确
Token 数，但是否重新划分边界应先用固定数据快照完成 A/B 检索评测，再执行选择性重建。
