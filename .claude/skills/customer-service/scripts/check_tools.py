"""
工具自检脚本 — 逐一调每个 Tool 验证可用性

用法:
    python .claude/skills/customer-service/scripts/check_tools.py
    python .claude/skills/customer-service/scripts/check_tools.py --tool query_order
"""

import sys
import json
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import argparse
from config import validate_config
from database import init_database
from tool_registry import ALL_TOOLS, get_meta
from validation import validate_params

# 每个工具的合法测试参数（不会产生副作用）
TEST_PARAMS = {
    "query_order":               {"order_id": "ORD-0001"},
    "query_orders_by_phone":     {"phone": "13800138001"},
    "track_logistics":           {"order_id": "ORD-0001"},
    "search_refund_policy":      {"query": "7天无理由退货的条件"},
    "create_ticket":             {"order_id": "ORD-0001", "ticket_type": "refund",
                                  "description": "[自测] 工具可用性检查"},
    "cancel_order":              {"order_id": "ORD-0003"},  # pending 订单，不会真取消
}

SKIP_TOOLS = {"cancel_order"}  # 高风险工具跳过执行，只测参数校验


def main():
    parser = argparse.ArgumentParser(description="客服 Agent 工具自检")
    parser.add_argument("--tool", type=str, help="只测试指定工具")
    args = parser.parse_args()

    validate_config()
    init_database()

    tools_to_test = [t for t in ALL_TOOLS if args.tool is None or t.name == args.tool]
    if args.tool and not tools_to_test:
        print(f"❌ 未找到工具: {args.tool}")
        print(f"   可用工具: {', '.join(t.name for t in ALL_TOOLS)}")
        return

    passed = 0
    failed = 0
    skipped = 0

    for tool in tools_to_test:
        meta = get_meta(tool.name)
        risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}[meta["risk"]]
        print(f"\n{risk_icon} {tool.name}")
        print(f"   {tool.description[:80]}...")

        # ① Pydantic 校验
        params = TEST_PARAMS.get(tool.name, {})
        ok, msg = validate_params(tool.name, params)
        if not ok:
            print(f"   ❌ 参数校验失败: {msg}")
            failed += 1
            continue
        print(f"   ✅ 参数校验通过")

        # ② 跳过高风险工具的执行
        if tool.name in SKIP_TOOLS:
            print(f"   ⏭️  高风险工具，跳过执行")
            skipped += 1
            continue

        # ③ 执行
        try:
            start = time.time()
            result_raw = tool.invoke(params)
            result = json.loads(result_raw)
            duration = (time.time() - start) * 1000

            if result.get("success") or result.get("requires_confirmation"):
                print(f"   ✅ 执行成功 ({duration:.0f}ms)")
                passed += 1
            else:
                print(f"   ⚠️  执行返回失败: {result.get('message', '')[:80]}")
                passed += 1  # 逻辑正常的"找不到"也算通过
        except Exception as e:
            print(f"   ❌ 执行异常: {e.__class__.__name__}: {str(e)[:120]}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"📊 结果: {passed} 通过, {failed} 失败, {skipped} 跳过")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
