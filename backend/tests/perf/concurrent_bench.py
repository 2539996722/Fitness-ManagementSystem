"""#132 并发基准：10 线程 × 15 秒。

模拟 10 个用户同时打 /exercises 端点，统计总请求数 / 失败率 / 延迟分布。
不依赖 locust，纯 threading。
"""
import os
import statistics
import threading
import time
from urllib import error, request

URL = os.getenv("PERF_BASE_URL", "http://127.0.0.1:8002") + "/api/v1/exercises?page=1&page_size=24"
USERS = 10
DURATION = 15  # seconds

latencies: list[float] = []
lock = threading.Lock()
stop = threading.Event()
errors = {"http_500": 0, "http_4xx": 0, "other": 0}


def worker():
    while not stop.is_set():
        req = request.Request(URL)
        t0 = time.perf_counter()
        try:
            resp = request.urlopen(req, timeout=5)
            resp.read()
            lat = (time.perf_counter() - t0) * 1000
            with lock:
                latencies.append(lat)
        except error.HTTPError as e:
            e.read()
            with lock:
                if 500 <= e.code < 600:
                    errors["http_500"] += 1
                else:
                    errors["http_4xx"] += 1
        except Exception:
            with lock:
                errors["other"] += 1


print(f"并发基准 {URL}")
print(f"  users={USERS} duration={DURATION}s")
threads = [threading.Thread(target=worker, daemon=True) for _ in range(USERS)]
start = time.perf_counter()
for t in threads:
    t.start()
time.sleep(DURATION)
stop.set()
for t in threads:
    t.join(timeout=2)
elapsed = time.perf_counter() - start

if not latencies:
    print("没有成功样本")
    print("errors:", errors)
    raise SystemExit(1)

latencies.sort()
n = len(latencies)
p50 = latencies[n // 2]
p95 = latencies[int(n * 0.95)]
p99 = latencies[int(n * 0.99)]
total = n + sum(errors.values())
rps = n / elapsed

print(f"\n结果（{elapsed:.1f}s 实际跑）")
print(f"  总请求: {total} (成功 {n}, 失败 {sum(errors.values())})")
print(f"  RPS: {rps:.1f}")
print(f"  失败明细: {errors}")
print(f"  延迟分布:")
print(f"    avg: {statistics.mean(latencies):.1f} ms")
print(f"    p50: {p50:.1f} ms")
print(f"    p95: {p95:.1f} ms")
print(f"    p99: {p99:.1f} ms")
print(f"    max: {max(latencies):.1f} ms")

status = "OK" if p95 < 200 else "WARN"
print(f"\n[{status}] p95 = {p95:.1f} ms (threshold 200ms)")
