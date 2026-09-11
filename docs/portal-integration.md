# 页面与 AI 集成契约

页面入口 `/asset-risk.html`（`/demo.html` 别名）；`/` 重定向到页面。导航保持 `index.html`、`daily-news.html`、`asset-risk.html`、`entity-assessment.html`、`deep-reports.html`、`intl-ratings.html`。宿主应映射这些现有页面路径；本模块不提供其余页面。

前端使用原生 HTML/CSS/JS，静态资源 `/static/*`，API 前缀 `/api/v1`。接入现有布局时可使用 demo.html 的 main 和这两个样式文件、一个脚本，也可按相同契约在宿主框架重写组件。部署子路径时需统一调整 API 与静态资源前缀，不修改导航业务目标。

| 接口 | 用途 |
|---|---|
| GET /dashboard | updated_at、monitors、events（最近100条）、timeline（最近30条）、news（最近100条）、ai |
| POST /demo/seed | 仅空目标库创建演示目标；无公开信息时创建样例；不覆盖已有数据 |
| GET /news | 按发布时间倒序，最多100条 |
| POST /news | title、content、source、source_url、published_at（含时区）、category、is_mock（默认false） |
| GET /ai/status | configured、enabled、auto_refresh、revision、model、running、last_attempt、analysis |
| PATCH /ai/settings | enabled、auto_refresh；配置不足启用返回409 |
| POST /ai/refresh | 已关闭时直接返回状态；重复输入复用成功分析；并发/限流返回409 |

AI settings 默认关闭并持久化；分析不会改变 monitor、evaluation 或 risk_event。ai_runs 保留请求前写入的完整 input_snapshot、SHA256、model、prompt_version、created_at、status、content、error。成功分析与最近失败尝试分别返回，界面同时显示生成日期。服务崩溃留下 running 审计记录，下一次允许的请求会新增记录，历史记录不伪装为成功。

新增 ER 关系：public_news 为来源资料；ai_settings 为单例配置；ai_runs 的 input_snapshot 包含引用的 monitor / risk_event / public_news ID 及内容副本，保证来源后续变化也能复现当时输入。风险事件原有 raw_record → observation → evaluation → risk_event 证据链不变。

接入真实 Provider 先完成字段映射、实体匹配、时间口径、授权存储和更新周期，再用同一套缺失/重复/过期测试验收。不要将真实数据适配器的异常静默替换为 Mock。

当前公开信息为手动录入和结构化接口导入；新闻抓取、关联检索及自动分类由现有系统提供。报告系统可读取 events 与 news；AI 成功分析作为可选附录，并带生成时间、模型及输入范围。未连接宿主系统和真实数据服务，导航不可访问属于当前本地环境的预期限制。
