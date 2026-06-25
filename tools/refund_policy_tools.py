"""
退款政策 RAG 查询工具

📖 核心概念：
    完整 RAG 链路：
    1. Chunking — 递归字符切分 + overlap
    2. Embedding — 千问 text-embedding-v3（1024 维）
    3. 检索 — MultiQueryRetriever（LangChain）生成多个变体 → 语义搜索 → 去重合并

🔍 MultiQueryRetriever vs 手写单次搜索：

    手写：
      query="那要多久" → 1 次搜索 → Chroma 返回 top 3

    MultiQueryRetriever（LangChain）：
      query="那要多久"
        → LLM 生成 3 个变体：
          "退款需要多长时间"
          "退款到账时效是多久"
          "退货退款处理需要几个工作日"
        → 3 次搜索，各返回 top 3
        → 合并去重，取 top_k 条
    覆盖面更广，命中率更高。

💡 为什么用 LangChain 而不是手写：
    - rewrite_query：手写 raw API call → 用 ChatPromptTemplate | LLM 管道（代码更短、更可读）
    - 搜索：手写单 query 搜索 → 用 MultiQueryRetriever（覆盖多角度，效果更好）
    - 面试时可以说"我理解底层原理，但工程上用成熟库更可靠"
"""

import json
import re
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.config import Settings
from openai import OpenAI

from config import RAG_CHROMA_PATH, LLM_CONFIG

# ============================================================
# Embedding 配置 — 用千问 text-embedding-v3
# ============================================================
EMBEDDING_MODEL = "text-embedding-v3"

_embedding_client = OpenAI(
    api_key=LLM_CONFIG["api_key"],
    base_url=LLM_CONFIG["base_url"],
)

COLLECTION_NAME = "refund_policy"
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
TOP_K = 3

# ============================================================
# LangChain 组件（延迟初始化，首次 search 时才创建）
# ============================================================

_langchain_llm = None       # ChatOpenAI 实例
_multi_retriever = None     # MultiQueryRetriever 实例

# 对话上下文（可选注入，用于 context-aware rewrite）
_context: str = ""


def set_search_context(text: str):
    """Agent 可选注入对话上下文（用于补全指代）"""
    global _context
    _context = text


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
# Chunking — 用 LangChain RecursiveCharacterTextSplitter
# ============================================================

from langchain_text_splitters import RecursiveCharacterTextSplitter

_chunk_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n## ", "\n### ", "\n\n", "\n", "。", "；", "，", ". ", " "],
    keep_separator=False,
)


def chunk_text(text: str) -> List[str]:
    """用 LangChain RecursiveCharacterTextSplitter 切分文档"""
    docs = _chunk_splitter.create_documents([text])
    return [doc.page_content for doc in docs]


# ============================================================
# Embedding — 千问 text-embedding-v3
# ============================================================

def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    batch_size = 20
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = _embedding_client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        all_embeddings.extend([item.embedding for item in resp.data])
    return all_embeddings


def embed_single(text: str) -> List[float]:
    return embed_texts([text])[0]


# ============================================================
# LangChain 适配：ChromaDB → BaseRetriever
# ============================================================

def _get_langchain_llm():
    """延迟初始化 ChatOpenAI（避免 import 报错）"""
    global _langchain_llm
    if _langchain_llm is None:
        from langchain_openai import ChatOpenAI
        _langchain_llm = ChatOpenAI(
            model=LLM_CONFIG["model"],
            openai_api_key=LLM_CONFIG["api_key"],
            openai_api_base=LLM_CONFIG["base_url"],
            temperature=0,
        )
    return _langchain_llm


class ChromaRetriever:
    """
    ChromaDB → LangChain Retriever 适配器。

    LangChain 的 MultiQueryRetriever 需要一个 BaseRetriever 作为底层搜索引擎。
    这个适配器把我们的 ChromaDB 向量搜索包装成 LangChain 认识的接口。
    """

    # 不需要继承 BaseRetriever，MultiQueryRetriever 接受任何有 invoke/get_relevant_documents 的对象

    def __init__(self, collection, top_k: int = TOP_K):
        self.collection = collection
        self.top_k = top_k

    def get_relevant_documents(self, query: str) -> list:
        """LangChain 标准接口：query → List[Document]"""
        from langchain_core.documents import Document

        query_vec = embed_single(query)
        results = self.collection.query(
            query_embeddings=[query_vec],
            n_results=self.top_k,
            include=["documents", "distances"],
        )

        docs = []
        if results["documents"] and results["documents"][0]:
            for i, doc_text in enumerate(results["documents"][0]):
                distance = results["distances"][0][i] if results["distances"] else 0
                docs.append(Document(
                    page_content=doc_text,
                    metadata={"similarity": max(0, 1.0 - distance)},
                ))
        return docs

    def invoke(self, query: str, **kwargs) -> list:
        """LangChain Runnable 接口"""
        return self.get_relevant_documents(query)


def _get_multi_retriever(collection):
    """延迟初始化 MultiQueryRetriever"""
    global _multi_retriever
    if _multi_retriever is None:
        from langchain.retrievers.multi_query import MultiQueryRetriever

        base_retriever = ChromaRetriever(collection, top_k=TOP_K)
        _multi_retriever = MultiQueryRetriever.from_llm(
            retriever=base_retriever,
            llm=_get_langchain_llm(),
        )
    return _multi_retriever


# ============================================================
# Query Rewrite — 用 LangChain prompt chain（替代手写 raw API）
# ============================================================

def rewrite_query(query: str, context: str) -> str:
    """
    Context-aware Query Rewrite（用 LangChain prompt chain）。

    之前手写版：
        resp = client.chat.completions.create(model=..., messages=[...])
        rewritten = resp.choices[0].message.content

    现在用 LangChain：
        chain = ChatPromptTemplate | LLM | StrOutputParser
        rewritten = chain.invoke({"context": ..., "question": ...})

    好处：
    - 不需要手动拼 messages 结构
    - ChatPromptTemplate 帮你处理 system/user 角色的模板化
    - 管道符（|）是 LangChain 的 LCEL，可读性强
    - 自动处理 retry、streaming 等细节
    """
    # 不含指代词 → 跳过改写（省钱 + 省时间）
    if not re.search(r"那|这|它|他|她|呢|吗|啊|吧", query):
        return query

    try:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "你是一个搜索查询优化助手。根据对话上下文，把用户的简短/省略问题"
             "改写成完整、独立的搜索词。只输出改写后的搜索词，不要加任何解释。"),
            ("user",
             "对话上下文：\n{context}\n\n"
             "用户问题：{question}\n\n"
             "改写后的搜索词："),
        ])

        chain = prompt | _get_langchain_llm() | StrOutputParser()
        rewritten = chain.invoke({"context": context, "question": query})
        return rewritten.strip() if rewritten else query

    except Exception:
        return query


# ============================================================
# RAG 引擎（ChromaDB 存储 + LangChain 检索）
# ============================================================

class RefundPolicyRAG:
    """
    退款政策 RAG 引擎。

    索引：首次启动 → chunk → embed → 存入 Chroma
    检索：MultiQueryRetriever（多角度变体搜索 → 去重合并）
    """

    def __init__(self):
        self._ensure_data_loaded()

    def _ensure_data_loaded(self):
        RAG_CHROMA_PATH.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(RAG_CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        if self.collection.count() > 0:
            print(f"  📚 退款政策已加载（{self.collection.count()} 个 chunk）")
            return

        print("  ✂️  正在切分退款政策文档...")
        chunks = chunk_text(REFUND_POLICY_DOC)
        print(f"     切分为 {len(chunks)} 个 chunk")

        print(f"  🔤 正在向量化（{EMBEDDING_MODEL}，1024 维）...")
        embeddings = embed_texts(chunks)
        print(f"     完成，共 {len(embeddings)} 个向量")

        print(f"  💾 正在存入 ChromaDB（{RAG_CHROMA_PATH}）...")
        ids = [f"chunk_{i}" for i in range(len(chunks))]
        self.collection.add(ids=ids, embeddings=embeddings, documents=chunks)
        print(f"  ✅ 退款政策 RAG 知识库构建完成！")

    def search(self, query: str, top_k: int = TOP_K) -> str:
        """
        检索退款政策。

        流程：
        ① （如有上下文）LangChain rewrite → 补全指代
        ② MultiQueryRetriever → 生成多个变体 → 搜索 → 去重合并
        ③ 格式化返回 JSON

        MultiQueryRetriever 做的事：
          query="那要多久"
            → LLM 生成 3 个变体："退款需要多长时间" / "退款到账时效" / ...
            → 每个变体分别向量搜索
            → 合并去重，取最相关的 top 条
        """
        original_query = query

        # ① Context-aware rewrite（用 LangChain prompt chain，替代手写 API call）
        if _context:
            rewritten = rewrite_query(query, _context)
            if rewritten and rewritten != query:
                query = rewritten

        # ② MultiQueryRetriever：多角度变体搜索
        try:
            retriever = _get_multi_retriever(self.collection)
            docs = retriever.invoke(query)  # 返回 List[Document]
        except Exception:
            # LangChain 不可用时降级为单次搜索
            docs = ChromaRetriever(self.collection, top_k=top_k).invoke(query)

        if not docs:
            return json.dumps({
                "status": "no_results",
                "message": "未找到相关的退款政策，建议联系人工客服确认。",
            }, ensure_ascii=False)

        # ③ 格式化返回
        policies = []
        for doc in docs[:top_k]:
            sim = doc.metadata.get("similarity", 0)
            policies.append({
                "similarity": f"{sim:.2%}" if isinstance(sim, float) else str(sim),
                "content": doc.page_content[:500],
            })

        return json.dumps({
            "status": "found",
            "query": query,
            "original_query": original_query if original_query != query else None,
            "retrieved_count": len(policies),
            "policies": policies,
        }, ensure_ascii=False)

    def get_stats(self) -> dict:
        return {
            "collection_name": COLLECTION_NAME,
            "chunk_count": self.collection.count(),
            "embedding_model": EMBEDDING_MODEL,
            "storage_path": str(RAG_CHROMA_PATH),
            "retriever": "MultiQueryRetriever (LangChain)",
        }


# ============================================================
# 全局单例
# ============================================================

_rag_engine: RefundPolicyRAG | None = None


def get_rag_engine() -> RefundPolicyRAG:
    global _rag_engine
    if _rag_engine is None:
        print("  🚀 初始化退款政策 RAG 引擎...")
        _rag_engine = RefundPolicyRAG()
    return _rag_engine


def ensure_refund_policy_data():
    return REFUND_POLICY_DOC


# ============================================================
# 快速自测
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("🧪 退款政策 RAG 自测（LangChain MultiQueryRetriever）")
    print("=" * 50)

    chunks = chunk_text(REFUND_POLICY_DOC)
    print(f"\n📐 Chunking: {len(chunks)} 个片段")

    print("\n🔤 Embedding 测试...")
    vec = embed_single("7天无理由退货的条件是什么")
    print(f"  向量维度: {len(vec)}")

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
