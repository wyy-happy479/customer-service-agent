"""
Streamlit UI — 浏览器版客服 Agent

📖 核心概念：
    用 Streamlit 给 Agent 加个 Web 界面。Streamlit 是个纯 Python 的
    Web 框架，不需要写 HTML/CSS/JS，非常适合快速原型。

💡 启动方式：
    streamlit run app.py

⚠️ 常见坑点：
    Streamlit 每次交互都会重新运行整个脚本，所以 Agent 实例
    需要用 st.session_state 保持，否则每次对话都会重置。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
from config import validate_config, print_config
from database import init_database
from agent import CustomerServiceAgent


# ── 页面配置 ──
st.set_page_config(
    page_title="智能客服 Agent",
    page_icon="🤖",
    layout="wide",
)

st.title("🤖 智能客服 Agent")
st.caption("支持：查订单 | 查物流 | 退款政策 | 创建工单 | 取消订单（需确认）")

# ── 初始化（只运行一次） ──
@st.cache_resource
def init():
    """初始化数据库和配置（缓存，只运行一次）"""
    validate_config()
    init_database()
    return True

init()

# ── 会话状态管理 ──
if "agent" not in st.session_state:
    st.session_state.agent = CustomerServiceAgent()
    st.session_state.agent.verbose = False  # Streamlit 里不打印调试信息
    st.session_state.messages = []  # 聊天记录（用于显示）
    st.session_state.pending_confirmation = False

agent = st.session_state.agent

# ── 侧边栏：审计日志 ──
with st.sidebar:
    st.header("📊 审计日志")
    if st.button("刷新统计"):
        pass  # 点按钮自然触发刷新

    stats = agent.get_audit_summary()
    st.metric("总工具调用", stats.get("total_calls", 0))
    if stats.get("total_calls", 0) > 0:
        st.metric("成功率", stats.get("success_rate", "N/A"))

        st.subheader("各工具统计")
        for name, s in stats.get("tool_stats", {}).items():
            col1, col2, col3 = st.columns(3)
            col1.metric(name, f"{s['count']}次")
            col2.metric("平均耗时", f"{s['avg_ms']}ms")
            col3.metric("失败", f"{s['errors']}次")

    st.divider()
    if st.button("🔄 开始新对话"):
        agent.reset()
        st.session_state.messages = []
        st.session_state.pending_confirmation = False
        st.rerun()

# ── 主区域：聊天界面 ──
# 显示历史消息
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 待确认状态提示
if st.session_state.pending_confirmation:
    st.warning("⚠️ 请点击上方按钮确认或取消高风险操作")

# 用户输入
if user_input := st.chat_input("请输入您的问题..."):
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 处理输入
    with st.chat_message("assistant"):
        if st.session_state.pending_confirmation:
            # 高风险确认阶段
            pending = agent._pending_confirmation
            if user_input.strip() == "确认":
                reply = agent.confirm_high_risk(confirmed=True)
            else:
                reply = agent.confirm_high_risk(confirmed=False)
            st.session_state.pending_confirmation = False
        else:
            # 正常对话
            with st.spinner("思考中..."):
                reply = agent.chat(user_input)

            # 检查是否需要确认
            if hasattr(agent, '_pending_confirmation') and agent._pending_confirmation:
                st.session_state.pending_confirmation = True
                st.warning(reply)  # 确认提示用 warning 样式
                st.session_state.messages.append(
                    {"role": "assistant", "content": reply})
                st.stop()

        st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
