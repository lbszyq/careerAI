"""auth 注册/登录/鉴权测试（repository 层 mock，不依赖真实 DB）。"""
import uuid
from unittest.mock import AsyncMock

from helpers import make_token, make_user

from app.core.errors import AuthErrorCode, ErrorCode
from app.core.security import hash_password
from app.repositories.user_repository import UserRepository

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"


def test_register_success(client, monkeypatch):
    user = make_user()
    monkeypatch.setattr(UserRepository, "get_by_username", AsyncMock(return_value=None))
    monkeypatch.setattr(UserRepository, "get_by_phone", AsyncMock(return_value=None))
    monkeypatch.setattr(UserRepository, "create", AsyncMock(return_value=user))

    resp = client.post(
        REGISTER_URL, json={"username": "Tester", "phone": "13800138000", "password": "secret123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["user"]["username"] == "tester" # 统一小写存储
    assert body["data"]["user"]["id"] == str(user.id)
    assert body["data"]["tokens"]["token_type"] == "bearer"
    assert body["data"]["tokens"]["access_token"]


def test_register_username_taken(client, monkeypatch):
    monkeypatch.setattr(
        UserRepository, "get_by_username", AsyncMock(return_value=make_user(username="taken"))
    )
    resp = client.post(REGISTER_URL, json={"username": "taken", "password": "secret123"})
    assert resp.status_code == 409
    assert resp.json()["code"] == AuthErrorCode.USERNAME_TAKEN


def test_register_invalid_username_returns_2001(client):
    resp = client.post(REGISTER_URL, json={"username": "ab", "password": "secret123"})
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_register_missing_password_returns_2002(client):
    """缺必填字段（password）→ 400 + 2002 MISSING_REQUIRED（architecture.md）。"""
    resp = client.post(REGISTER_URL, json={"username": "Tester"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == ErrorCode.MISSING_REQUIRED
    assert body["data"] is None


def test_register_missing_username_returns_2002(client):
    """缺必填字段（username）→ 400 + 2002，与缺失字段位置无关。"""
    resp = client.post(REGISTER_URL, json={"password": "secret123"})
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.MISSING_REQUIRED


def test_register_invalid_phone_returns_2001(client):
    """字段存在但格式非法（phone 不符合手机号规则）→ 400 + 2001 INVALID_PARAM。"""
    resp = client.post(
        REGISTER_URL, json={"username": "Tester", "phone": "12345", "password": "secret123"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM

def test_register_empty_body_returns_2002(client):
    """空请求体（缺 username+password）→ 400 + 2002，不触发 500。"""
    resp = client.post(REGISTER_URL, json={})
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.MISSING_REQUIRED


def test_register_invalid_json_body_returns_2001(client):
    """请求体不是合法 JSON → 400 + 2001，不触发 500。"""
    resp = client.post(
        REGISTER_URL, content="{not-json", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM

def test_login_success(client, monkeypatch):
    user = make_user(password_hash=hash_password("secret123"))
    monkeypatch.setattr(UserRepository, "get_by_account", AsyncMock(return_value=user))
    resp = client.post(LOGIN_URL, json={"account": "tester", "password": "secret123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["user"]["username"] == "tester"
    assert body["data"]["tokens"]["access_token"]


def test_login_wrong_password_returns_1001(client, monkeypatch):
    user = make_user(password_hash=hash_password("right-password"))
    monkeypatch.setattr(UserRepository, "get_by_account", AsyncMock(return_value=user))
    resp = client.post(LOGIN_URL, json={"account": "tester", "password": "wrong-password"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == ErrorCode.UNAUTHORIZED
    assert "用户名或密码错误" in body["message"]


def test_me_without_token_returns_1001(client):
    resp = client.get(ME_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_invalid_token_returns_1001(client):
    resp = client.get(ME_URL, headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_expired_token_returns_1003(client):
    token = make_token(uuid.uuid4(), expired=True)
    resp = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.TOKEN_EXPIRED


def test_me_valid_token_returns_user(client, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    resp = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    # /auth/me 契约：data 直接为 UserOut（无 user 包装层）
    assert body["data"]["id"] == str(user.id)
    assert body["data"]["username"] == user.username
