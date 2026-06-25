"""
Agent 核心引擎 — LangChain ChatOpenAI.bind_tools() + 自定义生产特性

📖 架构：

    LangChain 负责（调库）：
    - LLM 交互 — ChatOpenAI
    - 工具 Schema — @tool 装饰器
    - Tool Binding — llm.bind_tools()（自动生成 Function Calling 参数）
    - 消息格式 — HumanMessage / AIMessage / ToolMessage

    自定义层负责（LangChain 不原生支持的生产特性）：
    - Tool Routing（意图分类缩小工具集）
    - Permission 检查（read/write/delete/payment）
    - Idempotency（幂等键 + 重复检测）
    - Retry Policy（tenacity 指数退避）
    - Human-in-the-Loop（高风险操作等用户确认）
    - Audit Log（JSONL 全记录）
    - 参数校验（Pydantic）

🔍 bind_tools() vs create_tool_calling_agent()：

    bind_tools() 是 LangChain 最底层的原语——它把 @tool 对象转成 OpenAI
    Function Calling 格式，自动注入到 ChatOpenAI 的请求中。所有版本的
    LangChain 都支持。

    create_tool_calling_agent() 是高级封装——内部也是 bind_tools + prompt
    template + output parser。但它在 langchain 1.3+ 中不存在了。

    面试话术：
    "我用 LangChain 的 ChatOpenAI.bind_tools() 绑定工具，这是最标准的模式。
    在此基础上封装了生产必需的 Human-in-the-Loop、幂等、重试等横切逻辑。"
"""

import json
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage

from config import LLM_CONFIG, AGENT_CONFIG
from tool_registry import (
    ALL_TOOLS, TOOLS_BY_NAME, route_tools,
    get_permission, get_risk_level, get_high_risk_executor,
)
from validation import validate_params
from audit import audit_logger
from idempotency import make_idempotency_key, check_and_set, set_result, is_idempotent_tool
from retry import execute_with_retry


# ═══════════════════════════════════════════════════════════
# LangChain LLM（只创建一次）
# ═══════════════════════════════════════════════════════════

_llm = ChatOpenAI(
    model=LLM_CONFIG["model"],
    openai_api_key=LLM_CONFIG["api_key"],
    openai_api_base=LLM_CONFIG["base_url"],
    temperature=LLM_CONFIG["temperature"],
)

SYSTEM_PROMPT = """你是一个专业的电商客服助手。你可以帮用户：

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


# ═══════════════════════════════════════════════════════════
# CustomerServiceAgent
# ═══════════════════════════════════════════════════════════

class CustomerServiceAgent:
    """多工具智能客服 Agent — LangChain bind_tools + 生产特性"""

    def __init__(self):
        self.max_iterations = AGENT_CONFIG["max_iterations"]
        self.verbose = AGENT_CONFIG["verbose"]
        self.messages: list = [SystemMessage(content=SYSTEM_PROMPT)]
        self._pending_confirmation: dict | None = None

    def chat(self, user_message: str) -> str:
        result = self._run(user_message)
        if result["type"] == "final_answer":
            return result["content"]
        if result["type"] == "needs_confirmation":
            return result["confirmation_message"]
        return "抱歉，我暂时无法处理您的请求，请稍后重试。"

    def confirm_high_risk(self, confirmed: bool) -> str:
        if not self._pending_confirmation:
            return "没有待确认的操作。"

        pending = self._pending_confirmation
        if not confirmed:
            self._append_tool_result(
                pending["tool_call_id"],
                json.dumps({"success": False, "message": "用户取消了操作"}, ensure_ascii=False))
            self._pending_confirmation = None
            result = self._run("")
            return result.get("content", "操作已取消。")

        tool_name = pending["tool_name"]
        params = pending["params"]
        if self.verbose:
            print(f"\n  ✅ 用户已确认，执行: {tool_name}")

        start = time.time()
        executor = get_high_risk_executor(tool_name)
        result = executor(params) if executor else {"success": False, "message": f"无确认函数: {tool_name}"}
        duration = (time.time() - start) * 1000

        audit_logger.log(
            tool_name=tool_name, params=params, result=result,
            duration_ms=duration, success=result.get("success", False),
            risk_level=get_risk_level(tool_name),
            permission=get_permission(tool_name), confirmed_by_user=True,
        )
        self._append_tool_result(pending["tool_call_id"],
                                 json.dumps(result, ensure_ascii=False))
        self._pending_confirmation = None
        result = self._run("")
        return result.get("content", json.dumps(result, ensure_ascii=False))

    # ═══════════════════════════════════════════════════════
    # 核心循环
    # ═══════════════════════════════════════════════════════

    def _run(self, user_message: str) -> dict:
        """Agent 主循环 — llm.bind_tools() 替代手写 tools 参数 + messages 拼接"""

        # Tool Routing + bind_tools（LangChain 自动生成 Function Calling schema）
        routed = route_tools(user_message, verbose=self.verbose) if user_message else ALL_TOOLS
        llm = _llm.bind_tools(routed)

        # RAG 上下文注入
        from tools.refund_policy_tools import set_search_context
        ctx = []
        for m in self.messages[-6:]:
            content = getattr(m, 'content', '') or ''
            if hasattr(m, 'type'):
                ctx.append(f"{m.type.upper()}: {content[:200]}")
        set_search_context("\n".join(ctx))

        if user_message:
            self.messages.append(HumanMessage(content=user_message))

        for iteration in range(1, self.max_iterations + 1):
            if self.verbose:
                print(f"\n📡 [第 {iteration} 次 LLM 调用] "
                      f"{len(self.messages)} 条消息, {len(routed)} 个工具")

            # LangChain llm.invoke() — 自动 handle tool schemas + 消息格式
            response = llm.invoke(self.messages)

            # 无 tool_calls → final answer
            if not response.tool_calls:
                self.messages.append(response)
                if self.verbose:
                    print(f"  ✅ LLM 决定：stop")
                return {"type": "final_answer",
                        "content": response.content or ""}

            # ── 有 tool_calls → 逐个执行 ──
            if self.verbose:
                for tc in response.tool_calls:
                    print(f"  🔧 LLM 想调: {tc['name']}({tc['args']})")

            self.messages.append(response)

            for tc in response.tool_calls:
                result = self._execute_tool(tc["name"], tc["args"])

                if result.get("requires_confirmation"):
                    self._pending_confirmation = {
                        "tool_call_id": tc["id"],
                        "tool_name": tc["name"],
                        "params": tc["args"],
                    }
                    return {
                        "type": "needs_confirmation",
                        "confirmation_message": result["message"],
                    }

                self._append_tool_result(
                    tc["id"], json.dumps(result, ensure_ascii=False))

            continue

        return {"type": "final_answer",
                "content": "抱歉，处理您的请求耗时较长，请稍后重试。"}

    # ═══════════════════════════════════════════════════════
    # 工具执行流水线（Pydantic → 权限 → 幂等 → tenacity 重试 → 审计）
    # ═══════════════════════════════════════════════════════

    def _execute_tool(self, tool_name: str, args: dict) -> dict:
        # ① Pydantic 参数校验
        ok, msg = validate_params(tool_name, args)
        if not ok:
            audit_logger.log(
                tool_name=tool_name, params=args,
                result={"success": False, "message": msg},
                duration_ms=0, success=False,
                risk_level=get_risk_level(tool_name),
                permission=get_permission(tool_name),
            )
            return {"success": False, "message": msg}

        # ② 权限日志
        if self.verbose:
            print(f"  🔐 权限: {get_permission(tool_name)} | "
                  f"风险: {get_risk_level(tool_name)}")

        # ③ 幂等检查
        idempotent_key = None
        if is_idempotent_tool(tool_name):
            idempotent_key = make_idempotency_key(tool_name, args)
            cached = check_and_set(idempotent_key)
            if cached is not None:
                if self.verbose:
                    print(f"  🔁 幂等命中: {idempotent_key}")
                return cached

        # ④ 执行（LangChain tool.invoke + tenacity 重试）
        langchain_tool = TOOLS_BY_NAME.get(tool_name)
        if langchain_tool is None:
            return {"success": False, "message": f"未知工具: {tool_name}"}

        start = time.time()
        try:
            result_raw = execute_with_retry(
                lambda: langchain_tool.invoke(args),
                tool_name=tool_name, verbose=self.verbose,
            )
            result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
        except Exception as e:
            result = {
                "success": False,
                "message": f"工具执行异常: {e.__class__.__name__}: {str(e)[:200]}",
            }
        duration = (time.time() - start) * 1000

        # ⑤ 存幂等结果
        if idempotent_key and result.get("success"):
            set_result(idempotent_key, result)

        # ⑥ 审计日志
        audit_logger.log(
            tool_name=tool_name, params=args, result=result,
            duration_ms=duration, success=result.get("success", False),
            risk_level=get_risk_level(tool_name),
            permission=get_permission(tool_name),
        )

        if self.verbose:
            status = "✅" if result.get("success") else "❌"
            print(f"  {status} {tool_name} 完成 ({duration:.0f}ms)")

        return result

    def _append_tool_result(self, tool_call_id: str, content: str):
        self.messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))

    def reset(self):
        self.messages = [SystemMessage(content=SYSTEM_PROMPT)]
        self._pending_confirmation = None

    def get_audit_summary(self) -> dict:
        return audit_logger.get_stats()

    def get_recent_logs(self, n: int = 10) -> list[dict]:
        return audit_logger.get_recent_logs(n)
