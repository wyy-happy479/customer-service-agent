"""
CLI 入口 — 命令行交互式客服 Agent

📖 核心概念：
    这是用户直接交互的入口。每轮对话分为三步：
    1. 用户输入 → Agent 处理
    2. 如果需要确认（取消订单等高风险操作）→ 等待用户输入"确认"/"取消"
    3. Agent 返回最终回复

💡 启动方式：
    python main.py              # 交互模式
    python main.py --once "我的订单ORD-0001到哪了"  # 单次查询
    python main.py --audit      # 查看审计日志摘要
"""

import sys
import argparse
from pathlib import Path

# 确保能找到项目根目录
sys.path.insert(0, str(Path(__file__).parent))

from config import validate_config, print_config
from database import init_database
from agent import CustomerServiceAgent
from audit import audit_logger


def interactive_mode():
    """交互式对话模式"""
    print("\n" + "=" * 60)
    print("🤖 智能客服 Agent — 交互模式")
    print("=" * 60)
    print("可用功能：查订单 | 查物流 | 退款政策 | 创建工单 | 取消订单")
    print("输入 'quit' 或 'exit' 退出")
    print("输入 'audit' 查看审计日志")
    print("输入 'reset' 开始新对话")
    print("=" * 60)

    agent = CustomerServiceAgent()

    while True:
        try:
            user_input = input("\n👤 您: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not user_input:
            continue

        # 特殊命令
        if user_input.lower() in ("quit", "exit"):
            print("👋 再见！")
            break
        if user_input.lower() == "audit":
            stats = agent.get_audit_summary()
            print("\n📊 审计日志摘要：")
            print(f"  总调用次数: {stats.get('total_calls', 0)}")
            if stats.get('total_calls', 0) > 0:
                print(f"  成功率: {stats.get('success_rate', 'N/A')}")
                for name, s in stats.get("tool_stats", {}).items():
                    print(f"  🔧 {name}: {s['count']}次, "
                          f"平均{s['avg_ms']}ms, {s['errors']}次失败")
            continue
        if user_input.lower() == "reset":
            agent.reset()
            print("🔄 对话已重置")
            continue

        # 检查是否是待确认状态
        if hasattr(agent, '_pending_confirmation') and agent._pending_confirmation:
            pending = agent._pending_confirmation
            if user_input.strip() == "确认":
                print("⏳ 正在执行...")
                reply = agent.confirm_high_risk(confirmed=True)
            else:
                print("❌ 操作已取消")
                reply = agent.confirm_high_risk(confirmed=False)
            print(f"\n🤖 客服: {reply}")
            continue

        # 正常对话
        print("⏳ 思考中...")
        reply = agent.chat(user_input)
        print(f"\n🤖 客服: {reply}")

        # 检查是否需要用户确认
        if hasattr(agent, '_pending_confirmation') and agent._pending_confirmation:
            print("\n" + "-" * 40)
            print("⚠️  请输入「确认」执行，或其他任意内容放弃")
            print("-" * 40)


def once_mode(query: str):
    """单次查询模式"""
    validate_config()
    init_database()
    agent = CustomerServiceAgent()
    agent.verbose = False  # 单次模式不打印调试信息
    reply = agent.chat(query)
    print(reply)


def audit_mode():
    """查看审计日志"""
    stats = audit_logger.get_stats()
    print("\n📊 审计日志摘要")
    print("=" * 40)
    print(f"总调用次数: {stats.get('total_calls', 0)}")
    if stats.get('total_calls', 0) > 0:
        print(f"成功率: {stats.get('success_rate', 'N/A')}")
        print("\n各工具统计：")
        for name, s in stats.get("tool_stats", {}).items():
            print(f"  🔧 {name}:")
            print(f"     调用: {s['count']} 次")
            print(f"     平均耗时: {s['avg_ms']} ms")
            print(f"     失败: {s['errors']} 次")

    # 显示最近日志
    logs = audit_logger.get_recent_logs(10)
    if logs:
        print(f"\n📜 最近 {len(logs)} 条记录：")
        for log in logs:
            icon = "✅" if log["success"] else "❌"
            risk_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                log["risk_level"], "⚪")
            print(f"  {icon} {risk_icon} {log['timestamp']} | "
                  f"{log['tool_name']} | {log['duration_ms']}ms")
            if log.get("confirmed_by_user"):
                print(f"     👤 用户已确认")


def main():
    parser = argparse.ArgumentParser(description="🤖 智能客服 Agent")
    parser.add_argument("--once", type=str, help="单次查询模式")
    parser.add_argument("--audit", action="store_true", help="查看审计日志")
    parser.add_argument("--init-db", action="store_true", help="(重新)初始化数据库")
    args = parser.parse_args()

    # 校验配置
    if not validate_config():
        sys.exit(1)

    # 初始化数据库
    if args.init_db:
        import os
        from config import DB_PATH
        if DB_PATH.exists():
            os.remove(DB_PATH)
            print("🗑️  旧数据库已删除")
    init_database()

    print_config()

    # 路由到对应模式
    if args.audit:
        audit_mode()
    elif args.once:
        once_mode(args.once)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
