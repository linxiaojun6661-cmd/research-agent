"""
config.py — 全局配置中心（第 ① 步）

研报 Agent 的所有"旋钮"集中在这一个文件:
  - LLM 接入（模型/端点/key）
  - 成本上限（token 预算/超时/重试）
  - 安全边界（域名白名单/敏感词）
  - 路径（报告/trace/记忆输出目录）

设计原则: 其他模块只 import config，绝不散落硬编码——
改一个值全局生效
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent            # research-agent/ 目录（提前定义）

# ⚠️ 必须显式指定 .env 路径: load_dotenv() 默认只找"当前运行目录"，
#    从别的目录运行程序时 key 会静默变空。显式路径 = 永远找得到。
load_dotenv(BASE_DIR / ".env")

# ═══════════════════════════════════════════════════════════
# ① 路径配置
# ═══════════════════════════════════════════════════════════
OUTPUT_DIR = BASE_DIR / "outputs"           # 生成的报告
TRACE_DIR = BASE_DIR / "traces"             # 全链路 JSONL 日志
MEMORY_DIR = BASE_DIR / "memory"            # 长期记忆（增强阶段用）

for d in (OUTPUT_DIR, TRACE_DIR, MEMORY_DIR):
    d.mkdir(exist_ok=True)                  # 启动即建好，其他模块直接写

# ═══════════════════════════════════════════════════════════
# ② LLM 配置
# ═══════════════════════════════════════════════════════════
MODEL = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
TEMPERATURE = 0.3   # 低温度 → 研报场景要稳定，不发挥

# ═══════════════════════════════════════════════════════════
# ③ 成本上限（Stage 8 清单: 错误重试 / 超时 / 成本上限）
# ═══════════════════════════════════════════════════════════
MAX_TOTAL_TOKENS = 200_000    # 单次调研总 token 预算，超了就降级
API_TIMEOUT = 60.0            # 单次 API 调用超时（秒）
MAX_RETRIES = 3               # 失败重试次数（指数退避在 cost_control 里实现）
MAX_STEPS_PER_ROLE = 8        # 单个角色最大行动步数（防死循环）
MAX_REVISE_ROUNDS = 3         # 修订循环最大轮数（Stage 4 的有界 revise）

# ═══════════════════════════════════════════════════════════
# ④ 安全边界（Stage 8 清单: 权限边界）
# ═══════════════════════════════════════════════════════════
ALLOWED_DOMAIN_PATTERNS = [
    "wikipedia.org", "python.org", "github.com",
    "stackoverflow.com", "baidu.com", "zhihu.com",
    "csdn.net", "cnblogs.com", "runoob.com",
]

SENSITIVE_PAGE_KEYWORDS = ["login", "signin", "auth", "password",
                           "pay", "checkout", "admin", "wallet"]

# ═══════════════════════════════════════════════════════════
# ⑤ 工具配置
# ═══════════════════════════════════════════════════════════
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
SEARCH_RESULTS_PER_QUERY = 5    # 每次搜索返回条数
MAX_PAGE_CHARS = 6000           # 单页抓取截断长度（控制成本）

# ═══════════════════════════════════════════════════════════
# ⑥ 服务安全（P0: 鉴权 + 限流）
# ═══════════════════════════════════════════════════════════
API_TOKEN = os.getenv("API_TOKEN", "")    # 为空 = 不启用鉴权（本地开发方便）
RATE_LIMIT_PER_MINUTE = 30                # 普通接口每 IP 每分钟上限
RESEARCH_RATE_LIMIT = 3                   # /research 更严格（每次调用都花钱）


if __name__ == "__main__":
    # 自检: python config.py 直接运行，验证配置加载
    print("═" * 50)
    print("✅ 配置加载成功")
    print(f"  模型: {MODEL} @ {BASE_URL}")
    print(f"  DeepSeek key: {'✅ 已配置' if DEEPSEEK_API_KEY else '❌ 缺失'}")
    print(f"  Tavily key:   {'✅ 已配置' if TAVILY_API_KEY else '❌ 缺失'}")
    print(f"  报告目录: {OUTPUT_DIR}")
    print(f"  trace目录: {TRACE_DIR}")
    print(f"  token 预算: {MAX_TOTAL_TOKENS:,} / 单次调研")
    print(f"  白名单域名: {len(ALLOWED_DOMAIN_PATTERNS)} 个")
    print("═" * 50)
