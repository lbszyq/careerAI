"""实况 HTTP 契约检查（QA，只读）：对运行中的后端服务做真实请求验证。

前置：本地已启动 uvicorn（真实 PostgreSQL + Redis），alembic 已 upgrade head。
用法：python tests/qa/qa_live_http_check.py
"""
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt

BASE = os.environ.get("QA_LIVE_BASE", "http://127.0.0.1:8000")
API = f"{BASE}/api/v1"
JWT_SECRET = os.environ.get("QA_LIVE_JWT_SECRET", "qa-tc008-live-secret-0123456789abcdef")

results: list[dict] = []


def record(name, ok, detail, expect=None, actual=None):
    results.append({"name": name, "ok": ok, "expect": expect, "actual": actual, "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def make_expired_token(sub):
    now = datetime.now(UTC)
    payload = {"sub": str(sub), "type": "access", "iat": now, "exp": now - timedelta(minutes=5)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def main():
    stamp = int(time.time())
    uname_a = f"qa_a_{stamp}"
    uname_b = f"qa_b_{stamp}"
    password = "qa-secret-123"

    with httpx.Client(base_url=BASE, timeout=15) as c:
        # 1. 注册 / 登录
        r = c.post(f"{API}/auth/register", json={"username": uname_a, "password": password})
        reg_a = r.json()
        record("register A 200/code0", r.status_code == 200 and reg_a.get("code") == 0,
               f"http={r.status_code} body={reg_a}")
        token_a = reg_a["data"]["tokens"]["access_token"]
        refresh_a = reg_a["data"]["tokens"]["refresh_token"]
        record("register A data.user 包装", "user" in reg_a.get("data", {}), "data keys=" + ",".join(sorted(reg_a["data"].keys())))

        r = c.post(f"{API}/auth/register", json={"username": uname_b, "password": password})
        reg_b = r.json()
        token_b = reg_b["data"]["tokens"]["access_token"]
        record("register B 200/code0", r.status_code == 200 and reg_b.get("code") == 0, f"http={r.status_code}")

        r = c.post(f"{API}/auth/login", json={"account": uname_a, "password": password})
        login_a = r.json()
        record("login A 200/code0", r.status_code == 200 and login_a.get("code") == 0, f"http={r.status_code}")

        # 2. /auth/me 结构
        r = c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        me_a = r.json()
        record("me A 200/code0", r.status_code == 200 and me_a.get("code") == 0, f"http={r.status_code}")
        record("me data 无 user 包装（契约偏离佐证）", "user" not in me_a.get("data", {}),
               "me.data keys=" + ",".join(sorted(me_a["data"].keys())),
               expect="register/login data.user 包装 vs me data 直接 UserOut")

        # 3. token 异常
        r = c.get(f"{API}/auth/me")
        record("me 无 token 401/1001", r.status_code == 401 and r.json().get("code") == 1001, f"http={r.status_code} body={r.json()}")
        r = c.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
        record("me 无效 token 401/1001", r.status_code == 401 and r.json().get("code") == 1001, f"http={r.status_code}")
        r = c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {make_expired_token(uuid.uuid4())}"})
        record("me 过期 token 401/1003", r.status_code == 401 and r.json().get("code") == 1003, f"http={r.status_code} body={r.json()}")

        # 4. refresh
        r = c.post(f"{API}/auth/refresh", json={"refresh_token": refresh_a})
        rec = r.json()
        record("refresh 200/code0 + TokenPair", r.status_code == 200 and rec.get("code") == 0
               and set(rec.get("data", {}).keys()) == {"access_token", "refresh_token", "token_type", "expires_in"},
               f"http={r.status_code} data.keys={sorted(rec.get('data', {}).keys())}")
        r = c.post(f"{API}/auth/refresh", json={"refresh_token": token_a})
        record("refresh 用 access token 401/1001", r.status_code == 401 and r.json().get("code") == 1001, f"http={r.status_code}")

        # 5. market（公开无鉴权）
        r = c.get(f"{API}/market/jobs")
        mj = r.json()
        record("market/jobs 200/code0", r.status_code == 200 and mj.get("code") == 0, f"http={r.status_code} total={mj.get('data', {}).get('total')}")
        r = c.get(f"{API}/market/facets")
        record("market/facets 200/code0", r.status_code == 200 and r.json().get("code") == 0, f"http={r.status_code}")
        r = c.get(f"{API}/market/jobs/{uuid.uuid4()}")
        record("market job 不存在 404/4107", r.status_code == 404 and r.json().get("code") == 4107, f"http={r.status_code} body={r.json()}")
        r = c.get(f"{API}/market/jobs", params={"sort": "bogus"})
        record("market sort 非法 400/3401", r.status_code == 400 and r.json().get("code") == 3401, f"http={r.status_code}")

        # 6. 跨用户任务隔离（A 建任务 → B 访问 → 403）
        r = c.post(f"{API}/tasks/trigger",
                   json={"task_type": "report_stage1", "params": {"user_id": str(uuid.uuid4()), "report_id": str(uuid.uuid4())}},
                   headers={"Authorization": f"Bearer {token_a}"})
        trig = r.json()
        record("A 触发任务 200/code0", r.status_code == 200 and trig.get("code") == 0, f"http={r.status_code} body={trig}")
        task_id = trig.get("data", {}).get("task_id")
        if task_id:
            r = c.get(f"{API}/tasks/{task_id}", headers={"Authorization": f"Bearer {token_b}"})
            record("B 访问 A 任务 403/1002", r.status_code == 403 and r.json().get("code") == 1002, f"http={r.status_code} body={r.json()}")
            r = c.get(f"{API}/tasks/{task_id}", headers={"Authorization": f"Bearer {token_a}"})
            record("A 访问自己任务 200", r.status_code == 200 and r.json().get("code") == 0, f"http={r.status_code}")
            r = c.post(f"{API}/tasks/{task_id}/cancel", headers={"Authorization": f"Bearer {token_b}"})
            record("B 取消 A 任务 403/1002", r.status_code == 403 and r.json().get("code") == 1002, f"http={r.status_code}")
        r = c.get(f"{API}/tasks/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token_a}"})
        record("任务不存在 404/4001", r.status_code == 404 and r.json().get("code") == 4001, f"http={r.status_code}")

        # 7. 无 token 访问受保护端点
        r = c.get(f"{API}/tasks/{uuid.uuid4()}")
        record("tasks 无 token 401/1001", r.status_code == 401 and r.json().get("code") == 1001, f"http={r.status_code}")

        # 8. /health
        r = c.get("/health")
        record("health 200/ok", r.status_code == 200 and r.json().get("data", {}).get("status") == "ok", f"body={r.json()}")

    passed = sum(1 for x in results if x["ok"])
    print(f"\n===== SUMMARY: {passed}/{len(results)} passed =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())