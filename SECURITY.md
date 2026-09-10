# FitHub 安全部署清单（SECURITY.md）

> 本文档面向 **生产部署前** 的安全自检。所有项目必须勾选后才能上线。
> 配套代码：`backend/app/core/config.py` 已实现生产模式启动校验。

---

## 1. 生产部署前必改 `.env`

| 项 | 默认（不安全） | 生产值 | 校验命令 |
|---|---|---|---|
| `APP_ENV` | `development` | `production` | `grep ^APP_ENV .env` |
| `JWT_SECRET` | `change-me-...-long`（占位） | `openssl rand -hex 32` 生成 | `echo $JWT_SECRET \| grep -v change-me` |
| `DEBUG` | `true` | `false` | `grep ^DEBUG .env` |
| `LOG_LEVEL` | `INFO` | `INFO` 或 `WARNING` | — |
| `DEFAULT_ADMIN_USERNAME` | `admin` | 自定义（**不要**直接用 admin） | — |
| `DEFAULT_ADMIN_PASSWORD` | `admin123` | ≥16 位随机 | `openssl rand -base64 18` |
| `MYSQL_PASSWORD` | （空/弱） | ≥20 位随机 | — |

**应用启动时会自动校验**：如果 `APP_ENV=production` 但上面任一项未改，启动会直接报错并拒绝运行（见 `config.py:reject_insecure_production_defaults`）。

---

## 2. JWT 密钥生成

```bash
# 推荐：64 字符十六进制
openssl rand -hex 32

# 或 base64（48 字符）
openssl rand -base64 32
```

把输出直接写入 `.env` 的 `JWT_SECRET=` 后面。**绝对不要**：
- 把密钥 commit 到 git（已被 `.gitignore` 排除 `.env`，确认团队成员都遵守）
- 在不同环境共用同一个密钥
- 把密钥贴到聊天/issue/PR 里

---

## 3. 默认管理员账号

部署后**首次登录后必须立即改密**（CLAUDE.md「不要在生产环境用默认密钥」条款）。

后续增强（M10+1，已列入 backlog）：
- 加 `User.must_change_password` 字段
- admin 首登后强制跳改密页，未改密前 API 调用全部 403
- 改完后才能正常使用

在 S2 未实施前，请人工确保：
1. 部署后立即 SSH 进服务器改 admin 密码
2. 在管理后台「操作日志」页面检查是否有非预期登录

---

## 4. 数据库（MySQL）

| 项 | 要求 |
|---|---|
| 密码 | ≥20 位随机，不要复用任何系统密码 |
| 网络 | bind 到 127.0.0.1 或内网；**绝不**直接暴露 3306 到公网 |
| 字符集 | `utf8mb4`（应用 DSN 已强制，详见 `config.py:ensure_charset`） |
| 备份 | 每天 cron 备份，至少保留 30 天异地副本 |
| 账户 | 应用专用账号 `fithub_app`，权限 `SELECT/INSERT/UPDATE/DELETE` + `CREATE/ALTER/DROP` 仅给迁移时使用 |
| SSL | `MYSQL_DSN` 加 `ssl=true&ssl_ca=/path/to/ca.pem`（生产建议） |

数据库连接池默认 `pool_size=20, max_overflow=10`，可按并发调整。

---

## 5. HTTPS / 反向代理

FastAPI 应用本身**不**直接对外暴露 8002 端口。生产环境应：

1. 前置 Nginx / Caddy 处理 TLS 终止
3.  跳转 HTTP → HTTPS
3. 严格 `Strict-Transport-Security` 头
4. `proxy_set_header X-Forwarded-Proto https;`

示例 Nginx 片段：
```nginx
server {
    listen 443 ssl http2;
    server_name api.your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

---

## 6. CORS 白名单

`CORS_ORIGINS` 只能列出真实部署的前端域名：

```env
# 生产示例
CORS_ORIGINS=https://app.your-domain.com,https://admin.your-domain.com
CORS_ALLOW_CREDENTIALS=true
```

**绝不要**：
- 留 `*` 通配
- 留 `localhost:8080` / `localhost:3000`（dev 残留）

---

## 7. 速率限制（slowapi）

当前已生效：

| 接口 | 限制 | 配置项 |
|---|---|---|
| `POST /chat/send` | 5 次/分钟 + 50 次/天（每用户） | `rate_limit_ai_per_user_per_minute` / `..._per_day` |
| `POST /chat/send/stream` | 同上 | 同上 |
| 全局 fallback | 60 次/分钟/IP | `rate_limit_per_minute` |

生产可按需要调小（如金融级），但**不要**调大。

---

## 8. 密码哈希

bcrypt cost=12（`bcrypt_rounds=12`）。单次哈希约 250 ms，对登录够用、暴力破解代价高。

调整：
- 调高（13/14）= 更慢、更安全、登录可能感知卡顿
- 调低（10/11）= **不推荐**，会显著降低破解成本

---

## 9. 文件上传

- `upload_max_size_mb=10`（10 MB）
- `upload_dir=./data/uploads`（应用目录，**不要**放到静态文件可访问路径）
- 上传接口应在 S2 之后加强：白名单 MIME、病毒扫描（可选 ClamAV）

---

## 10. 操作审计

所有管理员/教练/客服的写操作已记录到 `operation_logs` 表：
- `operator`（操作人 user_id）
- `action`（动作：approve_template / reject_template / offline_template / 创建/更新/删除 …）
- `target_type` / `target_id`
- `summary` / `details` JSON
- `created_at`

**部署后定期审计**：
```sql
SELECT operator, action, COUNT(*) c
FROM operation_logs
WHERE created_at > NOW() - INTERVAL 7 DAY
GROUP BY operator, action
ORDER BY c DESC;
```

异常模式（如客服在凌晨批量删除评论）立即拉清单核查。

---

## 11. LLM 成本 & 滥用防护

- `ai_call_logs` 表记录每次 LLM 调用的 user / tokens / cost_cny / status / error_message
- B 端「数据看板 → AI 用量」可看每日成本折线、按意图分布
- 单用户每日 50 次 + 每分钟 5 次双重限流已在 `chat.py:334-335`
- 若发现异常高峰：
  - 临时把 `rate_limit_ai_per_user_per_day` 调小到 10
  - 查 `ai_call_logs WHERE user_id=?` 看具体内容
  - 必要时禁用用户（`UPDATE users SET status=2 WHERE id=?`）

---

## 12. 灰度发布 checklist

| 阶段 | 操作 |
|---|---|
| 0. 预发布 | 跑完 `pytest -q`，全绿 |
| 1. 数据迁移 | `alembic upgrade head`，生产 DB 上 dry-run 一遍 |
| 2. 镜像/包 | 锁 Python 版本到 `requirements.txt`，避免 `pip install` 漂移 |
| 3. 灰度 10% | Nginx 按 IP/cookie 分流到新版本 |
| 4. 监控 1h | 看 `operation_logs` 是否正常、`ai_call_logs` cost_cny 是否在预期 |
| 5. 全量 | 切 100% 流量，旧版本 standby 30 分钟 |
| 6. 回滚 | Nginx 切回旧版本（保留 DB 迁移回滚 SQL） |

---

## 13. 应急联系人

> TODO：填入团队值班电话 / 邮箱 / Slack 频道

- DBA：TODO
- 安全响应：TODO
- LLM API 厂商：TODO

---

## 附：当前已实现的安全检查清单

- [x] bcrypt cost=12（`config.py:bcrypt_rounds=12`）
- [x] JWT (HS256) + 访问令牌 2h + 刷新令牌 7d（`security.py`）
- [x] 全局限流（60/分钟/IP）
- [x] LLM 限流（5/分钟 + 50/天，每用户）
- [x] 慢 API 限流装饰器（`@limiter.limit`）
- [x] CORS 白名单（`cors_origins`）
- [x] 文件上传大小限制（10MB）
- [x] 操作审计日志
- [x] AI 调用审计 + 成本估算
- [x] **生产模式启动校验**（`config.py:reject_insecure_production_defaults`）

待办（M10+1）：
- [ ] admin 首登强制改密（S2）
- [ ] 用户名密码复杂度校验（min_length 仅，无大写/数字/符号组合）
- [ ] 评论敏感词过滤
- [ ] 上传文件 MIME 白名单
- [ ] 异常登录检测（同 IP 短时多账号失败 → 临时封禁）