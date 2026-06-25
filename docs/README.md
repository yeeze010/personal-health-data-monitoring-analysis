# 文档索引

本目录用于沉淀个人健康生活网络数据监测与分析系统的需求、设计、接口、测试、部署与验收材料。

## 目录说明

| 目录 | 内容 | 当前用途 |
| --- | --- | --- |
| `docs/requirements/` | 产品定位、功能结构、核心业务流 | 约束页面范围与业务边界 |
| `docs/design/` | 数据模型、前端体验、工程骨架 | 支撑页面和接口实现 |
| `docs/api/` | API 规划与字段约定 | 前后端联调参考 |
| `docs/architecture/` | 架构说明与图示 | 交付和答辩材料 |
| `docs/test/` | 测试计划、冒烟和验收说明 | 研发与测试共用 |
| `docs/deployment/` | Docker、Nginx、本地联调方案 | 启动和部署说明 |
| `docs/acceptance/` | 验收标准和闭环记录 | 项目签收依据 |

## 本轮重点

- 前端页面按健康监测产品独立重构，重点修复移动端导航过高、横向溢出和信息层级偏平问题。
- 页面验收中心已纳入运行入口、权限矩阵、规则数和最近审计记录。
- 当前本地联调地址：
  - 前端开发：`http://127.0.0.1:5206`
  - API：`http://127.0.0.1:8206`
  - 前端预览：`http://127.0.0.1:6206`

## 建议阅读顺序

1. `docs/requirements/project-positioning.md`
2. `docs/requirements/feature-structure.md`
3. `docs/requirements/core-business-flow.md`
4. `docs/architecture/system-architecture.md`
5. `docs/design/data-model.md`
6. `docs/design/engineering-skeleton.md`
7. `docs/api/api-plan.md`
8. `docs/design/frontend-ux.md`
9. `docs/test/test-plan.md`
10. `docs/deployment/deployment-plan.md`
11. `docs/acceptance/acceptance-criteria.md`
