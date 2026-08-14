# 个人健康生活网络数据监测与分析系统

个人健康生活网络数据监测与分析系统面向个人与家庭照护场景，把体征、运动、睡眠、饮食、设备接入、异常提醒、隐私授权、健康报告和验收材料整理成可操作、可追踪、可交付的产品闭环。

## 技术结构

- 前端：Vite + 原生 HTML/CSS/JavaScript，入口位于 `frontend/`
- API：Python 标准库 HTTP 服务 + SQLite，入口位于 `backend/app.py`
- 数据库：首次启动自动创建 `data/health.db`
- 安全：PBKDF2 密码哈希、签名过期 JWT、六角色权限和个人数据范围隔离
- 部署：Docker Compose + Nginx
- 文档：`docs/` 中包含需求、设计、测试、部署与验收材料

## 固定端口

端口定义在根目录 `.env.ports`，并启用 `strictPort`。

| 服务 | 端口 | 地址 |
| --- | ---: | --- |
| 前端开发 | 5206 | `http://127.0.0.1:5206` |
| 前端预览 | 6206 | `http://127.0.0.1:6206` |
| API | 8206 | `http://127.0.0.1:8206` |

## 本地启动

终端 1 启动 API：

```powershell
$env:PORT='8206'
$env:BOOTSTRAP_USER_PASSWORD='在本机设置强密码'
$env:BOOTSTRAP_ADMIN_PASSWORD='在本机设置另一组强密码'
$env:JWT_SECRET='至少32位随机字符'
python backend/app.py
```

登录角色账号由后端首次启动时建立：`personal.user`、`family.admin`、`cared.member`、`health.advisor`、`platform.operator`、`system.admin`。登录页必须同时选择角色、填写用户名和密码。可使用 `BOOTSTRAP_FAMILY_PASSWORD`、`BOOTSTRAP_CARED_PASSWORD`、`BOOTSTRAP_ADVISOR_PASSWORD`、`BOOTSTRAP_OPERATOR_PASSWORD` 为其他角色设置独立密码，未设置时沿用用户密码。设备页面当前保存的是本地演示授权状态，不会冒充真实厂商 OAuth；部署时接入厂商连接器后再启用真实授权。

终端 2 启动前端：

```powershell
cmd /c npm install
cmd /c npm run dev
```

访问：`http://127.0.0.1:5206`

## 构建与预览

```powershell
cmd /c npm run build
cmd /c npm run preview
```

访问：`http://127.0.0.1:6206`

## 测试

```powershell
cmd /c npm run check
python tests/test_api.py
python tests/smoke_e2e.py
```

冒烟测试会验证首页、数据录入、异常流转、报告生成、隐私授权、设备接入、附件审计和验收中心。
测试同时覆盖未登录 401、个人用户越权 403、真实登录、JWT 签名和密码哈希。

## Docker

```powershell
docker compose up --build
```

启动前需按 `.env.example` 配置两类首次账号密码和 JWT 密钥。源码、页面和说明书不提供固定默认密码。

启动后访问：

- 前端：`http://127.0.0.1:5206`
- API：`http://127.0.0.1:8206`

## 主要入口

- 前端页面：`frontend/index.html`
- 前端交互：`frontend/app.js`
- 前端样式：`frontend/styles.css`
- Vite 配置：`vite.config.js`
- API 服务：`backend/app.py`
- 测试：`tests/test_api.py`、`tests/smoke_e2e.py`

## 本轮验收补充

- 重做前端页面结构与视觉层级，修复整站中文乱码问题
- 调整桌面与移动端导航密度，避免首屏被导航挤占
- 保留可操作表单、状态流转、报表与验收中心，并补充照护摘要与审计动态
- 构建输出继续保持 `dist/` 可预览
