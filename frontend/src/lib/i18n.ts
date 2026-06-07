export type Lang = "zh" | "en";

export const translations = {
  // ── Navigation ──────────────────────────────────
  nav: {
    dashboard:  { zh: "仪表盘",  en: "Dashboard" },
    agents:     { zh: "智能体",  en: "Agents" },
    workflows:  { zh: "工作流",  en: "Workflows" },
    chat:       { zh: "对话",    en: "Chat" },
    knowledge:  { zh: "知识库",  en: "Knowledge" },
    models:     { zh: "模型",    en: "Models" },
    tools:      { zh: "工具",    en: "Tools" },
    settings:   { zh: "设置",    en: "Settings" },
  },

  // ── Common ──────────────────────────────────────
  common: {
    create:     { zh: "新建",    en: "New" },
    save:       { zh: "保存",    en: "Save" },
    cancel:     { zh: "取消",    en: "Cancel" },
    delete:     { zh: "删除",    en: "Delete" },
    confirm:    { zh: "确认",    en: "Confirm" },
    loading:    { zh: "加载中…", en: "Loading..." },
    noData:     { zh: "暂无数据", en: "No data yet" },
    name:       { zh: "名称",    en: "Name" },
    description:{ zh: "描述",    en: "Description" },
    status:     { zh: "状态",    en: "Status" },
    active:     { zh: "启用",    en: "Active" },
    inactive:   { zh: "停用",    en: "Inactive" },
    provider:   { zh: "提供商",  en: "Provider" },
    model:      { zh: "模型",    en: "Model" },
    language:   { zh: "语言",    en: "Language" },
    chinese:    { zh: "中文",    en: "Chinese" },
    english:    { zh: "English", en: "English" },
  },

  // ── Dashboard ───────────────────────────────────
  dashboard: {
    title:      { zh: "AIAGNET", en: "AIAGNET" },
    badge:      { zh: "AI 智能体网络平台", en: "AI Agent Network Platform" },
    subtitle:   { zh: "融合 CrewAI、LangGraph、LangChain、Dify、n8n 和 LangFlow 的统一平台。", en: "The unified platform combining CrewAI, LangGraph, LangChain, Dify, n8n, and LangFlow." },
    quickStart: { zh: "快速开始", en: "Quick Start" },
    step1:      { zh: "前往", en: "Go to" },
    step1b:     { zh: "配置你的 LLM 提供商（OpenAI、Anthropic 或本地 Ollama）。", en: "and configure your LLM provider (OpenAI, Anthropic, or local Ollama)." },
    step2:      { zh: "在", en: "Create agents in" },
    step2b:     { zh: "中创建智能体 — 定义角色、目标和工具。", en: "— define their role, goal, and tools." },
    step3:      { zh: "在可视化设计器中搭建工作流，连接智能体节点和条件分支。", en: "Build a workflow in the Visual Designer by connecting agent nodes and conditions." },
    step4:      { zh: "开启对话，实时观察智能体协同工作。", en: "Start a conversation and watch your agents collaborate in real-time." },
    features: {
      multiAgent:   { zh: "多智能体编排", en: "Multi-Agent Orchestration" },
      multiAgentD:  { zh: "创建具有自定义角色、目标和背景故事的智能体，支持顺序、层级和并行三种执行模式。", en: "Create agents with custom roles, goals, and backstories. Supports Sequential, Hierarchical, and Parallel modes." },
      workflow:     { zh: "可视化工作流设计器", en: "Visual Workflow Designer" },
      workflowD:    { zh: "拖拽式工作流构建器，支持智能体、工具、条件和人工审核节点，由 LangGraph 状态机驱动。", en: "Drag-and-drop builder with Agent, Tool, Condition, and Human nodes. Powered by LangGraph state machines." },
      chat:         { zh: "自动对话系统", en: "Auto-Dialogue System" },
      chatD:        { zh: "持久化记忆的多轮对话，智能体自动协作完成复杂任务。", en: "Multi-turn conversations with persistent memory. Agents automatically collaborate to complete tasks." },
      rag:          { zh: "RAG 知识库", en: "RAG Knowledge Base" },
      ragD:         { zh: "上传 PDF、DOCX 和网页，自动切分、向量化，支持检索增强生成。", en: "Upload PDF, DOCX, and web pages. Automatic chunking, embedding, and retrieval-augmented generation." },
      modelHub:     { zh: "模型中心", en: "Model Hub" },
      modelHubD:    { zh: "接入 OpenAI、Anthropic、Azure 和本地 Ollama，智能路由与成本追踪。", en: "Connect OpenAI, Anthropic, Azure, and local Ollama. Smart routing and cost tracking." },
      tools:        { zh: "工具注册表", en: "Tool Registry" },
      toolsD:       { zh: "内置工具：网络搜索、计算器、HTTP 请求、日期时间。支持通过 API 扩展自定义工具。", en: "Built-in: web search, calculator, HTTP requests, datetime. Extend with custom tools via API." },
    },
  },

  // ── Agents ──────────────────────────────────────
  agents: {
    title:        { zh: "智能体",        en: "Agents" },
    subtitle:     { zh: "创建并管理具有角色、目标和工具的 AI 智能体。", en: "Create and manage AI agents with roles, goals, and tools." },
    newAgent:     { zh: "新建智能体",     en: "New Agent" },
    role:         { zh: "角色",           en: "Role" },
    goal:         { zh: "目标",           en: "Goal" },
    backstory:    { zh: "背景故事（可选）", en: "Backstory (optional)" },
    temperature:  { zh: "温度",           en: "Temperature" },
    maxIter:      { zh: "最大迭代次数",   en: "Max Iterations" },
    noAgents:     { zh: "暂无智能体，创建你的第一个。", en: "No agents yet. Create your first agent." },
    deleteConfirm:{ zh: "确认删除此智能体？", en: "Delete this agent?" },
    namePlaceholder: { zh: "我的研究智能体", en: "My Research Agent" },
    rolePlaceholder: { zh: "高级研究分析师", en: "Senior Research Analyst" },
    goalPlaceholder: { zh: "查找并总结最新 AI 研究成果", en: "Find and summarize the latest AI research" },
    nlMode:       { zh: "自然语言", en: "Natural Language" },
    manualMode:   { zh: "手动填写", en: "Manual" },
    nlPlaceholder:{ zh: "描述你想要的智能体，例如：帮我写一份竞品分析报告的调研助手", en: "Describe your agent, e.g. a research assistant for competitive analysis reports" },
    generate:     { zh: "AI 生成", en: "AI Generate" },
    generating:   { zh: "生成中…", en: "Generating..." },
    seedTemplates:{ zh: "模板", en: "Templates" },
    tools:        { zh: "工具", en: "Tools" },
    selectModel:  { zh: "选择模型", en: "Select model" },
  },

  // ── Workflows ────────────────────────────────────
  workflows: {
    title:        { zh: "工作流",   en: "Workflows" },
    subtitle:     { zh: "构建并执行多智能体工作流，使用可视化图形设计器。", en: "Build and execute multi-agent workflows with visual graph designer." },
    newWorkflow:  { zh: "新建工作流", en: "New Workflow" },
    processType:  { zh: "执行模式",  en: "Process Type" },
    sequential:   { zh: "顺序 — 智能体依次执行", en: "Sequential — agents run one after another" },
    hierarchical: { zh: "层级 — 管理者分配任务给工作者", en: "Hierarchical — manager delegates to workers" },
    parallel:     { zh: "并行 — 所有智能体同时执行", en: "Parallel — all agents run simultaneously" },
    openDesigner: { zh: "打开设计器", en: "Open Designer" },
    noWorkflows:  { zh: "暂无工作流，创建你的第一个。", en: "No workflows yet. Create your first workflow." },
    deleteConfirm:{ zh: "确认删除此工作流？", en: "Delete this workflow?" },
    addNodes:     { zh: "添加节点",  en: "Add Nodes" },
    agentNode:    { zh: "+ 智能体节点", en: "+ Agent Node" },
    condition:    { zh: "+ 条件",    en: "+ Condition" },
    tips:         { zh: "拖动节点调整位置，从连接点拖出连线。", en: "Drag nodes to reposition. Connect by dragging from handles." },
    inputLabel:   { zh: "执行输入…", en: "Input for execution..." },
    run:          { zh: "运行",      en: "Run" },
    running:      { zh: "运行中…",   en: "Running..." },
    seedTemplates:{ zh: "模板",      en: "Templates" },
    nodes:        { zh: "节点",      en: "nodes" },
    edges:        { zh: "连线",      en: "edges" },
  },

  // ── Chat ─────────────────────────────────────────
  chat: {
    noAgent:      { zh: "无智能体",   en: "No agent" },
    placeholder:  { zh: "输入消息…",  en: "Type a message..." },
    hint:         { zh: "Enter 发送，Shift+Enter 换行", en: "Enter to send, Shift+Enter for new line" },
    empty:        { zh: "开始与 AI 智能体对话。", en: "Start a conversation with your AI agents." },
    emptyHint:    { zh: "从侧边栏选择智能体或使用默认模型。", en: "Select an agent from the sidebar or use the default model." },
    newChat:      { zh: "新对话",     en: "New Chat" },
    conversations:{ zh: "对话列表",   en: "Conversations" },
    thinking:     { zh: "思考中…",    en: "Thinking..." },
    createFailed: { zh: "创建对话失败", en: "Failed to create conversation" },
    loadFailed:   { zh: "加载消息失败", en: "Failed to load messages" },
    replyFailed:  { zh: "回复失败",    en: "Reply failed" },
    emptyResponse:{ zh: "(空回复)",   en: "(empty response)" },
    untitled:     { zh: "对话",        en: "Chat" },
  },

  // ── Knowledge ────────────────────────────────────
  knowledge: {
    title:        { zh: "知识库",    en: "Knowledge Bases" },
    newKB:        { zh: "新建知识库", en: "New KB" },
    search:       { zh: "搜索",      en: "Search" },
    upload:       { zh: "上传",      en: "Upload" },
    searchPlaceholder: { zh: "搜索知识库…", en: "Search knowledge base..." },
    documents:    { zh: "文档",      en: "Documents" },
    chunks:       { zh: "块",        en: "chunks" },
    searchResults:{ zh: "搜索结果",  en: "Search Results" },
    score:        { zh: "相关度",    en: "score" },
    noKB:         { zh: "暂无知识库", en: "No knowledge bases" },
    selectKB:     { zh: "选择或创建知识库。", en: "Select a knowledge base or create one." },
    embeddingModel:{ zh: "向量模型",  en: "Embedding Model" },
    deleteDocConfirm: { zh: "确认删除文档？", en: "Delete document?" },
    nameRequired: { zh: "请输入知识库名称", en: "Knowledge base name is required" },
    created:      { zh: "知识库已创建", en: "Knowledge base created" },
    createFailed: { zh: "创建失败", en: "Failed to create knowledge base" },
    uploading:    { zh: "上传中", en: "Uploading" },
    uploaded:     { zh: "文档已上传并索引", en: "Document uploaded and indexed" },
    uploadFailed: { zh: "上传失败", en: "Upload failed" },
    searchFailed: { zh: "搜索失败", en: "Search failed" },
    docDeleted:   { zh: "文档已删除", en: "Document deleted" },
    deleteFailed: { zh: "删除失败", en: "Delete failed" },
  },

  // ── Models ───────────────────────────────────────
  models: {
    title:        { zh: "模型中心",   en: "Model Hub" },
    subtitle:     { zh: "管理 LLM 提供商和模型配置。", en: "Manage LLM providers and model configurations." },
    activeConfigs:{ zh: "已配置模型",  en: "Active Configurations" },
    available:    { zh: "可用模型",   en: "Available Models" },
    defaultBadge: { zh: "默认",       en: "default" },
    contextWindow:{ zh: "上下文窗口",  en: "context window" },
    setupTitle:   { zh: "配置说明",   en: "Setup Instructions" },
    setupOpenAI:  { zh: "在 .env 文件中设置", en: "Set" },
    setupOllama:  { zh: "安装 Ollama 并运行", en: "Install Ollama and run" },
    localModel:   { zh: "本地", en: "Local" },
    cloudModel:   { zh: "云端", en: "Cloud" },
    serverOnline: { zh: "Ollama 服务器在线", en: "Ollama server online" },
  },

  // ── Tools ────────────────────────────────────────
  tools: {
    title:        { zh: "工具注册表",  en: "Tool Registry" },
    subtitle:     { zh: "所有可用工具列表，在创建智能体时分配工具。", en: "All available tools. Assign tools to agents when creating them." },
    builtin:      { zh: "内置",        en: "builtin" },
    customTitle:  { zh: "自定义工具",  en: "Custom Tools" },
    customDesc:   { zh: "可通过 API 注册自定义 HTTP 或 Python 工具。", en: "Custom HTTP-based and Python tools can be registered via the API." },
  },

  // ── Settings ─────────────────────────────────────
  settings: {
    title:        { zh: "设置",        en: "Settings" },
    subtitle:     { zh: "平台配置与环境变量。", en: "Platform configuration and environment setup." },
    envVars:      { zh: "环境变量",     en: "Environment Variables" },
    envDesc:      { zh: "通过编辑 .env 文件（从 .env.example 复制）来配置平台。", en: "Configure the platform by editing your .env file (copy from .env.example)." },
    apiRef:       { zh: "API 参考",    en: "API Reference" },
    apiDesc:      { zh: "后端 API 文档可在以下地址访问：", en: "The backend API is available at" },
    langTitle:    { zh: "语言 / Language", en: "Language / 语言" },
    langDesc:     { zh: "选择界面显示语言。", en: "Select the interface display language." },
  },
} as const;

export type TranslationKey = keyof typeof translations;

export function t(
  section: keyof typeof translations,
  key: string,
  lang: Lang
): string {
  const sec = translations[section] as Record<string, { zh: string; en: string }>;
  return sec?.[key]?.[lang] ?? key;
}
