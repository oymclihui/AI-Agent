# AI-AGENT 平台产品规划与开发路线

> 本文档描述 AI-AGENT 统一智能体平台的**已完成功能概览**与**未来规划**，供产品、研发与智能体检索参考。
> 最后更新：2026-06-08（与代码库对齐审计）

---

## 一、平台定位

AI-AGENT 是融合多智能体编排、可视化工作流、技能沉淀、数字员工定时任务、RAG 知识库与模型管理的统一平台。

核心分层：

- **Knowledge（知识库）**：事实与文档 — 「知道什么」
- **Skills（技能）**：方法论与 SOP — 「怎么做」（对齐 Cursor `SKILL.md`）
- **Tools（工具）**：可调用能力 — 「能做什么」
- **Agents（智能体）**：角色、目标、工具与技能绑定
- **Workflows（工作流）**：n8n 风格可视化编排
- **Digital Employees（数字员工）**：岗位化 Agent + 定时任务

**数字员工上岗链路**：Model Hub → Agents（+Skills）→ Workflows / Knowledge → Digital Employees（定时任务）→ Chat / 大屏 / 外部渠道。

---

## 二、已完成功能

### 2.1 工作流

- [x] n8n 风格可视化设计器（React Flow）
- [x] 从 n8n 官方仓库生成 **675+ 节点** 目录（触发器、AI、集成等）
- [x] 设计器：分类折叠节点面板、拖拽添加、右侧配置面板
- [x] **自然语言生成工作流**：`POST /api/v1/workflows/generate`，生成后跳转设计器
- [x] 节点 **AI 配置助手**：根据节点类型辅助填写参数
- [x] 中英双语节点目录与界面

### 2.2 技能（Skills）

- [x] 平台内创建 / 编辑技能（Markdown 指令、描述、发布状态）
- [x] 对齐 Cursor `SKILL.md` 结构（slug、description、instructions_md、tags）
- [x] 智能体 `skills_config` 绑定；对话与 Agent 任务运行时 **SkillInjector** 注入
- [x] **在线技能库**：
  - Anthropic 官方 + Agent Skills Hub
  - **SkillHub 中国社区**（`skillhub-cn`）：热门 / 飙升 / 精选 / 最新榜同步与批量导入
  - 在线目录约 **1123** 条模板（三源合计，随 sync 更新）
- [x] API：`/api/v1/skills/library/catalog`、`/library/import`、`/library/sync`；`/seed-bundled` 内置技能
- [x] 启动种子：代码审查、Git 提交信息；内置 **`data-qa-intent`（数据问答意图识别）**
- [x] **技能中英双语展示**：`metadata.i18n` 存储 display_name / description；API 支持 `?lang=zh|en`，随前端系统语言切换

**内置技能 `data-qa-intent` 要点**（借鉴 smart-qa-v2.0）：

- 12 类数据问答意图（KPI、趋势、归因、预测等；见 `data-qa-intent.md` 意图表）
- 指标 / 维度 / 时间实体识别
- 推荐图表类型与 `[kpi]` / `[chart]` / `[choices]` 结构化输出协议
- 适用于数据分析类数字员工与 Chat 场景

### 2.3 数字员工（Digital Employees）

- [x] 数字员工 CRUD：名称、职责、绑定 Agent、时区
- [x] 每个员工可挂载 **多个定时任务**（Cron 或固定间隔）
- [x] 任务类型（当前）：**Agent 指令任务**（`task_config.prompt`）
- [x] 进程内调度器（30 秒轮询）、**立即执行**、**执行记录**
- [x] 启动种子：员工「小研」+ 工作日 9:00 早报任务
- [x] API：`/api/v1/employees/`、`/tasks`、`/run`、`/runs`、`/scheduler/status`
- [x] **从模板创建员工**：`GET /api/v1/employees/templates`、`POST /api/v1/employees/import-template`
- [x]  bundled 模板 JSON（`backend/app/core/employees/templates/`），共 **12** 个：

| template_id | 名称 | 类别 |
|-------------|------|------|
| industry-research-assistant | 行业研究助理 | research |
| marketing-content-daily | 营销内容官 | marketing |
| security-health-check | 安全巡检员 | security |
| data-analyst-weekly | 数据分析周报员 | analytics |
| data-attribution-analyst | 归因分析专员（归因哥） | analytics |
| data-viz-analyst | 可视化分析专员 | analytics |
| data-metrics-analyst | 指标体系专员（Emily） | analytics |
| data-report-analyst | 报表分析专员（Lisa） | analytics |
| data-predict-analyst | 预测分析专员 | analytics |
| data-quality-analyst | 数据质量专员 | analytics |
| data-narrative-analyst | 叙事分析专员（Nora） | analytics |
| design-html-specialist | HTML 高保真设计专员（小设） | design |

设计类模板默认绑定 **`huashu-design`** + **`html2pptx`**（可编辑 PPTX 规范）技能。

### 2.4 运营大屏（Operations Dashboard）

- [x] 前端页面 **`/screen`**：全屏运营看板（无侧边栏）
- [x] 后端 **`GET /api/v1/dashboard/overview`**：KPI、员工状态、今日任务、小时趋势、排行等
- [x] **`GET /api/v1/dashboard/stream`**：SSE 实时刷新
- [x] 轮播幻灯片、员工筛选、时区 **Asia/Shanghai**
- [x] 首页与侧边栏入口：「运营大屏」

### 2.5 对话、知识与其他

- [x] 智能体自然语言生成
- [x] 多轮对话、流式输出、会话记忆（服务重启后从 DB 恢复）
- [x] RAG 知识库（Chroma 本地 / Milvus 可选）；文档 **storage_path** 持久化与 **GET 原文预览**
- [x] **平台文档知识库**：启动时种子「AI-AGENT 平台文档」（本文档）；**content_sha256 变更时自动再索引**
- [x] Model Hub、Tools、Orchestrator（CrewAI 风格）
- [x] 产品品牌统一为 **AI-AGENT**
- [x] 前端 **中 / 英** 双语界面（含技能名称随语言切换）
- [x] 默认后端端口 **8000**；支持 **PostgreSQL**（开发可连远程实例，生产可 SQLite 回退）
- [x] **远程部署脚本**（方案 B）：`backend/scripts/remote_deploy.py`、`remote_finish_deploy.py`、`remote_port_fix.py`、`remote_status.py` 等（systemd + Nginx）
- [x] **Docker Compose 初版**：根目录 `docker-compose.yml`（PostgreSQL、Redis、Chroma、前后端、Nginx）；Ollama 需宿主机，尚未写入 README 一键流程

---

## 三、未来规划（Roadmap）

### 3.1 数字员工 Phase 2

**目标**：从「只能跑 Agent 提示词」扩展为「可调度任意自动化单元」。

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | 工作流定时任务 | `task_type=workflow`，到期触发指定工作流执行 |
| P0 | 多 Agent 编排任务 | `task_type=crew`，调用 Orchestrator 顺序/并行流程 |
| P1 | 自然语言创建员工 / 任务 | 描述岗位与排班，AI 生成员工配置与 Cron 表达式 |
| P1 | 任务失败重试与告警 | 连续失败通知（邮件 / Webhook / 飞书 / 站内） |
| P2 | 生产级调度 | Celery Beat + Redis 替代进程内轮询，支持多实例部署 |
| P2 | 员工绑定知识库 | 定时任务自动 RAG 检索指定 KB |
| P2 | 任务依赖与编排 | 任务 A 完成后触发任务 B |
| P2 | 定时任务结果推送 | 任务完成后推送到飞书群 / 邮件 |

---

### 3.2 技能 Phase 2

**目标**：技能可生成、可导出、可从实践中沉淀。

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | 自然语言生成技能 | 描述场景，AI 生成 description + instructions_md |
| P1 | SKILL.md 导入 / 导出 | 与 Cursor / Claude Code 目录互通 |
| P1 | 从对话 / 执行记录「保存为技能」 | Chat 或 Agent Run 一键提炼 SOP |
| P1 | 在线库条目中英双语 | catalog 模板补充 `i18n` / display_name_zh |
| P2 | 技能路由器（自动 invoke） | 根据用户意图匹配 `auto_invoke` 技能，无需手动绑定 |
| P2 | 工作流 Agent 节点绑定技能 | AgentNode 配置中勾选 skills_config |
| P2 | 技能版本与审计 | 草稿 → 发布 → 归档，变更历史 |

---

### 3.3 工作流增强

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P1 | 更多内置节点执行器 | HTTP、Code、Database 等从目录到可运行 |
| P1 | 工作flow版本与发布 | 草稿 / 生产环境隔离 |
| P2 | Webhook 触发器 | 外部系统回调启动工作流 |
| P2 | 子工作流 | 节点嵌套调用其他工作流 |
| P2 | 执行可视化 | 运行中高亮当前节点、中间态查看 |

---

### 3.4 外部渠道集成

| 优先级 | 功能 | 说明 |
|--------|------|------|
| **P0** | **飞书机器人** | 企业自建应用：事件订阅 `im.message.receive_v1` → Webhook → DialogueManager → 飞书发消息 API；`chat_id` 映射 Conversation |
| P1 | 飞书卡片消息 | KPI / 图表类回复（对接 `[chart]` / `[kpi]` 协议） |
| P1 | 钉钉 / 企业微信 | 与飞书类似的 Bot 接入层 |
| P2 | 渠道绑定管理页 | 群 / 用户 ↔ Agent / 数字员工 配置 UI |

**飞书打通架构（计划）**：

1. 飞书开放平台创建自建应用，配置 Verification Token、Encrypt Key、事件 URL（公网 HTTPS）
2. 后端 `POST /api/v1/integrations/feishu/events`：验签、解密、3 秒内 ACK，异步调 LLM
3. `chat_id` ↔ `Conversation` 持久化，默认或按群绑定 Agent / 数字员工
4. 复用 SkillInjector、RAG、定时任务结果推送

环境变量（计划）：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`、`FEISHU_ENCRYPT_KEY`、`FEISHU_DEFAULT_AGENT_ID`

---

### 3.5 数据分析与 Chat 体验（smart-qa 借鉴）

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P1 | Chat 结构化块渲染 | 解析 `[chart:{...}]`、`[kpi:{...}]`、`[choices:]` 并前端可视化 |
| P1 | 意图路由 | 根据关键词自动切换数据分析类数字员工 |
| P2 | 用户记忆 | focusMetrics、frequentQueries、回复风格偏好（跨会话） |
| P2 | 联网搜索门控 | 内外部意图评分，按需调用 web_search |
| P2 | 零售 / 百胜等行业模板 | 扩展垂直场景员工模板 |

---

### 3.6 平台与基础设施

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | Docker Compose 一键部署 | 仓库已有 `docker-compose.yml` 初版；待 Ollama 容器化、文档化与生产验证 |
| P1 | 用户认证与多租户 | JWT / OAuth，KB / Agent / 员工按租户隔离 |
| P1 | 审计日志 | 谁创建、修改、执行了哪些资源 |
| P1 | 生产 PostgreSQL | 服务器部署默认 PG；SQLite 仅作无 PG 时回退 |
| P2 | 可观测性 | OpenTelemetry、执行链路追踪 |
| P2 | API Key 与速率限制 | 对外开放 API 时的鉴权与配额 |
| P2 | HTTPS 与域名 | 生产 Nginx + 证书；内网穿透用于飞书回调调试 |

---

### 3.7 对话与知识

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P1 | Agent 绑定知识库 | 对话时自动 RAG 检索 |
| P1 | 混合检索 | 向量 + 关键词（BM25） |
| P2 | 文档增量更新 | 上传新版本时仅重嵌入变更部分 |
| P2 | 多模态知识 | 图片、表格解析与检索 |

---

### 3.8 智能体与编排

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P1 | Agent 模板市场 | 分享 / 导入行业 Agent 配置（与员工模板互补） |
| P2 | 并行 Orchestrator | 多 Agent 并行 + 结果聚合 |
| P2 | Human-in-the-loop | 编排中暂停等待人工输入（工作流 human 节点与 Chat 打通） |
| P2 | 长期记忆 | 跨会话用户偏好与事实记忆 |

---

## 四、README 开发路线对照

- [x] n8n 风格工作流节点库与设计器
- [x] 自然语言创建工作流 / 智能体
- [x] 技能模块与在线技能库导入（含 SkillHub.cn）
- [x] 数字员工与 Cron 定时任务
- [x] 从模板创建数字员工（含数据分析类模板）
- [x] 运营大屏 `/screen` 与 Dashboard API
- [x] 技能中英双语（metadata.i18n）
- [x] 远程部署脚本（Linux + systemd + Nginx）
- [ ] 飞书 / 钉钉等 IM 机器人接入
- [ ] Chat 内图表 / KPI 结构化渲染
- [ ] 定时任务支持工作流 / 多 Agent 编排执行
- [ ] 从对话 / 执行记录「保存为技能」
- [ ] 用户认证与多租户
- [~] Docker Compose 一键部署（`docker-compose.yml` 初版已有，待完善与文档化）

---

## 五、建议实施顺序（2026 Q2–Q3）

1. **飞书机器人 Phase 1**（Webhook + 默认 Agent 回复，打通外部入口）
2. **数字员工 Phase 2 — workflow / crew 任务类型**（复用现有执行器）
3. **Chat 结构化渲染**（`[chart]` / `[kpi]`，与 data-qa-intent 闭环）
4. **Docker Compose**（降低部署门槛）
5. **技能 NL 生成 + 保存为技能**（形成沉淀闭环）
6. **Celery Beat 生产调度 + 飞书告警**（规模化定时任务）

---

## 六、相关 API（已实现）

| 模块 | 路径前缀 | 说明 |
|------|----------|------|
| 技能 | `/api/v1/skills` | CRUD；`?lang=zh\|en`；`/library/*`；`/seed-bundled` |
| 数字员工 | `/api/v1/employees` | CRUD；`/templates`；`/import-template`；`/tasks`；`/run`；`/runs` |
| 运营大屏 | `/api/v1/dashboard` | `/overview`；`/stream`（SSE） |
| 工作流 | `/api/v1/workflows` | CRUD；`/generate`；`/execute` |
| 知识库 | `/api/v1/knowledge` | CRUD；文档上传；`/search`；文档原文 GET |
| 对话 | `/api/v1/chat` | 会话；流式消息 |

完整接口见：`http://localhost:8000/docs`（默认端口 8000）

**计划 API**：

| 模块 | 路径 | 说明 |
|------|------|------|
| 飞书 | `/api/v1/integrations/feishu/events` | 事件订阅 Webhook（计划） |

---

## 七、部署与环境

| 场景 | 说明 |
|------|------|
| 本地开发 | 前端 `http://localhost:3000`，后端 `http://127.0.0.1:8000` |
| 远程 Linux | Nginx :80 → 前端 :3000 + API :8000；脚本见 `backend/scripts/remote_*.py` |
| 数据库 | 开发可用 PostgreSQL；服务器无 PG 时可 SQLite |
| 飞书回调 | 需公网 HTTPS（ngrok 或域名），内网 IP 无法直接被飞书访问 |

---

## 八、术语表

| 术语 | 英文 | 含义 |
|------|------|------|
| 数字员工 | Digital Employee | 岗位化封装，绑定 Agent，挂载多个定时任务 |
| 技能 | Skill | 可复用 SOP，运行时注入 Agent 上下文 |
| 节点库 | Node Catalog | 从 n8n 同步的工作流节点定义目录 |
| 调度器 | Employee Scheduler | 扫描到期任务并调用 Runner 的后台服务 |
| 运营大屏 | Operations Dashboard | `/screen` 实时展示 KPI、员工与任务执行情况 |
| 意图技能 | data-qa-intent | 数据问答意图识别与结构化输出规范 |
| 模板员工 | Employee Template | JSON 模板一键导入岗位、Agent、任务 |
