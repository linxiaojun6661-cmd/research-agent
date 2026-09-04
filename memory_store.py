"""
memory_store.py — 长期记忆（第 ⑭ 步）—— RAG 向量库

调研成果入库: 报告切块 → embedding → 存入本地 JSON 向量库
下次调研先查: 同主题旧成果按余弦相似度召回，作为资料注入

复用 Stage 2 的三大件: chunk_text / get_embedding / cosine
依赖: 本机 Ollama 的 nomic-embed-text（embedding 模型）
"""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import httpx

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EMBED_MODEL = "nomic-embed-text"
OLLAMA_URL = "http://localhost:11434"


# ═══════════════════════════════════════════════════════════
# ① 三大件（Stage 2 老配方）
# ═══════════════════════════════════════════════════════════

def get_embedding(text: str) -> list[float]:
    """Ollama nomic-embed-text → 向量。"""
    r = httpx.post(f"{OLLAMA_URL}/api/embeddings",
                   json={"model": EMBED_MODEL, "prompt": text},
                   timeout=60)
    r.raise_for_status()
    return r.json()["embedding"]


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度: 两个向量的夹角余弦，1=同向 0=无关。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def chunk_text(text: str, size: int = 500) -> list[str]:
    """按段落边界切块（Stage 2 chunk_document 的简化版）。"""
    chunks, buf = [], ""
    for p in text.split("\n"):
        if len(buf) + len(p) > size and buf:
            chunks.append(buf)
            buf = p
        else:
            buf += p + "\n"
    if buf:
        chunks.append(buf)
    return chunks


# ═══════════════════════════════════════════════════════════
# ② MemoryStore —— 本地 JSON 向量库
# ═══════════════════════════════════════════════════════════

class MemoryStore:
    """持久化向量库: 一条记忆 = 文本块 + 主题 + 向量 + 时间。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.MEMORY_DIR / "memory.json"
        self.entries: list[dict] = []
        self.load()

    def load(self):
        if self.path.exists():
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self):
        self.path.write_text(json.dumps(self.entries, ensure_ascii=False),
                             encoding="utf-8")

    def add(self, topic: str, text: str) -> int:
        """切块 → embedding → 入库。返回新增块数。"""
        n = 0
        for chunk in chunk_text(text):
            self.entries.append({
                "topic": topic,
                "text": chunk,
                "embedding": get_embedding(chunk),
                "ts": datetime.now().isoformat(),
            })
            n += 1
        self.save()
        return n

    def search(self, query: str, top_k: int = 3,
               threshold: float = 0.5) -> list[tuple[float, str]]:
        """语义检索: 查询向量与所有记忆算余弦，取最相似的前 k 条。"""
        q = get_embedding(query)
        scored = [(cosine(q, e["embedding"]), e) for e in self.entries]
        scored.sort(key=lambda x: -x[0])       # 相似度降序
        hits = []
        for score, e in scored[:top_k]:
            if score < threshold:              # 低于阈值 = 不相关
                break
            hits.append((round(score, 3), e["text"][:300]))
        return hits

    def stats(self) -> str:
        return f"{len(self.entries)} 条记忆" if self.entries else "（空库）"


# ═══════════════════════════════════════════════════════════
# ③ 安全封装 —— 记忆是增强，不是刚需
# ═══════════════════════════════════════════════════════════

_store = None

def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def recall_safe(topic: str, top_k: int = 3) -> str:
    """调研前查旧成果。任何失败（Ollama 没开等）返回空串，不挡主线。"""
    try:
        hits = _get_store().search(topic, top_k=top_k)
        if not hits:
            return ""
        lines = [f"- [相似度 {s}] {text}" for s, text in hits]
        return "\n".join(lines)
    except Exception:
        return ""


def remember_safe(topic: str, report: str) -> None:
    """调研后存成果。失败静默——不因为记忆功能坏了就毁掉主流程。"""
    try:
        _get_store().add(topic, report)
    except Exception:
        pass


if __name__ == "__main__":
    # 自检: python memory_store.py
    print("═" * 50)
    print("测试 1: 纯数学部分（不需要 Ollama）")
    a = [1.0, 0.0]
    b = [1.0, 0.0]
    c = [0.0, 1.0]
    print(f"  同向向量相似度: {cosine(a, b):.2f}（应=1.0）")
    print(f"  正交向量相似度: {cosine(a, c):.2f}（应=0.0）")
    text = "\n".join([f"第{i}段内容" * 50 for i in range(5)])
    print(f"  切块测试: {len(text)} 字符 → {len(chunk_text(text))} 块")

    print("\n测试 2: Ollama 可用性")
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        print(f"  ✅ Ollama 在线，模型: {[m['name'] for m in r.json()['models']][:5]}")
        print("\n测试 3: 完整入出库（真 embedding）")
        store = MemoryStore(config.MEMORY_DIR / "memory_test.json")
        n = store.add("测试主题", "RAG 是检索增强生成，能减少大模型幻觉。")
        print(f"  ✅ 入库 {n} 块 → 检索结果:")
        for s, t in store.search("什么是检索增强"):
            print(f"    [{s}] {t[:50]}")
    except Exception as e:
        print(f"  ⚠️ Ollama 不可用（{str(e)[:50]}），跳过真 embedding 测试")
        print("    （不影响主流程: recall_safe 会静默降级）")
    print("═" * 50)
