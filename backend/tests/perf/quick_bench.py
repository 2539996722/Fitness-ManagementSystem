"""#132 quick_benchmark — 不依赖 locust，纯 urllib。

用法：python backend/tests/perf/quick_bench.py
"""
import os
import statistics
import time
from urllib import error, request

URL = os.getenv("PERF_BASE_URL", "http://127.0.0.1:8002") + "/api/v1/exercises?page=1&page_size=24"
N = 50

print(f"基准测试 {URL} ×{N}")
latencies: list[float] = []
errors: list[str] = []
for i in range(N):
    req = request.Request(URL)
    t0 = time.perf_counter()
    try:
        resp = request.urlopen(req, timeout=5)
        resp.read()
    except error.HTTPError as e:
        e.read()
        errors.append(f"[{i}] HTTP {e.code}")
        continue
    except Exception as e:
        errors.append(f"[{i}] ERROR {e}")
        continue
    latencies.append((time.perf_counter() - t0) * 1000)

if not latencies:
    print("没有成功样本")
    print("errors:", errors[:5])
    raise SystemExit(1)

latencies.sort()
p50 = latencies[len(latencies) // 2]
p95 = latencies[int(len(latencies) * 0.95)]
p99 = latencies[int(len(latencies) * 0.99)]
print(f"成功 {len(latencies)}/{N}")
print(f"  avg: {statistics.mean(latencies):.1f} ms")
print(f"  p50: {p50:.1f} ms")
print(f"  p95: {p95:.1f} ms")
print(f"  p99: {p99:.1f} ms")
print(f"  max: {max(latencies):.1f} ms")

# 基线
# - p50 < 50 ms    健康
# - p95 < 200 ms   健康
# - p99 > 500 ms   需要优化
status = "OK" if p95 < 200 else "WARN"
print(f"[{status}] p95 = {p95:.1f} ms (threshold 200ms)")
