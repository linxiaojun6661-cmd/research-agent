"""
tools.py — 工具层（第 ② 步）

研报 Agent 的三个工具 + 注册表:
  - web_search:      Tavily 网络搜索（研报的事实来源）
  - calculator:      安全计算器（数字处理）
  - knowledge_base:  本地知识库（项目专属概念）

设计要点:
  1. 统一接口: 每个工具入参 dict、出参 str —— LLM 直接消费文本
  2. TOOL_HANDLERS: 名字→函数 的注册表（类比你 minimal_agent 的 TOOL_MAP）
  3. TOOLS: OpenAI function calling 格式的 schema（给 LLM 看的"工具说明书"）
  4. 工具内部自管安全（calculator 字符白名单），不依赖调用方自觉
"""
import sys

import httpx

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ═══════════════════════════════════════════════════════════
# ① 网络搜索（Tavily）
# ═══════════════════════════════════════════════════════════

def web_search(query: str) -> str:
    """Tavily 搜索，返回前 N 条的「标题 + URL + 摘要」。"""
    if not config.TAVILY_API_KEY:
        return "错误: 未配置 TAVILY_API_KEY"
    try:
        # 若本机 HTTP 代理导致请求失败，可加 trust_env=False 绕过
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": config.TAVILY_API_KEY,
                "query": query,
                "max_results": config.SEARCH_RESULTS_PER_QUERY,
            },
            timeout=config.API_TIMEOUT,
        )
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return "未找到相关结果。"
        lines = []
        for r in results:
            title = r.get("title", "无标题")
            url = r.get("url", "")
            content = r.get("content", "")[:200]      # 摘要截断，省 token
            lines.append(f"- {title}\n  URL: {url}\n  {content}")
        return "\n".join(lines)
    except Exception as e:
        return f"搜索失败: {e}"


# ═══════════════════════════════════════════════════════════
# ② 安全计算器（复用 eval_harness 的修复版）
# ═══════════════════════════════════════════════════════════

def calculator(expression: str) -> str:
    """计算数学表达式。只允许数字和运算符字符（白名单模式）。"""
    allowed = set("0123456789+-*/().%^ ")
    if not all(c in allowed for c in expression):
        return "错误: 表达式包含不允许的字符。"
    try:
        # ⚠️ 老坑: Python 的 ^ 是异或不是幂！先替换成 **
        expression = expression.replace("^", "**")
        return f"{expression} = {eval(expression)}"
    except Exception as e:
        return f"计算错误: {e}"


# ═══════════════════════════════════════════════════════════
# ③ 本地知识库（研报 Agent 的领域常识）
# ═══════════════════════════════════════════════════════════

KNOWLEDGE_BASE = {
    "大模型": "大模型（LLM）是参数量巨大的深度学习模型，通过海量文本预训练获得通用语言能力。",
    "智能体": "智能体（Agent）是能感知环境、决策并执行动作的自治系统。",
    "RAG": "检索增强生成（RAG）先检索相关资料，再把资料注入提示词让模型回答，减少幻觉。",
    "MCP": "MCP（Model Context Protocol）是连接 AI 应用与外部工具/数据源的开放标准协议。",
    "向量检索": "把文本转成向量后用相似度搜索，实现语义级别的检索。",
}


def knowledge_base(query: str) -> str:
    """在本地知识库中搜索概念定义。"""
    for key, value in KNOWLEDGE_BASE.items():
        if key in query:
            return f"找到: {value}"
    return "知识库中未找到相关信息。"


# ═══════════════════════════════════════════════════════════
# ④ 注册表 —— 名字→函数，名字→schema
# ═══════════════════════════════════════════════════════════

TOOL_HANDLERS = {
    "web_search": web_search,
    "calculator": calculator,
    "knowledge_base": knowledge_base,
}

# 给 LLM 看的"工具说明书"（OpenAI function calling 格式）
TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "用 Tavily 搜索网络，返回标题/URL/摘要。调研主题、查资料时使用。",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "calculator",
        "description": "计算数学表达式。支持 + - * / ( ) % ^。",
        "parameters": {"type": "object",
                       "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "knowledge_base",
        "description": "在本地知识库中搜索概念定义（大模型/智能体/RAG/MCP等）。",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
]


def execute_tool(name: str, args: dict) -> str:
    """统一执行入口: 按名字找处理器，找不到就报错（pipeline 会用到）。"""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return f"错误: 未知工具 {name}"
    try:
        return handler(**args)
    except TypeError as e:
        return f"错误: 工具参数不正确 {e}"


if __name__ == "__main__":
    # 自检: python tools.py 逐个测试三个工具
    print("═" * 50)
    print("测试 1: calculator")
    print(" ", calculator("2^10 + 100 / 4"))
    print("\n测试 2: knowledge_base")
    print(" ", knowledge_base("什么是RAG"))
    print("\n测试 3: web_search（真实调用 Tavily）")
    r = web_search("Python 编程语言")
    print(" ", r[:300])
    print("═" * 50)
    print("✅ 工具层自检完成")
