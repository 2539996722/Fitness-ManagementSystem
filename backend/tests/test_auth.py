"""auth.py 单测。

分两层：
- Pure：security.py 的密码哈希 / JWT 签发 / 校验 + schema 校验（无 DB）
- Integration：register / login / refresh 路由（mock AsyncSession）
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from jose import jwt

from app.api.v1.auth import (
    LOCK_AFTER_FAILS,
    LOCK_MINUTES,
    PASSWORD_PATTERN,
    USERNAME_PATTERN,
    _make_token_pair,
    _utcnow_naive,
    login,
    refresh,
    register,
)
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn


# ============ Regex 校验 ============

class TestUsernamePattern:
    """USERNAME_PATTERN：中英文/数字/下划线，3-32 字符。"""

    @pytest.mark.parametrize("u", [
        "abc",                          # 最短
        "user_123",                     # 下划线+数字
        "用户名1",                       # 中文+数字（满足 ≥3 字符）
        "用户_name",                     # 中文+英文+下划线
        "abc" + "x" * 29,               # 刚好 32 字符
    ])
    def test_valid(self, u):
        assert USERNAME_PATTERN.match(u), f"should accept: {u}"

    @pytest.mark.parametrize("u", [
        "ab",                           # 太短（<3）
        "用户",                         # 太短（2 字符中文，<3）
        "abc" + "x" * 30,               # 太长（>32）
        "user name",                    # 空格不允许
        "user-name",                    # 短横线不允许
        "user.name",                    # 点不允许
        "user@host",                    # @不允许
        "user!",                        # 标点不允许
        "",                             # 空字符串
    ])
    def test_invalid(self, u):
        assert not USERNAME_PATTERN.match(u), f"should reject: {u!r}"


class TestPasswordPattern:
    """PASSWORD_PATTERN：8-20 字符，含字母+数字。"""

    @pytest.mark.parametrize("p", [
        "abc12345",                     # 8 字符 + 字母+数字
        "Aa1aaaaa",                     # 8 字符
        "Test1234",
        "Pwd12345!@#",                  # 含符号也 OK
        "12345678a",                    # 数字开头也行
    ])
    def test_valid(self, p):
        assert PASSWORD_PATTERN.match(p), f"should accept: {p}"

    @pytest.mark.parametrize("p", [
        "short1",                       # 太短（<8）
        "abcdefgh",                     # 无数字
        "12345678",                     # 无字母
        "Abc" + "1" * 18,               # 21 字符（>20）
        "",                             # 空
    ])
    def test_invalid(self, p):
        assert not PASSWORD_PATTERN.match(p), f"should reject: {p!r}"


# ============ Pydantic schema ============

class TestSchemas:

    def test_register_in_validates_username_length(self):
        # 太短 → 校验失败
        with pytest.raises(ValueError):
            RegisterIn(username="ab", password="Abc12345")

    def test_register_in_validates_password_length(self):
        with pytest.raises(ValueError):
            RegisterIn(username="valid_name", password="short1")  # <8

    def test_register_in_validates_password_max(self):
        with pytest.raises(ValueError):
            RegisterIn(username="valid_name", password="A" * 21)

    def test_register_in_accepts_valid(self):
        r = RegisterIn(username="valid_user", password="Abc12345", nickname="昵称")
        assert r.username == "valid_user"
        assert r.password == "Abc12345"
        assert r.nickname == "昵称"

    def test_register_in_nickname_optional(self):
        r = RegisterIn(username="valid_user", password="Abc12345")
        assert r.nickname is None

    def test_login_in_no_validation(self):
        """登录接口对用户名/密码不做格式校验（避免泄露用户名是否存在）。"""
        LoginIn(username="anything", password="")  # 空密码也被 schema 接受


# ============ security.py 密码 ============

class TestPasswordHash:
    """bcrypt cost=12，hash 不可逆、verify 准确。"""

    def test_hash_returns_non_empty_string(self):
        h = hash_password("Abc12345")
        assert isinstance(h, str)
        assert len(h) > 50  # bcrypt hash 通常 60 字符
        assert h.startswith("$2b$") or h.startswith("$2a$")  # bcrypt 前缀

    def test_hash_different_for_same_input(self):
        """bcrypt 加盐 → 同一密码每次哈希结果不同。"""
        h1 = hash_password("Abc12345")
        h2 = hash_password("Abc12345")
        assert h1 != h2

    def test_verify_correct_password(self):
        h = hash_password("Abc12345")
        assert verify_password("Abc12345", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("Abc12345")
        assert verify_password("WrongPass1", h) is False
        assert verify_password("abc12345", h) is False  # 大小写差异

    def test_verify_malformed_hash_returns_false(self):
        """异常 hash 不抛，返回 False（防 crash）。"""
        assert verify_password("anything", "not-a-valid-hash") is False
        assert verify_password("anything", "") is False

    def test_hash_bcrypt_cost_12(self):
        """确认 cost=12（与 SECURITY.md 约定）。"""
        h = hash_password("Abc12345")
        # bcrypt hash 格式：$2b$<cost>$...
        cost = int(h.split("$")[2])
        assert cost == settings.bcrypt_rounds


# ============ security.py JWT ============

class TestJwt:
    """JWT 签发 / 解码 / 类型区分。"""

    def test_create_access_token_has_type_access(self):
        tok = create_access_token(42)
        payload = jwt.decode(tok, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["type"] == "access"
        assert payload["sub"] == "42"

    def test_create_refresh_token_has_type_refresh(self):
        tok = create_refresh_token(42)
        payload = jwt.decode(tok, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["type"] == "refresh"

    def test_extra_claims_included(self):
        tok = create_access_token(1, extra_claims={"role": "admin"})
        payload = jwt.decode(tok, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["role"] == "admin"

    def test_decode_token_round_trip(self):
        tok = create_access_token(99)
        decoded = decode_token(tok)
        assert decoded is not None
        assert decoded["sub"] == "99"

    def test_decode_token_wrong_secret(self):
        """不同密钥签发的 token 应解码失败。"""
        bad = jwt.encode({"sub": "1", "type": "access"}, "wrong-secret", algorithm="HS256")
        assert decode_token(bad) is None

    def test_decode_token_malformed(self):
        """格式错误的 token 不抛异常，返回 None。"""
        assert decode_token("") is None
        assert decode_token("garbage") is None
        assert decode_token("a.b.c") is None

    def test_access_token_exp_2h(self):
        """Access token 默认 2 小时过期。"""
        tok = create_access_token(1)
        payload = jwt.decode(tok, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        delta = payload["exp"] - payload["iat"]
        # 允许 ±10 秒误差
        assert abs(delta - settings.access_token_expire_minutes * 60) < 10

    def test_refresh_token_exp_7d(self):
        tok = create_refresh_token(1)
        payload = jwt.decode(tok, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        delta = payload["exp"] - payload["iat"]
        expected = settings.refresh_token_expire_days * 86400
        assert abs(delta - expected) < 10


# ============ _make_token_pair ============

class TestMakeTokenPair:

    def test_returns_three_values(self):
        user = SimpleNamespace(id=1, role="user")
        access, refresh, expires_in = _make_token_pair(user)
        assert isinstance(access, str)
        assert isinstance(refresh, str)
        assert isinstance(expires_in, int)
        # access 和 refresh 不一样
        assert access != refresh
        # expires_in 等于配置的分钟数 × 60
        assert expires_in == settings.access_token_expire_minutes * 60

    def test_role_embedded_in_access_token(self):
        user = SimpleNamespace(id=5, role="admin")
        access, _, _ = _make_token_pair(user)
        payload = jwt.decode(access, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["role"] == "admin"


# ============ _utcnow_naive ============

class TestUtcnowNaive:

    def test_returns_naive_datetime(self):
        t = _utcnow_naive()
        assert isinstance(t, datetime)
        assert t.tzinfo is None  # 无时区

    def test_approximate_to_now(self):
        """返回时间应在调用时间前后 1 秒内。"""
        before = datetime.utcnow()
        t = _utcnow_naive()
        after = datetime.utcnow()
        assert before - timedelta(seconds=1) <= t <= after + timedelta(seconds=1)


# ============ 注册路由（mocked session）============

def _mock_session_no_existing_user(next_user_id: int = 999):
    """构造一个 session：用户不存在（注册成功路径）。

    模拟 ORM 行为：session.add(user) 之后 refresh 会把 id / created_at 回填。
    """
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    async def fake_refresh(obj):
        # 模拟 DB 行为：auto increment id + 默认 created_at
        obj.id = next_user_id
        obj.created_at = datetime(2024, 1, 1)
        obj.nickname = getattr(obj, "nickname", obj.username)
        obj.role = "user"
        obj.status = 0
        obj.gender = 0
        obj.avatar_url = None
    session.refresh.side_effect = fake_refresh
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


def _mock_session_existing_user():
    """构造一个 session：用户已存在（注册失败路径）。"""
    session = AsyncMock()
    existing = SimpleNamespace(id=1, username="dup_user")
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    session.execute.return_value = mock_result
    return session


class TestRegisterRoute:

    @pytest.mark.asyncio
    async def test_register_success(self):
        body = RegisterIn(username="newuser1", password="Abc12345", nickname="新人")
        session = _mock_session_no_existing_user()
        result = await register(body, session)
        assert result.access_token
        assert result.refresh_token
        assert result.user.username == "newuser1"

    @pytest.mark.asyncio
    async def test_register_rejects_bad_username(self):
        """长度 OK 但含不允许字符（如 '-'）→ 400。Pydantic 不查字符集，靠 auth 里的 regex。"""
        body = RegisterIn(username="user-name", password="Abc12345")  # '-' 不在 [\w一-龥]
        session = _mock_session_no_existing_user()
        with pytest.raises(HTTPException) as exc:
            await register(body, session)
        assert exc.value.status_code == 400
        assert "用户名格式错误" in exc.value.detail

    @pytest.mark.asyncio
    async def test_register_rejects_short_username_via_pydantic(self):
        """Pydantic 校验长度先于 regex。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RegisterIn(username="ab", password="Abc12345")  # <3 字符

    @pytest.mark.asyncio
    async def test_register_rejects_bad_password(self):
        body = RegisterIn(username="validname", password="nodigitpass")
        session = _mock_session_no_existing_user()
        with pytest.raises(HTTPException) as exc:
            await register(body, session)
        assert exc.value.status_code == 400
        assert "密码格式错误" in exc.value.detail

    @pytest.mark.asyncio
    async def test_register_rejects_duplicate_username(self):
        body = RegisterIn(username="dup_user", password="Abc12345")
        session = _mock_session_existing_user()
        with pytest.raises(HTTPException) as exc:
            await register(body, session)
        assert exc.value.status_code == 409
        assert "已被注册" in exc.value.detail


# ============ 登录路由（mocked session）============

def _make_user(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1, username="tester", password_hash=hash_password("Abc12345"),
        nickname="tester", avatar_url=None,
        gender=0, age=None, height_cm=None, weight_kg=None,
        role="user", status=0, is_deleted=False,
        failed_login_count=0, locked_until=None,
        last_login_at=None, created_at=datetime(2024, 1, 1),
        is_locked=False, is_banned=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_session_with_user(user):
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    session.execute.return_value = mock_result
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


class TestLoginRoute:

    @pytest.mark.asyncio
    async def test_login_success(self):
        user = _make_user()
        session = _mock_session_with_user(user)
        body = LoginIn(username="tester", password="Abc12345")
        result = await login(body, session)
        assert result.access_token
        assert user.failed_login_count == 0  # 重置

    @pytest.mark.asyncio
    async def test_login_user_not_found(self):
        """用户名不存在应报 401，且不暴露'用户不存在'。"""
        session = _mock_session_with_user(None)
        body = LoginIn(username="nobody", password="Abc12345")
        with pytest.raises(HTTPException) as exc:
            await login(body, session)
        assert exc.value.status_code == 401
        assert "用户名或密码错误" in exc.value.detail

    @pytest.mark.asyncio
    async def test_login_wrong_password_increments_count(self):
        user = _make_user(failed_login_count=0)
        session = _mock_session_with_user(user)
        body = LoginIn(username="tester", password="WrongPass1")
        with pytest.raises(HTTPException) as exc:
            await login(body, session)
        assert exc.value.status_code == 401
        assert user.failed_login_count == 1

    @pytest.mark.asyncio
    async def test_login_locks_after_n_fails(self):
        """连续 LOCK_AFTER_FAILS 次失败后锁定账号。"""
        user = _make_user(failed_login_count=LOCK_AFTER_FAILS - 1)
        session = _mock_session_with_user(user)
        body = LoginIn(username="tester", password="WrongPass1")
        with pytest.raises(HTTPException):
            await login(body, session)
        # 应触发锁定
        assert user.locked_until is not None
        # 锁定时间应在未来 LOCK_MINUTES 分钟内
        remaining = user.locked_until - _utcnow_naive()
        assert timedelta(minutes=LOCK_MINUTES - 1) < remaining <= timedelta(minutes=LOCK_MINUTES)

    @pytest.mark.asyncio
    async def test_login_rejects_locked_account(self):
        user = _make_user(is_locked=True)
        session = _mock_session_with_user(user)
        body = LoginIn(username="tester", password="Abc12345")
        with pytest.raises(HTTPException) as exc:
            await login(body, session)
        assert exc.value.status_code == 423

    @pytest.mark.asyncio
    async def test_login_rejects_banned_account(self):
        user = _make_user(is_banned=True)
        session = _mock_session_with_user(user)
        body = LoginIn(username="tester", password="Abc12345")
        with pytest.raises(HTTPException) as exc:
            await login(body, session)
        assert exc.value.status_code == 403
        assert "封禁" in exc.value.detail

    @pytest.mark.asyncio
    async def test_login_rejects_deleted_account(self):
        user = _make_user(is_deleted=True)
        session = _mock_session_with_user(user)
        body = LoginIn(username="tester", password="Abc12345")
        with pytest.raises(HTTPException) as exc:
            await login(body, session)
        assert exc.value.status_code == 403


# ============ 刷新 token 路由 ============

class TestRefreshRoute:

    @pytest.mark.asyncio
    async def test_refresh_with_valid_token(self):
        user = _make_user()
        session = _mock_session_with_user(user)
        rt = create_refresh_token(user.id, extra_claims={"role": user.role})
        body = RefreshIn(refresh_token=rt)
        result = await refresh(body, session)
        assert result.access_token
        assert result.refresh_token

    @pytest.mark.asyncio
    async def test_refresh_rejects_access_token(self):
        """access token 不能用于 refresh。"""
        user = _make_user()
        session = _mock_session_with_user(user)
        at = create_access_token(user.id, extra_claims={"role": user.role})
        body = RefreshIn(refresh_token=at)
        with pytest.raises(HTTPException) as exc:
            await refresh(body, session)
        assert exc.value.status_code == 401
        assert "Refresh Token 无效" in exc.value.detail

    @pytest.mark.asyncio
    async def test_refresh_rejects_garbage_token(self):
        body = RefreshIn(refresh_token="not.a.token")
        session = _mock_session_with_user(None)
        with pytest.raises(HTTPException) as exc:
            await refresh(body, session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_rejects_banned_user(self):
        """user 被封禁后 refresh 也应拒绝。"""
        user = _make_user(is_banned=True)
        session = _mock_session_with_user(user)
        rt = create_refresh_token(user.id)
        body = RefreshIn(refresh_token=rt)
        with pytest.raises(HTTPException) as exc:
            await refresh(body, session)
        assert exc.value.status_code == 401
        assert "封禁" in exc.value.detail

    @pytest.mark.asyncio
    async def test_refresh_rejects_deleted_user(self):
        user = _make_user(is_deleted=True)
        session = _mock_session_with_user(user)
        rt = create_refresh_token(user.id)
        body = RefreshIn(refresh_token=rt)
        with pytest.raises(HTTPException) as exc:
            await refresh(body, session)
        assert exc.value.status_code == 401


# ============ 端到端安全场景 ============

class TestEndToEndSecurity:

    @pytest.mark.asyncio
    async def test_register_then_login_returns_valid_tokens(self):
        """模拟完整流程：注册 → 拿到 token → 登出 → 再登。"""
        # 第一次注册（用户不存在）
        session = _mock_session_no_existing_user()
        body = RegisterIn(username="flow_user", password="Flow12345")
        reg_result = await register(body, session)
        # token 能解码
        decoded = decode_token(reg_result.access_token)
        assert decoded["type"] == "access"
        decoded_refresh = decode_token(reg_result.refresh_token)
        assert decoded_refresh["type"] == "refresh"

    def test_password_round_trip(self):
        """hash + verify 完整链路。"""
        plain = "Abc12345"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True
        assert verify_password("wrong", hashed) is False
