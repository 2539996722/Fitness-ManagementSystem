"""FitHub 关键接口压测（Locust）。

覆盖 C 端高频 + B 端中等频 5 个接口：
1. GET /api/v1/exercises              动作库分页（首页核心）
2. GET /api/v1/exercises/filters      筛选项聚合（侧栏）
3. GET /api/v1/exercises/{id}         动作详情
4. GET /api/v1/banners/active         首页公告
5. GET /api/v1/plan-templates         模板市场

使用方法：
1. 启动被测服务：uvicorn app.main:app --host 127.0.0.1 --port 8002
2. 准备一个压测用户：邮箱/密码可通过 /auth/register 或 admin 后台手动
3. 在脚本里填 BASE_URL / USER_TOKEN / ADMIN_TOKEN，或通过环境变量注入
4. 运行：
   locust -f tests/perf/locustfile.py --host=http://127.0.0.1:8002
   浏览器开 http://localhost:8089 启动压测
5. 命令行无界面跑：
   locust -f tests/perf/locustfile.py --host=http://127.0.0.1:8002 \
       --headless -u 50 -r 10 -t 60s --csv=perf_report
"""

import os
import random

from locust import HttpUser, task, between


# ============ 配置 ============

BASE_PATH = "/api/v1"

# 真实 token（生产压测必须用专用账号，别拿 admin/admin123 跑）
# 简单起见先用 .env 的 admin；生产改专用 token
USER_TOKEN = os.getenv("PERF_USER_TOKEN", "")
ADMIN_TOKEN = os.getenv("PERF_ADMIN_TOKEN", "")


class CEndUser(HttpUser):
    """C 端普通用户场景：浏览动作库 + 看详情 + 刷模板市场。

    模拟真实用户：80% 列表 + 15% 详情 + 5% 模板。
    """

    weight = 9  # 占比 9/10
    wait_time = between(1, 3)  # 用户思考时间

    def on_start(self):
        self.client.headers["Authorization"] = f"Bearer {USER_TOKEN}" if USER_TOKEN else ""

    @task(40)
    def list_exercises(self):
        """动作库分页（首页核心，每用户必点）。"""
        params = {
            "page": random.randint(1, 5),
            "page_size": random.choice([24, 48]),
        }
        # 随机加一个筛选条件
        if random.random() < 0.3:
            params["body_part"] = random.choice(["chest", "back", "legs", "shoulders", "arms"])
        if random.random() < 0.2:
            params["equipment"] = random.choice(["barbell", "dumbbell", "cable", "bodyweight"])
        if random.random() < 0.15:
            params["keyword"] = random.choice(["卧推", "深蹲", "硬拉", "推举", "划船"])
        self.client.get(f"{BASE_PATH}/exercises", params=params, name="GET /exercises")

    @task(20)
    def list_exercises_no_filter(self):
        """纯分页（不筛选），模拟大部分用户。"""
        self.client.get(
            f"{BASE_PATH}/exercises",
            params={"page": 1, "page_size": 24},
            name="GET /exercises (no filter)",
        )

    @task(15)
    def exercise_detail(self):
        """动作详情（id 从 0001-1324 随机）。"""
        # 数据集编号格式 4 位补零
        eid = f"{random.randint(1, 1324):04d}"
        self.client.get(f"{BASE_PATH}/exercises/{eid}", name="GET /exercises/{id}")

    @task(10)
    def exercise_filters(self):
        """筛选项聚合（侧栏下拉）。"""
        self.client.get(f"{BASE_PATH}/exercises/filters", name="GET /exercises/filters")

    @task(8)
    def plan_templates_market(self):
        """模板市场。"""
        self.client.get(
            f"{BASE_PATH}/plan-templates",
            params={"page": 1, "page_size": 24},
            name="GET /plan-templates",
        )

    @task(5)
    def banners_active(self):
        """首页公告（每用户每次访问都查）。"""
        self.client.get(f"{BASE_PATH}/banners/active", name="GET /banners/active")

    @task(2)
    def health(self):
        """健康检查（监控用）。"""
        self.client.get(f"{BASE_PATH}/health", name="GET /health")


class AdminUser(HttpUser):
    """B 端管理场景：登录态看数据看板、列模板。

    频次远低于 C 端，weight=1。
    """

    weight = 1
    wait_time = between(2, 5)

    def on_start(self):
        self.client.headers["Authorization"] = f"Bearer {ADMIN_TOKEN}" if ADMIN_TOKEN else ""

    @task(30)
    def dashboard_overview(self):
        self.client.get(f"{BASE_PATH}/admin/dashboard/overview", name="GET /admin/dashboard/overview")

    @task(20)
    def dashboard_ai_cost(self):
        self.client.get(
            f"{BASE_PATH}/admin/dashboard/ai-cost",
            params={"days": 7},
            name="GET /admin/dashboard/ai-cost",
        )

    @task(20)
    def admin_templates(self):
        self.client.get(
            f"{BASE_PATH}/admin/templates/queue",
            params={"status": "pending_review", "limit": 20},
            name="GET /admin/templates/queue",
        )

    @task(10)
    def dashboard_user_trend(self):
        self.client.get(
            f"{BASE_PATH}/admin/dashboard/user-trend",
            params={"days": 30},
            name="GET /admin/dashboard/user-trend",
        )


# ============ 离线跑（不需要 locust）的小基准 ============
def quick_benchmark():
    """直接 urllib 跑一遍 50 次 GET /exercises，单进程最坏情况。

    用法：python tests/perf/locustfile.py
    """
    import statistics
    import time
    from urllib import error, request

    url = os.getenv("PERF_BASE_URL", "http://127.0.0.1:8002") + f"{BASE_PATH}/exercises?page=1&page_size=24"
    headers = {"Authorization": f"Bearer {USER_TOKEN}"} if USER_TOKEN else {}

    n = 50
    latencies: list[float] = []
    print(f"基准测试 {url} ×{n}")
    for i in range(n):
        req = request.Request(url, headers=headers)
        t0 = time.perf_counter()
        try:
            resp = request.urlopen(req, timeout=5)
            resp.read()
        except error.HTTPError as e:
            e.read()
            print(f"  [{i}] HTTP {e.code}")
            continue
        except Exception as e:
            print(f"  [{i}] ERROR {e}")
            continue
        latencies.append((time.perf_counter() - t0) * 1000)

    if not latencies:
        print("没有成功样本")
        return

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    print(f"成功 {len(latencies)}/{n}")
    print(f"  avg: {statistics.mean(latencies):.1f} ms")
    print(f"  p50: {p50:.1f} ms")
    print(f"  p95: {p95:.1f} ms")
    print(f"  p99: {p99:.1f} ms")
    print(f"  max: {max(latencies):.1f} ms")

    # 性能基线参考（dev 环境，本机 MySQL）
    # - p50 < 50 ms    健康
    # - p95 < 200 ms 健康
    # - p99 > 500 ms 需要优化
    if p95 > 200:
        print("[WARN] p95 > 200 ms，建议加缓存或检查 SQL")
    else:
        print("[OK] p95 < 200 ms，达标")


if __name__ == "__main__":
    quick_benchmark()