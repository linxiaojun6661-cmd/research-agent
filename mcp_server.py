"""
mcp_server.py — MCP 服务器（第 ⑬ 步）

把研报 Agent 的工具以 MCP 协议暴露:
  - 工具实现直接复用 tools.py —— 一份实现，两种协议
    （OpenAI function calling 给内部 pipeline 用，MCP 给外部 agent 用）
  - Claude Desktop / 其他 MCP 客户端可直接调用 web_search / calculator

用法:
  python mcp_server.py             # 启动（stdio 传输，给 MCP 客户端连）
  python mcp_server.py --selftest  # 自检: 进程内直连测试（老配方）
"""
import sys
import warnings

# ⚠️ 老教训: 必须在 FastMCP 导入前屏蔽 warning，否则污染 stdio 输出
warnings.filterwarnings("ignore")

from fastmcp import FastMCP

import config      # noqa: E402  加载 .env（工具需要 key）
import tools       # noqa: E402  复用工具实现

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

mcp = FastMCP("research-tools")


@mcp.tool()
def web_search(query: str) -> str:
    """Tavily 网络搜索，返回标题/URL/摘要。调研主题、查资料时使用。"""
    return tools.web_search(query)


@mcp.tool()
def calculator(expression: str) -> str:
    """安全计算数学表达式。支持 + - * / ( ) % ^。"""
    return tools.calculator(expression)


@mcp.tool()
def knowledge_base(query: str) -> str:
    """在本地知识库中搜索概念定义（大模型/智能体/RAG/MCP等）。"""
    return tools.knowledge_base(query)


def selftest():
    """自检: 子进程启动 server，MCP SDK 客户端直连验证（test_mcp_direct 老配方）。

    ⚠️ 新版 mcp SDK（fastmcp 4.x 自带）: stdio_client 收 StdioServerParameters
    而不是 Popen 对象——旧版写法已失效，这是 SDK 的破坏性变更。
    """
    import asyncio

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=[__file__],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tl = await session.list_tools()
                print(f"✅ 发现 {len(tl.tools)} 个 MCP 工具: "
                      f"{[t.name for t in tl.tools]}")
                result = await session.call_tool("calculator",
                                                 {"expression": "2^10"})
                print(f"✅ calculator(2^10) → {result.content[0].text}")
                result = await session.call_tool("knowledge_base",
                                                 {"query": "什么是MCP"})
                print(f"✅ knowledge_base(MCP) → {result.content[0].text[:40]}...")

    asyncio.run(run())


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        mcp.run()   # 默认 stdio 传输，等待 MCP 客户端连接
