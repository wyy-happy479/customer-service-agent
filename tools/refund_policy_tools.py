"""
退款政策 RAG 查询工具

📖 核心概念：
    完整的三步 RAG 链路：
    1. Chunking — 把退款政策文档切成小块（防止过长文本损失检索精度）
    2. Embedding — 每个 chunk → 向量（千问 text-embedding-v3，1024维）
    3. 检索 — 用户问题 → 向量化 → Chroma 语义搜索 → 最相关 chunk → 返回 LLM

🔍 底层原理（ChromaDB 语义搜索）：
    用户问"无理由退货有什么条件？"
      → Embedding API 生成查询向量 q
      → Chroma 在所有文档向量 {d1, d2, ...} 中找 cosine_sim(q, di) 最大的 top_k 个
      → 返回最相关的文档片段

💡 与关键词匹配的区别：
    关键词匹配："7天"命中 → 返回"7天无理由退货"段落（精确匹配）
    语义搜索："无条件退货" → 也返回"7天无理由退货"段落（理解语义，不一定匹配原词）

    这就是 RAG 的价值——用户可能用各种说法问同一个问题，
    语义搜索能找到正确的答案，不管用词是否完全一致。

⚠️ 开发技巧：
    这里不用 ChromaDB 内置的 Embedding（它默认下载一个 79MB 的模型），
    而是手动调用千问 Embedding API 生成向量，再用 collection.add(embeddings=...) 存入。
    好处：
    - 不触发额外模型下载
    - 可控、可观测（你能看到每个 chunk 的向量维度和检索结果）
    - 面试时能讲清"Embedding → 存储 → 检索"每一步
"""

import json
import sys
from pathlib import Path
from typing import List

# 确保能找到项目根目录的 config
sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.config import Settings
from openai import OpenAI

from config import RAG_CHROMA_PATH, LLM_CONFIG

# ============================================================
# Embedding 配置 — 用千问 text-embedding-v3
# ============================================================
EMBEDDING_MODEL = "text-embedding-v3"  # 1024 维，效果好

_embedding_client = OpenAI(
    api_key=LLM_CONFIG["api_key"],
    base_url=LLM_CONFIG["base_url"],
)

COLLECTION_NAME = "refund_policy"
CHUNK_SIZE = 300       # 每个 chunk 的目标字符数（政策文档比较短，300 够了）
CHUNK_OVERLAP = 50     # chunk 之间的重叠（防止关键信息在边界被切断）
TOP_K = 3              # 检索召回数


# ============================================================
# 退款政策源文档
# ============================================================

REFUND_POLICY_DOC = """
## 7天无理由退货
购买后7天内，在商品完好、不影响二次销售的前提下，可申请无理由退货。
退回运费由买家承担。如因商品质量问题导致的退货，退回运费由卖家承担。

## 质量问题退货
商品存在质量问题的，买家可在签收后15天内申请退货退款。
退回运费由卖家承担。需提供商品瑕疵的照片或视频作为凭证。
如卖家对质量问题有争议，可申请平台介入处理，平台将在3个工作日内给出判定结果。

## 退款时效
以下退款方式对应的到账时间：
- 支付宝支付：退款在商家确认收货后 1-3 个工作日到账
- 微信支付：退款在商家确认收货后 1-3 个工作日到账
- 银行卡支付：退款在商家确认收货后 3-5 个工作日到账
- 货到付款：退款在商家确认收货后 5-7 个工作日到账，需提供收款银行账号

## 不支持退货的商品类型
以下商品类型不支持7天无理由退货，但质量问题仍可退货：
1. 定制类商品：如刻字、定制尺寸、定制图案等
2. 生鲜食品、冷冻食品、保质期短于7天的食品
3. 已激活的软件、游戏、音像制品、电子书等数字化商品
4. 个人卫生用品：如牙刷、内衣、内裤、袜子等，拆封后不支持退货
5. 已使用过的美容化妆品、护肤品

## 换货政策
签收后15天内，因质量问题可申请换货，换货产生的来回运费由卖家承担。
如因个人原因申请换货（如买错颜色、买错尺码、不喜欢等），来回运费由买家承担。
换货只支持同款商品更换，不支持换不同型号或不同商品。
如原商品已下架或无库存，可协商更换等价商品或退款处理。

## 部分退款规则
如一笔订单包含多件商品，只退其中一部分：
- 退款金额按实际退回商品的价格计算，不包含未退回商品
- 如订单使用了优惠券，退款时优惠券金额按商品价格比例分摊
- 已使用的优惠券金额不予返还
- 如订单满足包邮条件，部分退货后不再满足包邮条件的，退款时扣除发货运费

## 售后工单处理时效
- 退款工单：客服在 1-2 个工作日内审核处理
- 换货工单：客服在 1-3 个工作日内审核处理，审核通过后 48 小时内发出新商品
- 投诉工单：24 小时内首次响应，3 个工作日内给出处理方案
- 所有工单可在"我的订单-售后详情"中查看处理进度
""".strip()


# ============================================================
# Chunking — 把长文档切成小块
# ============================================================

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    递归字符切分（Recursive Character Splitter）。

    📖 原理：
        按优先级从高到低尝试分隔符，尽量保持语义单元完整。
        然后在 chunk 之间加 overlap，防止关键信息正好在切分边界被切断。

        比如："...退回运费由买家承担。"
              "如因商品质量问题导致的退货..."
        如果正好在句号后切断，第二句开头"如因商品质量..."缺少上下文。
        加了 overlap 后，第二个 chunk 也会包含前一个 chunk 最后几个句子。
    """
    separators = ["\n## ", "\n### ", "\n\n", "\n", "。", "；", "，", ". ", " "]
    chunks = _recursive_split(text, separators, chunk_size, overlap)
    return chunks


def _recursive_split(text: str, separators: List[str], chunk_size: int, overlap: int) -> List[str]:
    """递归切分核心逻辑"""
    # 如果当前文本不超过 chunk_size，直接返回
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    # 尝试用当前优先级最高的分隔符切分
    sep = separators[0] if separators else " "
    splits = text.split(sep)

    # 如果只有一个片段（即分隔符未命中），换下一个分隔符
    if len(splits) == 1 and len(separators) > 1:
        return _recursive_split(text, separators[1:], chunk_size, overlap)

    chunks = []
    current_chunk = ""

    for split in splits:
        candidate = (current_chunk + sep + split).strip() if current_chunk else split

        if len(candidate) <= chunk_size:
            current_chunk = candidate
        else:
            # 当前 chunk 已满，保存并开始新 chunk
            if current_chunk:
                chunks.append(current_chunk)

            # 如果单个片段超过 chunk_size，递归切它
            if len(split) > chunk_size:
                sub_chunks = _recursive_split(split, separators[1:] if len(separators) > 1 else [" "], chunk_size, overlap)
                chunks.extend(sub_chunks)
                current_chunk = ""
            else:
                current_chunk = split

    if current_chunk:
        chunks.append(current_chunk)

    # 加 overlap：每个 chunk 后面接上一个 chunk 的尾巴
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = chunks[i - 1][-overlap:] if len(chunks[i - 1]) > overlap else chunks[i - 1]
            overlapped.append(tail + chunks[i])
        chunks = overlapped

    return chunks


# ============================================================
# Embedding — 用千问 API 把文本变成向量
# ============================================================

def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    批量文本 → 向量。

    原理：对每条文本调 Embedding API，返回一个 1024 维的浮点数列表。
    这些数字在 1024 维空间中代表文本的语义位置。
    """
    if not texts:
        return []

    # 千问 Embedding API 限制：单次最多传 25 条
    batch_size = 20
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = _embedding_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
        )
        all_embeddings.extend([item.embedding for item in resp.data])

    return all_embeddings


def embed_single(text: str) -> List[float]:
    """单条文本向量化"""
    return embed_texts([text])[0]


# ============================================================
# ChromaDB 存储 + 检索
# ============================================================

class RefundPolicyRAG:
    """
    退款政策 RAG 引擎。

    完整的 RAG 三步：
    1. 首次启动 → chunk → embed → 存入 Chroma
    2. 每次查询 → query embed → Chroma 语义搜索 → 返回最相关 chunk
    """

    def __init__(self):
        self._ensure_data_loaded()

    def _ensure_data_loaded(self):
        """确保 ChromaDB 中有退款政策数据（幂等：已有就不重复加）"""
        # 确保目录存在
        RAG_CHROMA_PATH.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(RAG_CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )

        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        # 幂等检查：如果已经有数据，跳过导入
        if self.collection.count() > 0:
            print(f"  📚 退款政策已加载（{self.collection.count()} 个 chunk）")
            return

        # 第 1 步：Chunking
        print("  ✂️  正在切分退款政策文档...")
        chunks = chunk_text(REFUND_POLICY_DOC)
        print(f"     切分为 {len(chunks)} 个 chunk")

        # 第 2 步：Embedding
        print(f"  🔤 正在向量化（{EMBEDDING_MODEL}，1024 维）...")
        embeddings = embed_texts(chunks)
        print(f"     完成，共 {len(embeddings)} 个向量")

        # 第 3 步：存入 Chroma
        print(f"  💾 正在存入 ChromaDB（{RAG_CHROMA_PATH}）...")
        ids = [f"chunk_{i}" for i in range(len(chunks))]
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
        )
        print(f"  ✅ 退款政策 RAG 知识库构建完成！")

    def search(self, query: str, top_k: int = TOP_K) -> str:
        """
        语义搜索退款政策。

        流程：
        1. 用户问题 → 向量 q
        2. Chroma 搜 top_k 最相似的 chunk
        3. 格式化返回给 LLM
        """
        # ⚡ 用 query_embeddings 而非 query_texts（避免触发 Chroma 内置 Embedding 下载）
        query_vec = embed_single(query)

        results = self.collection.query(
            query_embeddings=[query_vec],
            n_results=top_k,
            include=["documents", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            return json.dumps({
                "status": "no_results",
                "message": "未找到相关的退款政策，建议联系人工客服确认。",
            }, ensure_ascii=False)

        # 组装检索结果
        policies = []
        for i, doc in enumerate(results["documents"][0]):
            distance = results["distances"][0][i] if results["distances"] else 0
            similarity = max(0, 1.0 - distance)  # cosine distance → similarity
            policies.append({
                "similarity": f"{similarity:.2%}",
                "content": doc,
            })

        return json.dumps({
            "status": "found",
            "query": query,
            "retrieved_count": len(policies),
            "policies": policies,
        }, ensure_ascii=False)

    def get_stats(self) -> dict:
        """返回知识库统计信息"""
        return {
            "collection_name": COLLECTION_NAME,
            "chunk_count": self.collection.count(),
            "embedding_model": EMBEDDING_MODEL,
            "storage_path": str(RAG_CHROMA_PATH),
        }


# ============================================================
# 全局单例
# ============================================================

_rag_engine: RefundPolicyRAG | None = None


def get_rag_engine() -> RefundPolicyRAG:
    """延迟初始化（首次启动时自动构建知识库）"""
    global _rag_engine
    if _rag_engine is None:
        print("  🚀 初始化退款政策 RAG 引擎...")
        _rag_engine = RefundPolicyRAG()
    return _rag_engine


def ensure_refund_policy_data():
    """返回完整退款政策文本（供 tool_registry 降级使用）"""
    return REFUND_POLICY_DOC


# ============================================================
# 快速自测
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("🧪 退款政策 RAG 自测")
    print("=" * 50)

    # 测试 chunking
    chunks = chunk_text(REFUND_POLICY_DOC)
    print(f"\n📐 Chunking: {len(chunks)} 个片段")
    for i, c in enumerate(chunks):
        print(f"  [{i}] {c[:80]}...")

    # 测试 embedding
    print("\n🔤 Embedding 测试...")
    vec = embed_single("7天无理由退货的条件是什么")
    print(f"  向量维度: {len(vec)}")
    print(f"  前5个值: {vec[:5]}")

    # 测试 RAG 引擎
    print("\n🔍 检索测试：")
    rag = RefundPolicyRAG()

    test_queries = [
        "7天无理由退货有什么条件？",
        "商品有质量问题怎么办？",
        "退款多久能到账？",
        "哪些东西不能退货？",
        "我想换一个颜色可以吗？",
    ]

    for q in test_queries:
        print(f"\n  ❓ {q}")
        result = json.loads(rag.search(q))
        if result["status"] == "found":
            for p in result["policies"]:
                print(f"    📄 [{p['similarity']}] {p['content'][:100]}...")
        else:
            print(f"    ⚠️ {result.get('message', '未找到')}")

    print(f"\n📊 知识库统计: {rag.get_stats()}")
