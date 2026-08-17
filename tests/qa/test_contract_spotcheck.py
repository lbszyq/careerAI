"""契约抽查（QA，只读）：auth 端点响应结构 / 错误码 / HTTP 状态一致性。

依据 docs/architecture.md （统一信封 {code,message,data}）与 （错误码规范）。
发现与契约不一致处标记「契约偏离」，由 项目负责人 仲裁，不修改业务代码。
"""
import uuid
from unittest.mock import AsyncMock

from app.core.errors import AuthErrorCode, ErrorCode
from app.core.security import hash_password
from app.repositories.user_repository import UserRepository
from helpers import make_token, make_user

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
REFRESH_URL = "/api/v1/auth/refresh"


# ---------- 响应信封与结构一致性（） ----------

def test_envelope_shape_success(client, monkeypatch):
    """成功响应统一信封：{code:0, message, data}。"""
    user = make_user()
    monkeypatch.setattr(UserRepository, "get_by_username", AsyncMock(return_value=None))
    monkeypatch.setattr(UserRepository, "get_by_phone", AsyncMock(return_value=None))
    monkeypatch.setattr(UserRepository, "create", AsyncMock(return_value=user))
    resp = client.post(
        REGISTER_URL, json={"username": "Tester", "phone": "13800138000", "password": "secret123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 0
    assert body["message"] == "ok"


def test_envelope_shape_error(client):
    """错误响应统一信封：{code:非0, message, data:null}。"""
    resp = client.get(ME_URL)
    assert resp.status_code == 401
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == ErrorCode.UNAUTHORIZED
    assert body["data"] is None


def test_me_data_shape_differs_from_register_login(client, monkeypatch):
    """契约偏离佐证（已报）：/auth/me 的 data 直接为 UserOut，
    register/login 的 data 有 user 包装层 —— 三种端点响应结构不一致。

    偏离点：GET /auth/me → data{id,username,...}（无 user 键）；
           POST /auth/register|login → data{user:{...}, tokens:{...}}。
    影响：前端需按端点区分解析；后续统一需 评估（本任务不修改）。
    """
    user = make_user(password_hash=hash_password("secret123"))
    monkeypatch.setattr(UserRepository, "get_by_username", AsyncMock(return_value=None))
    monkeypatch.setattr(UserRepository, "get_by_phone", AsyncMock(return_value=None))
    monkeypatch.setattr(UserRepository, "create", AsyncMock(return_value=user))

    reg = client.post(
        REGISTER_URL, json={"username": "Tester", "phone": "13800138000", "password": "secret123"}
    ).json()
    assert reg["data"]["user"]["id"] # register: data.user 包装
    assert "tokens" in reg["data"]

    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    token = make_token(user.id)
    me = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"}).json()
    assert me["code"] == 0
    assert "user" not in me["data"] # me: data 直接是 UserOut，无 user 包装
    assert me["data"]["id"] == str(user.id)

    monkeypatch.setattr(UserRepository, "get_by_account", AsyncMock(return_value=user))
    login = client.post(LOGIN_URL, json={"account": "tester", "password": "secret123"}).json()
    assert login["data"]["user"]["id"] # login: data.user 包装

    # 输出三端点 data 键形状，作为偏离证据（随 pytest -s 可见）
    print("\n[QA] register.data keys:", sorted(reg["data"].keys()))
    print("[QA] login.data keys:", sorted(login["data"].keys()))
    print("[QA] me.data keys:", sorted(me["data"].keys()))


# ---------- 错误码 / HTTP 状态一致性（） ----------

def test_me_without_token_401_1001(client):
    resp = client.get(ME_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_invalid_token_401_1001(client):
    resp = client.get(ME_URL, headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_expired_token_401_1003(client):
    token = make_token(uuid.uuid4(), expired=True)
    resp = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.TOKEN_EXPIRED


def test_me_refresh_token_rejected_as_access_1001(client):
    """access 依赖只接受 type=access；refresh token 冒充 access → 1001。"""
    token = make_token(uuid.uuid4(), token_type="refresh")
    resp = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_register_invalid_username_400_2001(client):
    resp = client.post(REGISTER_URL, json={"username": "ab", "password": "secret123"})
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_register_missing_password_400_2001(client):
    """边界：缺必填字段 → 2001（实现未区分 2002 MISSING_REQUIRED，登记为事实）。"""
    resp = client.post(REGISTER_URL, json={"username": "tester"})
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_register_invalid_phone_400_2001(client):
    resp = client.post(
        REGISTER_URL, json={"username": "tester", "phone": "12345", "password": "secret123"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_register_username_taken_409_3001(client, monkeypatch):
    monkeypatch.setattr(
        UserRepository, "get_by_username", AsyncMock(return_value=make_user(username="taken"))
    )
    resp = client.post(REGISTER_URL, json={"username": "taken", "password": "secret123"})
    assert resp.status_code == 409
    assert resp.json()["code"] == AuthErrorCode.USERNAME_TAKEN


def test_login_wrong_password_401_1001(client, monkeypatch):
    user = make_user(password_hash=hash_password("right-password"))
    monkeypatch.setattr(UserRepository, "get_by_account", AsyncMock(return_value=user))
    resp = client.post(LOGIN_URL, json={"account": "tester", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_refresh_with_access_token_401_1001(client):
    """refresh 端点只接受 refresh token（异常路径）。"""
    token = make_token(uuid.uuid4(), token_type="access")
    resp = client.post(REFRESH_URL, json={"refresh_token": token})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_refresh_success_returns_token_pair(client, monkeypatch):
    """POST /auth/refresh 成功 → data 为 TokenPair（无 user 包装，语义上合理）。"""
    user = make_user()
    token = make_token(user.id, token_type="refresh")
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    resp = client.post(REFRESH_URL, json={"refresh_token": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert set(body["data"].keys()) == {"access_token", "refresh_token", "token_type", "expires_in"}


# ---------- 响应不泄露敏感字段（T4 部分） ----------

def test_auth_responses_do_not_expose_password_or_hash(client, monkeypatch):
    """register/login/me 响应不含 password/password_hash 等敏感字段。"""
    user = make_user()
    monkeypatch.setattr(UserRepository, "get_by_username", AsyncMock(return_value=None))
    monkeypatch.setattr(UserRepository, "get_by_phone", AsyncMock(return_value=None))
    monkeypatch.setattr(UserRepository, "create", AsyncMock(return_value=user))
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))

    reg = client.post(
        REGISTER_URL, json={"username": "Tester", "phone": "13800138000", "password": "secret123"}
    ).json()
    token = make_token(user.id)
    me = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"}).json()

    for body in (reg, me):
        dumped = str(body)
        for sensitive in ("password", "password_hash", "secret"):
            assert sensitive not in dumped, f"响应泄露敏感字段: {sensitive}"
