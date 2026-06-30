# 配置参考

## 环境变量（.env）

| 变量 | 必填 | 默认值 | 说明 |
|------|:--:|------|------|
| `OPENAI_API_KEY` | ✅ | — | DashScope API Key（千问百炼），兼容 OpenAI SDK |
| `OPENAI_BASE_URL` | ❌ | `https://dashscope.aliyuncs.com/compatible-mode/v1` | API 端点 |
| `LLM_MODEL` | ❌ | `qwen-plus` | 可选: `qwen-max`（更强）、`qwen-turbo`（更快） |

## Agent 配置（config.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_iterations` | 10 | 单次对话最多调几次工具 |
| `temperature` | 0.1 | LLM 温度（低 = 确定性高，适合客服场景） |

## RAG 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CHUNK_SIZE` | 300 | 文档切分大小（字符） |
| `CHUNK_OVERLAP` | 50 | 切分重叠（防语义断裂） |
| `TOP_K` | 3 | 每次检索返回条数 |
| `EMBEDDING_MODEL` | text-embedding-v3 | 千问 Embedding 模型，1024 维 |

## 重试配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 工具执行重试 | 3 次，指数退避 1s→2s→4s | 仅网络错误重试 |
| LLM 调用重试 | 2 次，指数退避 max 10s | 仅网络错误重试 |
| 幂等记录 TTL | 3600s（1小时） | 生产环境建议改用 Redis |
