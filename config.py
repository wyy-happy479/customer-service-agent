"""
项目配置 — 所有可配置项集中管理

📖 核心概念：为什么要把配置集中起来？
   - 散落在各文件的硬编码常量 = 改一个要翻遍所有文件
   - 集中管理 + 环境变量注入 = 改一处就生效，部署时也不用改代码

🔍 底层原理：
   python-dotenv 做的事很简单：
   1. 读取 .env 文件的每一行
   2. 解析 KEY=VALUE
   3. 写入 os.environ（优先不覆盖已有的）
   所以你在系统环境变量里设的 OPENAI_API_KEY 不会被 .env 覆盖。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env（不覆盖系统环境变量）
load_dotenv()

# ============================================================
# 项目路径
# ============================================================
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "customer_service.db"
AUDIT_LOG_PATH = DATA_DIR / "audit_log.jsonl"
# 退款政策 RAG 的 ChromaDB 存储路径（本项目独立管理，不依赖项目2）
RAG_CHROMA_PATH = DATA_DIR / "chroma_rag"

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# LLM 配置（千问百炼 DashScope — 兼容 OpenAI 接口）
# ============================================================
LLM_CONFIG = {
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "base_url": os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "model": os.getenv("LLM_MODEL", "qwen-plus"),  # qwen-plus 性价比高，qwen-max 能力强
    "temperature": 0.1,    # Agent 场景用低温度，减少随机性
    "max_tokens": 2048,
}

# ============================================================
# Agent 配置
# ============================================================
AGENT_CONFIG = {
    "max_iterations": 10,   # 最多连续调几次工具（防无限循环）
    "verbose": True,         # 是否打印调试信息
}

# ============================================================
# 工具分级配置
# ============================================================
# 高风险工具：执行前需要用户二次确认
HIGH_RISK_TOOLS = [
    "cancel_order",         # 取消订单 — 不可逆操作
]

# 中等风险工具：记录但不拦截
MEDIUM_RISK_TOOLS = [
    "create_ticket",        # 创建工单 — 可撤回但不建议滥用
]

# ============================================================
# 校验规则
# ============================================================
VALIDATION_RULES = {
    "order_id": {
        "pattern": r"^ORD-\d{4}$",
        "example": "ORD-0001",
        "message": "订单号格式应为 ORD-XXXX（4位数字），如 ORD-0001",
    },
    "phone": {
        "pattern": r"^1[3-9]\d{9}$",
        "example": "13800138000",
        "message": "手机号应为11位中国大陆手机号",
    },
}


def validate_config():
    """启动时校验必要配置"""
    errors = []
    if not LLM_CONFIG["api_key"]:
        errors.append(
            "❌ OPENAI_API_KEY 未设置\n"
            "   → 请在系统环境变量中设置，或在 .env 文件中配置"
        )
    # RAG 知识库首次启动时自动构建，无需手动检查

    if errors:
        print("\n".join(errors))
        return False
    return True


def print_config():
    """打印当前配置（隐藏敏感信息）"""
    print("=" * 60)
    print("📋 当前配置")
    print("=" * 60)
    print(f"  LLM: {LLM_CONFIG['model']} @ {LLM_CONFIG['base_url']}")
    print(f"  Agent: max_iterations={AGENT_CONFIG['max_iterations']}")
    print(f"  DB: {DB_PATH}")
    print(f"  Audit: {AUDIT_LOG_PATH}")
    print(f"  RAG Chroma: {RAG_CHROMA_PATH}")
    print(f"  高风险工具: {HIGH_RISK_TOOLS}")
    print("=" * 60)
