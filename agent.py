"""
Agent 循环 — 核心引擎

📖 核心概念：
    Agent 循环就是让 LLM 反复"思考→行动→观察→思考→..."直到得出最终答案。
    这跟人类解决问题的方式一样：想一步，做一步，看结果，再想下一步。

🔍 底层原理（跟着数字走）：

    用户: "我的订单 ORD-0001 到哪了？"
      │
      ▼
    ┌──────────────────────────────────────────────────────┐
    │  第 1 次 LLM 调用（带 tools）                          │
    │  LLM 想：用户想知道物流 → 我应该调 track_logistics      │
    │  LLM 返回：tool_calls=[{name:"track_logistics",        │
    │              arguments:{order_id:"ORD-0001"}}]         │
    └──────────────────────────────────────────────────────┘
      │
      ▼
    ┌──────────────────────────────────────────────────────┐
    │  你的代码：执行工具                                     │
    │  → 查物流表 → 返回：快递在"北京分拣中心"               │
    └──────────────────────────────────────────────────────┘
      │
      ▼
    ┌──────────────────────────────────────────────────────┐
    │  第 2 次 LLM 调用（带 tools + 工具结果）                │
    │  LLM 看：工具拿到了物流信息，信息够了，不需要再调工具     │
    │  LLM 返回：stop → "您的订单当前在北京分拣中心..."       │
    └──────────────────────────────────────────────────────┘
      │
      ▼
    最终回复给用户

💡 Human-in-the-Loop 流程：

    用户: "帮我取消 ORD-0003"
      │
      ▼
    LLM 决定调 cancel_order("ORD-0003")
      │
      ▼
    你的代码：检测到 requires_confirmation → 暂停！
    → 输出确认提示 → 等待用户输入
      │
      ├── 用户输入"确认" → 真正执行 cancel_order → 返回结果给 LLM
      └── 用户输入其他 → 放弃操作 → 告诉 LLM "用户取消了"

⚠️ 常见坑点：
    1. message 格式必须严格正确（role、tool_call_id、tool_calls 结构）
       → 格式错了 OpenAI API 会返回 400 错误
    2. 不要把工具结果当最终答案（必须再调一次 LLM 转成人话）
    3. max_iterations 必须设上限（防止 LLM 死循环）
"""

import json
import time
from typing import Generator
from openai import OpenAI
from config import LLM_CONFIG, AGENT_CONFIG
from tool_registry import (
    TOOL_DEFINITIONS, TOOL_EXECUTORS,
    execute_high_risk_confirmed,
    get_risk_level, is_high_risk,
)
from validation import validate_params
from audit import audit_logger


class CustomerServiceAgent:
    """
    多工具智能客服 Agent。

    使用方式：
        agent = CustomerServiceAgent()
        agent.chat("我的订单 ORD-0001 到哪了？")
    """

    def __init__(self):
        self.client = OpenAI(
            api_key=LLM_CONFIG["api_key"],
            base_url=LLM_CONFIG["base_url"],
        )
        self.model = LLM_CONFIG["model"]
        self.max_iterations = AGENT_CONFIG["max_iterations"]
        self.verbose = AGENT_CONFIG["verbose"]

        # 对话历史（整个会话期间持续累积）
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": self._build_system_prompt()
            }
        ]

    def _build_system_prompt(self) -> str:
        """构建 system prompt — 告诉 LLM 它是谁、能做什么、规则是什么"""
        return """你是一个专业的电商客服助手。你可以帮用户：

1. **查订单** — 用户提供订单号（ORD-XXXX）或手机号，帮他们查订单详情
2. **查物流** — 用户提供订单号，帮他们追踪快递进度
3. **退款政策咨询** — 用户问退货/退款规则时，搜索知识库
4. **创建售后工单** — 帮用户提交退款/换货/投诉申请
5. **取消订单** — 取消待发货的订单（需要用户二次确认）

⚠️ 重要规则：
- 如果用户没有提供订单号，先问清订单号再查
- 如果你不确定用户要做什么，主动询问澄清
- 用友好、专业的语气回复，像真人客服一样
- 回复中涉及金额时，带上货币符号（¥）
- 如果工具返回错误，把错误原因友好地解释给用户
- 当信息足够回答用户问题时，不要再调用更多工具，直接回答
- 如果用户只是闲聊（打招呼、感谢等），直接友好回应，不要调工具"""

    def chat(self, user_message: str) -> str:
        """
        处理一条用户消息，返回 Agent 的最终回复。

        这是完整的三阶段流程：
        1. Agent 循环（LLM 自主调工具）
        2. 高风险确认（如需要）
        3. 最终回复生成
        """
        # 用户消息加入对话历史
        self.messages.append({"role": "user", "content": user_message})

        # ═══════════════════════════════════════════════
        # 阶段 1：Agent 循环
        # ═══════════════════════════════════════════════
        loop_result = self._agent_loop()

        # ═══════════════════════════════════════════════
        # 阶段 2：如果 LLM 返回了最终答案，直接返回
        # ═══════════════════════════════════════════════
        if loop_result["type"] == "final_answer":
            return loop_result["content"]

        # ═══════════════════════════════════════════════
        # 阶段 3：高风险确认（如果需要）
        # ═══════════════════════════════════════════════
        if loop_result["type"] == "needs_confirmation":
            # 返回确认提示，等待外部处理
            return loop_result["confirmation_message"]

        # 兜底
        return "抱歉，我暂时无法处理您的请求，请稍后重试或联系人工客服。"

    def confirm_high_risk(self, confirmed: bool) -> str:
        """
        用户对高风险操作的确认结果。

        Args:
            confirmed: True=确认执行, False=放弃

        调用时机：chat() 返回确认提示后，用户输入"确认"或"取消"时调用。
        """
        if not hasattr(self, '_pending_confirmation'):
            return "没有待确认的操作。"

        pending = self._pending_confirmation

        if not confirmed:
            # 用户放弃 → 把"用户放弃"作为工具结果返回给 LLM
            self._append_tool_result(
                pending["tool_call_id"],
                json.dumps({
                    "success": False,
                    "message": "用户取消了该操作，未执行。",
                }, ensure_ascii=False)
            )
            self._pending_confirmation = None

            # 重新进入 Agent 循环，让 LLM 根据"用户取消"生成回复
            result = self._agent_loop()
            if result["type"] == "final_answer":
                return result["content"]
            return "操作已取消。请问还有其他需要帮您的吗？"

        else:
            # 用户确认 → 真正执行
            tool_name = pending["tool_name"]
            params = pending["params"]

            if self.verbose:
                print(f"\n  ✅ 用户已确认，执行高风险操作: {tool_name}")

            start = time.time()
            result = execute_high_risk_confirmed(tool_name, params)
            duration = (time.time() - start) * 1000

            # 记录审计日志（标记为已确认）
            audit_logger.log(
                tool_name=tool_name,
                params=params,
                result=result,
                duration_ms=duration,
                success=result.get("success", False),
                risk_level="high",
                confirmed_by_user=True,
            )

            # 把结果返回给 LLM
            self._append_tool_result(
                pending["tool_call_id"],
                json.dumps(result, ensure_ascii=False)
            )
            self._pending_confirmation = None

            # 重新进入 Agent 循环
            loop_result = self._agent_loop()
            if loop_result["type"] == "final_answer":
                return loop_result["content"]
            return json.dumps(result, ensure_ascii=False)

    # ═══════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════

    def _agent_loop(self) -> dict:
        """
        Agent 主循环：反复调 LLM → 执行工具 → 再调 LLM → ...直到 LLM 说 stop。

        Returns:
            {"type": "final_answer", "content": "..."}   — LLM 给出最终回复
            {"type": "needs_confirmation", "confirmation_message": "..."} — 需要用户确认
        """
        for iteration in range(1, self.max_iterations + 1):
            if self.verbose:
                print(f"\n📡 [第 {iteration} 次 LLM 调用] "
                      f"上下文 {len(self.messages)} 条消息")

            # 调 LLM（带 tools）
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=TOOL_DEFINITIONS,
                temperature=LLM_CONFIG["temperature"],
            )

            choice = response.choices[0]

            # ── 情况 A：LLM 觉得信息够了，直接回答 ──
            if choice.finish_reason == "stop":
                content = choice.message.content or ""
                self.messages.append({"role": "assistant", "content": content})
                if self.verbose:
                    print(f"  ✅ LLM 决定：stop（回答用户）")
                return {"type": "final_answer", "content": content}

            # ── 情况 B：LLM 想调工具 ──
            if choice.finish_reason == "tool_calls":
                if self.verbose:
                    for tc in choice.message.tool_calls:
                        print(f"  🔧 LLM 想调: {tc.function.name}"
                              f"({tc.function.arguments})")

                # ① 把 assistant 消息写入对话历史
                self.messages.append({
                    "role": "assistant",
                    "content": choice.message.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in choice.message.tool_calls
                    ]
                })

                # ② 逐个执行工具
                for tc in choice.message.tool_calls:
                    result = self._execute_single_tool(
                        tool_call_id=tc.id,
                        tool_name=tc.function.name,
                        arguments_str=tc.function.arguments,
                    )

                    # 检查是否需要高风险确认
                    if result.get("requires_confirmation"):
                        # 暂停 Agent 循环，等用户确认
                        self._pending_confirmation = {
                            "tool_call_id": tc.id,
                            "tool_name": tc.function.name,
                            "params": json.loads(tc.function.arguments),
                        }
                        return {
                            "type": "needs_confirmation",
                            "confirmation_message": result["message"],
                        }

                    # 正常工具结果 → 写入对话历史
                    self._append_tool_result(
                        tc.id, json.dumps(result, ensure_ascii=False))

                # ③ 继续循环（LLM 可能还需要调更多工具）
                continue

            # ── 情况 C：其他（异常） ──
            if self.verbose:
                print(f"  ⚠️ 意外的 finish_reason: {choice.finish_reason}")
            break

        # 超过最大迭代次数
        return {
            "type": "final_answer",
            "content": "抱歉，处理您的请求耗时较长，请稍后重试或联系人工客服。"
        }

    def _execute_single_tool(
        self, tool_call_id: str, tool_name: str, arguments_str: str
    ) -> dict:
        """
        执行单个工具调用。

        流程：解析参数 → 校验 → 执行 → 记录审计日志
        """
        # 1. 解析参数
        try:
            params = json.loads(arguments_str)
        except json.JSONDecodeError:
            return {
                "success": False,
                "message": f"工具参数解析失败: {arguments_str}"
            }

        # 2. 参数校验（在真正执行前拦截！）
        ok, msg = validate_params(tool_name, params)
        if not ok:
            # 在这里统一打审计日志，后面的 return 就不打了
            audit_logger.log(
                tool_name=tool_name, params=params,
                result={"success": False, "message": msg},
                duration_ms=0, success=False,
                risk_level=get_risk_level(tool_name),
            )
            return {"success": False, "message": msg}

        # 3. 查找执行函数
        executor = TOOL_EXECUTORS.get(tool_name)
        if executor is None:
            return {
                "success": False,
                "message": f"未知工具: {tool_name}"
            }

        # 4. 执行（计时）
        start = time.time()
        try:
            result = executor(params)
        except Exception as e:
            result = {
                "success": False,
                "message": f"工具执行异常: {str(e)}"
            }
        duration = (time.time() - start) * 1000

        # 5. 记录审计日志
        audit_logger.log(
            tool_name=tool_name,
            params=params,
            result=result,
            duration_ms=duration,
            success=result.get("success", False),
            risk_level=get_risk_level(tool_name),
        )

        if self.verbose:
            status = "✅" if result.get("success") else "❌"
            print(f"  {status} {tool_name} 完成 ({duration:.0f}ms)")

        return result

    def _append_tool_result(self, tool_call_id: str, content: str):
        """把工具执行结果追加到对话历史"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def reset(self):
        """重置对话历史（开始新会话）"""
        self.messages = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        if hasattr(self, '_pending_confirmation'):
            del self._pending_confirmation

    def get_audit_summary(self) -> dict:
        """获取本次会话的审计摘要"""
        return audit_logger.get_stats()

    def get_recent_logs(self, n: int = 10) -> list[dict]:
        """获取最近的工具调用日志"""
        return audit_logger.get_recent_logs(n)
