"""
async_tasks.py — 异步任务（P0 补全 ②）

把长任务（完整调研 1-3 分钟）从请求线程里摘出来:
  提交 → 秒回 task_id（HTTP 202）
  后台线程执行 → 客户端轮询状态

教学版实现: 内存任务表 + threading
生产演进: 换 Celery/Redis 队列（任务表持久化 + worker 进程池），
          submit/get 的接口形状不变——这就是留好接口的意义。
"""
import threading
import uuid
from datetime import datetime

TASKS: dict = {}            # task_id -> 状态字典
_LOCK = threading.Lock()    # 多请求并发读写任务表，必须加锁（P0 并发课的点）


def submit_task(fn, *args, **kwargs) -> str:
    """提交任务: 秒回 task_id，后台线程执行 fn(*args, **kwargs)。"""
    task_id = uuid.uuid4().hex[:12]
    with _LOCK:
        TASKS[task_id] = {
            "status": "pending",
            "result": None,
            "error": None,
            "created": datetime.now().isoformat(),
        }

    def runner():
        with _LOCK:
            TASKS[task_id]["status"] = "running"
        try:
            result = fn(*args, **kwargs)
            with _LOCK:
                TASKS[task_id]["status"] = "done"
                TASKS[task_id]["result"] = result
        except Exception as e:
            with _LOCK:
                TASKS[task_id]["status"] = "failed"
                TASKS[task_id]["error"] = str(e)[:500]

    threading.Thread(target=runner, daemon=True).start()
    return task_id


def get_task(task_id: str) -> dict | None:
    return TASKS.get(task_id)


if __name__ == "__main__":
    # 自检: python async_tasks.py —— 离线，不花 API 钱
    import time

    print("═" * 50)
    print("测试 1: 正常任务 提交→轮询→完成")

    def slow_work():
        time.sleep(1.2)
        return "活儿干完了"

    tid = submit_task(slow_work)
    print(f"  提交后立即查: {get_task(tid)['status']}（期望 pending/running）")
    time.sleep(0.3)
    print(f"  0.3 秒后:     {get_task(tid)['status']}（期望 running）")
    time.sleep(1.2)
    print(f"  1.5 秒后:     {get_task(tid)['status']} = {get_task(tid)['result']}")

    print("\n测试 2: 失败任务状态")
    tid2 = submit_task(lambda: 1 / 0)      # 故意出错
    time.sleep(0.5)
    t = get_task(tid2)
    print(f"  状态: {t['status']} | 错误: {t['error'][:30]}")

    print("\n测试 3: 不存在的任务")
    print(f"  查询结果: {get_task('nonexistent')}（期望 None）")
    print("═" * 50)
