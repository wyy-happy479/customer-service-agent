"""
Tool Call Trace — 审计日志模块

📖 核心概念：
    每一次工具调用都记录：谁调的、什么时候、什么工具、什么参数、
    返回了什么、花了多久、成功还是失败。

🔍 底层原理：
    JSONL 格式（JSON Lines）：每行是一个独立的 JSON 对象。
    好处：
    - 追加写入不破坏文件结构（对比：JSON 数组追加需要重写整个文件）
    - 可以逐行读取，不需要一次性加载全部（适合日志量大的场景）
    - 用 tail/grep 就能分析，不需要专门的日志系统

💡 为什么需要它：
    面试核心亮点！生产环境的 Agent 必须有审计日志：
    - 排查问题：用户说"Agent 给我查错了"→ 翻日志看哪步出问题
    - 成本分析：每个工具调用花了多少 token / 多少时间
    - 合规要求：谁在什么时候取消了订单（不可逆操作必须有记录）
    - 性能优化：哪个工具最慢？哪个工具错误率最高？
"""

import json
import time
from pathlib import Path
from datetime import datetime
from config import AUDIT_LOG_PATH


class AuditLogger:
    """
    工具调用审计日志。

    用法：
        logger = AuditLogger()
        logger.log(
            tool_name="query_order",
            params={"order_id": "ORD-0001"},
            result={"success": True, "data": {...}},
            duration_ms=12.5,
            success=True,
        )
    """

    def __init__(self, log_path: Path = AUDIT_LOG_PATH):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        tool_name: str,
        params: dict,
        result: dict,
        duration_ms: float,
        success: bool,
        risk_level: str = "low",
        confirmed_by_user: bool = False,
        permission: str = "read",
    ):
        """
        写入一条审计日志。

        Args:
            tool_name: 工具名
            params: 调用参数
            result: 工具返回结果
            duration_ms: 执行耗时（毫秒）
            success: 是否成功
            risk_level: 风险等级（low/medium/high）
            confirmed_by_user: 高风险操作是否经用户确认
            permission: 权限层级（read/write/delete/payment）
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool_name,
            "params": params,
            "result": result,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            "risk_level": risk_level,
            "permission": permission,
            "confirmed_by_user": confirmed_by_user,
        }

        # 追加写入（JSONL 格式：每行一个 JSON）
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_recent_logs(self, n: int = 20) -> list[dict]:
        """读取最近 n 条日志"""
        if not self.log_path.exists():
            return []

        logs = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))

        return logs[-n:]

    def get_stats(self) -> dict:
        """统计信息：总调用次数、成功率、各工具耗时"""
        if not self.log_path.exists():
            return {"total_calls": 0}

        logs = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))

        if not logs:
            return {"total_calls": 0}

        success_count = sum(1 for l in logs if l["success"])
        tool_stats = {}
        for l in logs:
            name = l["tool_name"]
            if name not in tool_stats:
                tool_stats[name] = {"count": 0, "total_ms": 0, "errors": 0}
            tool_stats[name]["count"] += 1
            tool_stats[name]["total_ms"] += l["duration_ms"]
            if not l["success"]:
                tool_stats[name]["errors"] += 1

        for name in tool_stats:
            s = tool_stats[name]
            s["avg_ms"] = round(s["total_ms"] / s["count"], 2)

        return {
            "total_calls": len(logs),
            "success_rate": f"{success_count / len(logs) * 100:.1f}%",
            "tool_stats": tool_stats,
        }


# 全局单例
audit_logger = AuditLogger()
