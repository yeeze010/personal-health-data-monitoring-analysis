# 个人健康数据监测分析平台

个人健康数据监测分析平台面向个人与家庭照护场景，把体征、运动、睡眠、饮食、设备接入、异常提醒、隐私授权、健康报告和验收材料整理成可操作、可追踪、可交付的产品闭环。

## 技术结构

- 前端：Vite + 原生 HTML/CSS/JavaScript，入口位于 `frontend/`
- API：Python 标准库 HTTP 服务 + SQLite，入口位于 `backend/app.py`
- 数据库：首次启动自动创建 `data/health.db`
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
python backend/app.py
```

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

## Docker

```powershell
docker compose up --build
```

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
