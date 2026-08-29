# A手像素画板

Vue 3 + FastAPI 的实时协作像素画布。后端是**单进程**应用：PostgreSQL 保存事件历史，NumPy RGB 画布提供实时读取，快照只在累计变更达到阈值时创建。Redis 和多 worker 不受支持。

## 架构

```text
Vue Canvas ── HTTP V2 / WebSocket V2 ── FastAPI adapters
                                          ↓
                     canvas / abuse / moderation / admin applications
                                          ↓
                           PostgreSQL + snapshots/ + Tencent Captcha
```

像素写入始终遵循：验证与限流 → PostgreSQL 事务 → 内存画布 → 有序事件队列 → WebSocket 广播/快照计数。客户端以 `request_id` 重试不会产生重复 `PixelLog`。

## 本地开发

后端要求 Python 3.10+、PostgreSQL 和 Conda 环境 `pixel_back`：

```bash
cd pixel_back
conda activate pixel_back
pip install -r requirements.txt
cp .env.example .env
python scripts/pre_migration_audit.py
alembic upgrade head
python scripts/reconcile_legacy_snapshots.py --apply
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
python -m unittest discover -s tests -p "test_*.py"
```

前端：

```bash
cd pixel_front
npm install
npm run dev
npm run build
```

Vite 开发代理将 `/api` 和 `/ws` 转发到 `127.0.0.1:8000`。普通页面为 `/`；受后端 Cookie 鉴权保护的管理工具为 `/admin.html`。

## V2 接口

- `GET /api/v2/session`：签发 90 天匿名、签名的 HttpOnly Cookie。
- `WS /ws/canvas`：`session.ready` 指定快照与 `head_event_id`；客户端再请求增量事件。
- `GET /api/v2/canvas/snapshots/{id}.png`
- `GET /api/v2/canvas/events?after=&through=&limit=5000`
- `GET /health`、`/health/live`、`/health/ready`

协议不保留 V1 快照接口。绘制消息为 `pixel.place`，包含 UUID `request_id`，广播为 `pixel.updated`。

## Docker 部署

快照属于运行数据，不进入镜像。镜像将部署目录 `snapshots/` 挂载到容器 `/app/snapshots/`：

```bash
cd pixel_back
docker build --platform linux/amd64 -t ccr.ccs.tencentyun.com/star/pixel:latest .
docker push ccr.ccs.tencentyun.com/star/pixel:latest
chmod +x run.sh
./run.sh
```

`run.sh` 默认用 Alembic 自动判断是否存在待执行迁移。只有首次迁移或镜像带来新迁移时，才会运行只读数据检查、停止旧容器、执行迁移和验证同名历史快照；日常重启会跳过这些一次性步骤。可用 `RUN_MIGRATIONS=true ./run.sh` 强制执行，或用 `RUN_MIGRATIONS=false ./run.sh` 在紧急重启时跳过。迁移流程任一步失败都会阻止新服务启动，不会猜测或删除历史数据。容器采用主机网络，Uvicorn 仅监听宿主机 `127.0.0.1:8000`，由同机 Nginx 反向代理。生产环境必须设置 `VISITOR_COOKIE_SECRET`，并在管理员功能启用时设置 `ADMIN_TOKEN_HASH` 与 `ADMIN_SESSION_SECRET`。仅当 Uvicorn 不能被公网绕过、确实只经可信代理访问时才设置 `TRUST_PROXY_HEADERS=true`。

`ALLOWED_ORIGINS` 是 WebSocket 的精确来源白名单，协议和主机名都必须一致。例如同时使用根域和 `www` 时：`ALLOWED_ORIGINS=https://pixel-asoul.club,https://www.pixel-asoul.club`。

## 匿名反破坏与管理

匿名绘制保留。默认 `ABUSE_MODE=observe` 只记录风险；观察至少七天并审阅数据后再切到 `enforce`。策略包括访客/IP/覆盖令牌桶、覆盖风险加权、腾讯验证码与渐进封禁。管理员可查看时间轴、生成历史预览、创建恢复计划、封禁访客和开启维护只读；所有变更写入审计与新的像素历史，不删除旧日志。

启用腾讯验证码前，在腾讯云创建 Web/H5 验证并将生产域名加入允许范围，再填写 `.env` 的四个 `TENCENT_*` 配置。前端只会在服务端发出 `challenge.required` 时按需加载腾讯验证码脚本，取得 `ticket`、`randstr` 后经 WebSocket 交由服务端二次校验；腾讯云密钥不会下发到浏览器。当前实现未启用腾讯云控制台的 `CaptchaAppId` 强制鉴权（`aidEncrypted`）功能。
