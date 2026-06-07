# AI-AGENT 平台产品规划与开发路线

> 本文档描述 AI-AGENT 统一智能体平台的**已完成功能概览**与**未来规划**，供产品、研发与智能体检索参考。
> 最后更新：2026-06

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

---

## 二、已完成功能（Phase 1）

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
- [x] **在线技能库**：Anthropic 官方 + Agent Skills Hub，810+ 模板
- [x] API：`/api/v1/skills/library/catalog`、`/library/import`、`/library/sync`
- [x] 启动种子：代码审查、Git 提交信息 两个示例技能

### 2.3 数字员工（Digital Employees）

- [x] 数字员工 CRUD：名称、职责、绑定 Agent、时区
- [x] 每个员工可挂载 **多个定时任务**（Cron 或固定间隔）
- [x] 任务类型（当前）：**Agent 指令任务**（`task_config.prompt`）
- [x] 进程内调度器（30 秒轮询）、**立即执行**、**执行记录**
- [x] 启动种子：员工「小研」+ 工作日 9:00 早报任务
- [x] API：`/api/v1/employees/`、`/tasks`、`/run`、`/runs`、`/scheduler/status`

### 2.4 其他

- [x] 智能体自然语言生成
- [x] 多轮对话、流式输出、会话记忆
- [x] RAG 知识库（Chroma / Milvus）
- [x] Model Hub、Tools、Orchestrator（CrewAI 风格）
- [x] 产品品牌统一为 **AI-AGENT**

---

## 三、未来规划（Roadmap）

### 3.1 数字员工 Phase 2

**目标**：从「只能跑 Agent 提示词」扩展为「可调度任意自动化单元」。

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | 工作流定时任务 | `task_type=workflow`，到期触发指定工作流执行 |
| P0 | 多 Agent 编排任务 | `task_type=crew`，调用 Orchestrator 顺序/并行流程 |
| P1 | 自然语言创建员工 / 任务 | 描述岗位与排班，AI 生成员工配置与 Cron 表达式 |
| P1 | 任务失败重试与告警 | 连续失败通知（邮件 / Webhook / 站内） |
| P2 | 生产级调度 | Celery Beat + Redis 替代进程内轮询，支持多实例部署 |
| P2 | 员工绑定知识库 | 定时任务自动 RAG 检索指定 KB |
| P2 | 任务依赖与编排 | 任务 A 完成后触发任务 B |

**技术要点**：

- 扩展 `EmployeeTaskType` 枚举与 `runner.py` 分支
- `task_config`  schema 按类型区分（workflow_id、crew_config 等）
- 调度状态持久化，避免多 worker 重复执行（分布式锁）

---

### 3.2 技能 Phase 2

**目标**：技能可生成、可导出、可从实践中沉淀。

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | 自然语言生成技能 | 描述场景，AI 生成 description + instructions_md |
| P1 | SKILL.md 导入 / 导出 | 与 Cursor / Claude Code 目录互通 |
| P1 | 从对话 / 执行记录「保存为技能」 | Chat 或 Agent Run 一键提炼 SOP |
| P2 | 技能路由器（自动 invoke） | 根据用户意图匹配 `auto_invoke` 技能，无需手动绑定 |
| P2 | 工作流 Agent 节点绑定技能 | AgentNode 配置中勾选 skills_config |
| P2 | 技能版本与审计 | 草稿 → 发布 → 归档，变更历史 |

**技术要点**：

- `SkillInjector` 增加按需加载（渐进披露 reference / scripts）
- 与 Knowledge 明确分工：Skill 不含长篇事实，事实仍走 RAG

---

### 3.3 工作流增强

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P1 | 更多内置节点执行器 | HTTP、Code、Database 等从目录到可运行 |
| P1 | 工作流版本与发布 | 草稿 / 生产环境隔离 |
| P2 | Webhook 触发器 | 外部系统回调启动工作流 |
| P2 | 子工作流 | 节点嵌套调用其他工作流 |
| P2 | 执行可视化 | 运行中高亮当前节点、中间态查看 |

---

### 3.4 平台与基础设施

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | Docker Compose 一键部署 | 前后端 + Ollama + Redis + 可选 Milvus |
| P1 | 用户认证与多租户 | JWT / OAuth，KB / Agent / 员工按租户隔离 |
| P1 | 审计日志 | 谁创建、修改、执行了哪些资源 |
| P2 | PostgreSQL 生产数据库 | 替代 SQLite，支持并发与迁移 |
| P2 | 可观测性 | OpenTelemetry、执行链路追踪 |
| P2 | API Key 与速率限制 | 对外开放 API 时的鉴权与配额 |

---

### 3.5 对话与知识

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P1 | Agent 绑定知识库 | 对话时自动 RAG 检索 |
| P1 | 混合检索 | 向量 + 关键词（BM25） |
| P2 | 文档增量更新 | 上传新版本时仅重嵌入变更部分 |
| P2 | 多模态知识 | 图片、表格解析与检索 |

---

### 3.6 智能体与编排

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P1 | Agent 模板市场 | 分享 / 导入行业 Agent 配置 |
| P2 | 并行 Orchestrator | 多 Agent 并行 + 结果聚合 |
| P2 | Human-in-the-loop | 编排中暂停等待人工输入（工作流已有 human 节点，需与 Chat 打通） |
| P2 | 长期记忆 | 跨会话用户偏好与事实记忆 |

---

## 四、README 开发路线对照

以下项与仓库 README「开发路线」章节一致：

- [x] n8n 风格工作流节点库与设计器
- [x] 自然语言创建工作流 / 智能体
- [x] 技能模块与在线技能库导入
- [x] 数字员工与 Cron 定时任务
- [ ] 定时任务支持工作流 / 多 Agent 编排执行
- [ ] 从对话 / 执行记录「保存为技能」
- [ ] 用户认证与多租户
- [ ] Docker Compose 一键部署

---

## 五、建议实施顺序（2026 Q2–Q3）

1. **数字员工 Phase 2 — workflow / crew 任务类型**（复用现有执行器，价值最高）
2. **Docker Compose**（降低部署门槛）
3. **技能 NL 生成 + 保存为技能**（形成闭环沉淀）
4. **用户认证与多租户**（面向团队使用）
5. **Celery Beat 生产调度**（规模化定时任务）

---

## 六、相关 API（已实现）

| 模块 | 路径前缀 | 说明 |
|------|----------|------|
| 技能 | `/api/v1/skills` | CRUD；`/library/*` 在线库 |
| 数字员工 | `/api/v1/employees` | CRUD；`/tasks`；`/run`；`/runs` |
| 工作流 | `/api/v1/workflows` | CRUD；`/generate`；`/execute` |
| 知识库 | `/api/v1/knowledge` | CRUD；文档上传；`/search` |

完整接口见：http://localhost:8000/docs

---

## 七、术语表

| 术语 | 英文 | 含义 |
|------|------|------|
| 数字员工 | Digital Employee | 岗位化封装，绑定 Agent，挂载多个定时任务 |
| 技能 | Skill | 可复用 SOP，运行时注入 Agent 上下文 |
| 节点库 | Node Catalog | 从 n8n 同步的工作流节点定义目录 |
| 调度器 | Employee Scheduler | 扫描到期任务并调用 Runner 的后台服务 |
