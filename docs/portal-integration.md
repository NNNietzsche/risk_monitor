# 页面与 AI 集成契约

页面入口 `/asset-risk.html`（`/demo.html` 别名）；`/` 重定向到页面。导航保持 `index.html`、`daily-news.html`、`asset-risk.html`、`entity-assessment.html`、`deep-reports.html`、`intl-ratings.html`。宿主应映射这些现有页面路径；本模块不提供其余页面。

前端使用原生 HTML/CSS/JS，静态资源 `/static/*`，API 前缀 `/api/v1`。接入现有布局时可使用 demo.html 的 main 和这两个样式文件、页面与地图脚本，也可按相同契约在宿主框架重写组件。部署子路径时需统一调整 API 与静态资源前缀，不修改导航业务目标。

| 接口 | 用途 |
|---|---|
| GET /dashboard | updated_at、monitors、events（最近100条）、timeline（最近10条）、news（最近100条）、ai |
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


## 动态时间线分页

`GET /api/v1/timeline?limit=10&offset=0` 返回 `{items,total,limit,offset,snapshot}`。后续页面带回相同 snapshot，例如 `?limit=10&offset=10&snapshot=123`。snapshot 是这一轮翻页时的观测记录上限，自动采集新增记录不会导致历史翻页重复或漏行。按 observed_at DESC、id DESC 稳定排序；点击“回到最新”会开始新的快照。首页自动刷新；浏览历史页时保持快照。

Dashboard 仍返回最新10条的 timeline 数组，页面使用独立分页接口；分页参数无效返回422。地图使用已有 Observation.latitude/longitude，字段为空时不显示新的定位点。

## 统一动态与风险呈现

时间线每一项对应一条 Observation，并在 `events` 数组中附带该次评估产生的 Risk Event；同一次采集不会再作为普通动态、规则事件重复显示两行。多条规则事件共用一个动态条目，各有独立证据入口。`assessment` 包含 tone、label、description、rule_version，均依据该条观测对应的历史 evaluation 生成，不使用目标当前状态替换历史事实。

筛选参数：`kind=vessel|flight`、`entry_type=all|events|quality`、`severity=high|warning|info`。指定 severity 只保留包含匹配规则事件的动态；计数和分页均在后端筛选后执行。新增 evaluation.observation_id 索引用于关联事件。

前端沿用原 demo 的 timeline-item、timeline-line、timeline-dot 和 tag 样式。普通更新/恢复为绿色，持续关注或数据质量问题为黄色，高风险/持续取消备降为红色，未评估为灰色；文字标签同时说明状态，不仅靠颜色区分。底层 observations、evaluations、risk_events 仍分别存储，原 events API 与证据链保留。公开新闻仍位于独立的公开风险信息板块。
