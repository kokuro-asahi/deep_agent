# 先设置 AGENT_AUTH_TOKEN 为 /v1/auth/login 返回的 access_token
# 混合普通问题 + 攻击问题，10 并发
python scripts/benchmark_latency.py --concurrency 10 --seed 1
