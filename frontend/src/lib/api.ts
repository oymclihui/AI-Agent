import axios from "axios";
import type { DashboardOverview } from "@/lib/dashboardTypes";
import { getAuthToken, useAuthStore } from "@/lib/authStore";

/** Extract a human-readable message from an axios/API error. */
export function formatApiError(err: unknown, fallback: string): string {
  const ax = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = ax.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.filter((p) => p !== "body").join(".")
            : "";
          const msg = String((item as { msg?: unknown }).msg ?? "");
          return loc ? `${loc}: ${msg}` : msg;
        }
        return typeof item === "string" ? item : "";
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (typeof detail === "object" && detail !== null) {
    return JSON.stringify(detail);
  }
  if (ax.message && !ax.message.startsWith("Request failed with status code")) {
    return ax.message;
  }
  return fallback;
}

async function downloadBlob(path: string, filename: string, params?: Record<string, string | boolean>) {
  const token = getAuthToken();
  const qs = params
    ? "?" + new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      ).toString()
    : "";
  const res = await fetch(`/api/v1${path}${qs}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch { /* ignore */ }
    throw new Error(detail || "Download failed");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Same-origin proxy via app/api/v1/[...path]/route.ts → BACKEND_URL (default 8000). */
export const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
  timeout: 60000,
  transformResponse: [
    (data, _headers, status) => {
      if (status === 204 || data === "" || data == null) return null;
      if (typeof data === "string") {
        try {
          return JSON.parse(data);
        } catch {
          return data;
        }
      }
      return data;
    },
  ],
});

api.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const url = String(error.config?.url ?? "");
    const isAuthPublic = url.includes("/auth/login") || url.includes("/auth/register")
        || url.includes("/auth/forgot-password") || url.includes("/auth/reset-password");
    if (status === 401 && !isAuthPublic && typeof window !== "undefined") {
      const authHeader = error.config?.headers?.Authorization;
      const requestToken =
        typeof authHeader === "string" && authHeader.startsWith("Bearer ")
          ? authHeader.slice(7)
          : null;
      const currentToken = getAuthToken();
      // Ignore 401 from an older session still in flight after a fresh login.
      if (requestToken && currentToken && requestToken !== currentToken) {
        return Promise.reject(error);
      }
      if (!currentToken) {
        return Promise.reject(error);
      }
      useAuthStore.getState().logout();
    }
    return Promise.reject(error);
  },
);

const API_BASE = "/api/v1";

function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ── Auth ───────────────────────────────────────────
export const authApi = {
  login: (login: string, password: string) => api.post("/auth/login", { login, password }),
  register: (data: object) => api.post("/auth/register", data),
  me: () => api.get("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    api.post("/auth/change-password", { current_password, new_password }),
  adminResetPassword: (login: string, new_password: string) =>
    api.post("/auth/admin/reset-password", { login, new_password }),
  forgotPassword: (login: string) => api.post("/auth/forgot-password", { login }),
  validateResetToken: (token: string) => api.get("/auth/reset-password/validate", { params: { token } }),
  resetPassword: (token: string, new_password: string) =>
    api.post("/auth/reset-password", { token, new_password }),
  getMailbox: () => api.get("/auth/me/mailbox"),
  saveMailbox: (data: object) => api.post("/auth/me/mailbox", data),
  deleteMailbox: () => api.delete("/auth/me/mailbox"),
  testMailbox: () => api.post("/auth/me/mailbox/test"),
  listModelKeys: () => api.get("/auth/me/model-keys"),
  saveModelKey: (data: object) => api.post("/auth/me/model-keys", data),
  deleteModelKey: (id: string) => api.delete(`/auth/me/model-keys/${id}`),
};

// ── Agents ──────────────────────────────────────────
export const agentsApi = {
  list: (lang?: string, scope?: string) =>
    api.get("/agents/", { params: { ...(lang ? { lang } : {}), ...(scope ? { scope } : {}) } }),
  create: (data: object) => api.post("/agents/", data),
  get: (id: string, lang?: string) => api.get(`/agents/${id}`, { params: lang ? { lang } : {} }),
  update: (id: string, data: object) => api.patch(`/agents/${id}`, data),
  delete: (id: string) => api.delete(`/agents/${id}`),
  run: (id: string, data: object) => api.post(`/agents/${id}/run`, data),
  generate: (description: string) => api.post("/agents/generate", { description }),
  copy: (id: string) => api.post(`/agents/${id}/copy`),
  getSharing: (id: string) => api.get(`/agents/${id}/sharing`),
  updateSharing: (id: string, data: object) => api.put(`/agents/${id}/sharing`, data),
  shareTargets: (q?: string) => api.get("/agents/share-targets", { params: q ? { q } : {} }),
  seedTemplates: () => api.post("/agents/seed-templates"),
  librarySources: () => api.get("/agents/library/sources"),
  libraryCatalog: (params?: { source?: string; division?: string; q?: string }) =>
    api.get("/agents/library/catalog", { params }),
  libraryDivisions: (source?: string) =>
    api.get("/agents/library/divisions", { params: source ? { source } : {} }),
  librarySync: () => api.post("/agents/library/sync"),
  libraryImport: (data: {
    items?: { source: string; slug: string }[];
    import_all?: boolean;
    overwrite?: boolean;
    import_skills?: boolean;
  }) => api.post("/agents/library/import", data),
  libraryI18nBackfill: () => api.post("/agents/library/i18n-backfill"),
};

// ── Workflows ────────────────────────────────────────
export const workflowsApi = {
  list: () => api.get("/workflows"),
  create: (data: object) => api.post("/workflows/", data),
  get: (id: string) => api.get(`/workflows/${id}`),
  update: (id: string, data: object) => api.patch(`/workflows/${id}`, data),
  delete: (id: string) => api.delete(`/workflows/${id}`),
  execute: (id: string, data: object) => api.post(`/workflows/${id}/execute`, data),
  executions: (id: string) => api.get(`/workflows/${id}/executions`),
  seedTemplates: () => api.post("/workflows/seed-templates"),
  generate: (data: object) => api.post("/workflows/generate", data),
  nodeCatalog: () => api.get("/workflows/node-catalog"),
  nodeDefinition: (nodeId: string) => api.get(`/workflows/node-catalog/${nodeId}`),
  configureNode: (data: object) => api.post("/workflows/configure-node", data),
  /** Load catalog from API, fall back to bundled static JSON when backend is outdated */
  loadNodeCatalog: async () => {
    try {
      const { data } = await api.get("/workflows/node-catalog");
      return data;
    } catch {
      const res = await fetch("/node-catalog.json");
      if (!res.ok) throw new Error("Node catalog unavailable");
      return res.json();
    }
  },
};

// ── Chat ─────────────────────────────────────────────
export const chatApi = {
  createConversation: (data: object) => api.post("/chat/conversations", data),
  listConversations: () => api.get("/chat/conversations"),
  getConversation: (id: string) => api.get(`/chat/conversations/${id}`),
  updateContext: (id: string, data: object) => api.patch(`/chat/conversations/${id}/context`, data),
  deleteConversation: (id: string) => api.delete(`/chat/conversations/${id}`),
  deleteAllConversations: () => api.delete("/chat/conversations"),
  getMessages: (id: string) => api.get(`/chat/conversations/${id}/messages`),
  saveAsSkill: (id: string, data: object) => api.post(`/chat/conversations/${id}/save-as-skill`, data),
  saveToKnowledge: (id: string, data: object) => api.post(`/chat/conversations/${id}/save-to-knowledge`, data),
  suggestDeposit: (id: string, lang: string, signal?: AbortSignal) =>
    api.post(`/chat/conversations/${id}/suggest-deposit`, { lang }, { timeout: 180000, signal }),
  confirmDeposit: (id: string, data: object) =>
    api.post(`/chat/conversations/${id}/deposit/confirm`, data, { timeout: 180000 }),
  listGroupTemplates: (lang: string) => api.get(`/chat/group/templates?lang=${lang}`),
  exportGroupChat: async (id: string, lang: string) => {
    const token = getAuthToken();
    const res = await fetch(`/api/v1/chat/group/conversations/${id}/export?lang=${lang}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error("Export failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `group-chat-${id.slice(0, 8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  },
  sendMessage: (id: string, data: object) => api.post(`/chat/conversations/${id}/messages`, data),
  sendMessageWithFiles: (
    id: string,
    message: string,
    files: File[],
    stream = true,
    extras?: {
      model_config_id?: string | null;
      connector_id?: string | null;
      web_search_enabled?: boolean | null;
    },
  ) => {
    const form = new FormData();
    form.append("message", message);
    form.append("stream", stream ? "true" : "false");
    form.append("model_config_id", extras?.model_config_id ?? "");
    form.append("connector_id", extras?.connector_id ?? "");
    form.append(
      "web_search_enabled",
      extras?.web_search_enabled ? "true" : "false",
    );
    for (const file of files) {
      form.append("files", file);
    }
    return form;
  },
  transcribe: async (audio: Blob, lang: string) => {
    const form = new FormData();
    form.append("file", audio, "recording.webm");
    form.append("lang", lang);
    const response = await fetch(`${API_BASE}/chat/transcribe`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      let detail = text;
      try {
        const parsed = JSON.parse(text);
        detail = parsed?.detail ?? text;
      } catch {
        /* keep raw */
      }
      throw new Error(typeof detail === "string" ? detail : "transcribe failed");
    }
    return response.json() as Promise<{ text: string; source: string }>;
  },
  suggestQuestions: async (files: File[], lang: string, agentId?: string, signal?: AbortSignal) => {
    const form = new FormData();
    form.append("lang", lang);
    if (agentId) form.append("agent_id", agentId);
    for (const file of files) {
      form.append("files", file);
    }
    const response = await fetch(`${API_BASE}/chat/suggest-questions`, {
      method: "POST",
      body: form,
      headers: authHeaders(),
      signal,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || "suggest failed");
    }
    return response.json() as Promise<{ questions: string[]; source: string }>;
  },
  quickChat: (data: object) => api.post("/chat/quick", data),
};

// ── Knowledge Base ───────────────────────────────────
export const knowledgeApi = {
  list: () => api.get("/knowledge"),
  create: (data: object) => api.post("/knowledge/", data),
  get: (id: string) => api.get(`/knowledge/${id}`),
  delete: (id: string) => api.delete(`/knowledge/${id}`),
  uploadDocument: (kbId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.post(`/knowledge/${kbId}/documents`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  listDocuments: (kbId: string) => api.get(`/knowledge/${kbId}/documents`),
  getDocumentContent: (kbId: string, docId: string) =>
    api.get(`/knowledge/${kbId}/documents/${docId}/content`),
  deleteDocument: (kbId: string, docId: string) =>
    api.delete(`/knowledge/${kbId}/documents/${docId}`),
  search: (kbId: string, data: object) => api.post(`/knowledge/${kbId}/search`, data),
  update: (id: string, data: object) => api.patch(`/knowledge/${id}`, data),
  testBydKms: (data: object) => api.post("/knowledge/test-byd-kms", data),
  testConnection: (kbId: string) => api.post(`/knowledge/${kbId}/test-connection`),
};

// ── Models ────────────────────────────────────────────
export const modelsApi = {
  listAvailable: () => api.get("/models/available"),
  listConfigs: () => api.get("/models/configs"),
  createConfig: (data: object) => api.post("/models/configs", data),
  updateConfig: (id: string, data: object) => api.patch(`/models/configs/${id}`, data),
  deleteConfig: (id: string) => api.delete(`/models/configs/${id}`),
  setDefaultConfig: (id: string) => api.post(`/models/configs/${id}/set-default`),
  testConnection: (data: { provider: string; model_id: string; base_url?: string }) =>
    api.post("/models/test-connection", data),
  testConfigConnection: (id: string) => api.post(`/models/configs/${id}/test-connection`),
};

// ── Tools ─────────────────────────────────────────────
export const toolsApi = {
  list: () => api.get("/tools"),
};

// ── Desktop Automation ────────────────────────────────
export const desktopAutomationApi = {
  listDemos: () => api.get("/desktop-automation/demos"),
  createDemo: (data: object) => api.post("/desktop-automation/demos", data),
  updateDemo: (id: string, data: object) => api.patch(`/desktop-automation/demos/${id}`, data),
  deleteDemo: (id: string) => api.delete(`/desktop-automation/demos/${id}`),
  listTasks: () => api.get("/desktop-automation/tasks"),
  listAwaitingConfirmation: () => api.get("/desktop-automation/tasks/awaiting-confirmation"),
  confirmTask: (id: string) => api.post(`/desktop-automation/tasks/${id}/confirm`),
  rejectTask: (id: string) => api.post(`/desktop-automation/tasks/${id}/reject`),
  replay: (data: object) => api.post("/desktop-automation/tasks/replay", data),
  captureStart: (data?: object) => api.post("/desktop-automation/tasks/capture/start", data || {}),
  captureStop: (data: object) => api.post("/desktop-automation/tasks/capture/stop", data),
  sidecarStatus: () => api.get("/desktop-automation/sidecar/status"),
  depositDemo: (id: string, data: object) => api.post(`/desktop-automation/demos/${id}/deposit`, data),
};

// ── Harness (tool policy & confirmation) ─────────────
export const harnessApi = {
  listAwaitingActions: () => api.get("/harness/actions/awaiting-confirmation"),
  confirmAction: (id: string) => api.post(`/harness/actions/${id}/confirm`),
  rejectAction: (id: string) => api.post(`/harness/actions/${id}/reject`),
  listToolRisks: () => api.get("/harness/tools/risk"),
};

// ── Skills ────────────────────────────────────────────
export const skillsApi = {
  list: (lang?: string) => api.get("/skills", { params: lang ? { lang } : {} }),
  create: (data: object) => api.post("/skills/", data),
  get: (id: string, opts?: { lang?: string; raw?: boolean }) =>
    api.get(`/skills/${id}`, { params: { ...(opts?.lang ? { lang: opts.lang } : {}), ...(opts?.raw ? { raw: true } : {}) } }),
  update: (id: string, data: object) => api.patch(`/skills/${id}`, data),
  delete: (id: string) => api.delete(`/skills/${id}`),
  seedTemplates: () => api.post("/skills/seed-templates"),
  seedBundled: () => api.post("/skills/seed-bundled"),
  librarySources: () => api.get("/skills/library/sources"),
  libraryCatalog: (params?: { source?: string; category?: string; q?: string; lang?: string }) =>
    api.get("/skills/library/catalog", { params }),
  libraryCategories: (source?: string) =>
    api.get("/skills/library/categories", { params: source ? { source } : {} }),
  librarySync: (source = "skills-hub") =>
    api.post("/skills/library/sync", null, { params: { source } }),
  libraryImport: (data: { items: { source: string; slug: string }[]; overwrite?: boolean }) =>
    api.post("/skills/library/import", data),
};

// ── Dashboard / Screen ─────────────────────────────
export const dashboardApi = {
  overview: () => api.get<DashboardOverview>("/dashboard/overview"),
  streamUrl: (interval = 30) => {
    const token = getAuthToken();
    const qs = new URLSearchParams({ interval: String(interval) });
    if (token) qs.set("token", token);
    return `${API_BASE}/dashboard/stream?${qs.toString()}`;
  },
};

// ── Organization / RBAC ────────────────────────────
export const organizationApi = {
  listRoles: () => api.get("/organization/roles"),
  listDepartments: () => api.get("/organization/departments"),
  createDepartment: (data: object) => api.post("/organization/departments", data),
  updateDepartment: (id: string, data: object) => api.patch(`/organization/departments/${id}`, data),
  deleteDepartment: (id: string) => api.delete(`/organization/departments/${id}`),
  listUsers: () => api.get("/organization/users"),
  updateUser: (id: string, data: object) => api.patch(`/organization/users/${id}`, data),
  previewPermissions: (userId: string) => api.get(`/organization/permissions/preview/${userId}`),
  delegationContext: () => api.get("/organization/delegation/context"),
  delegatableRoles: () => api.get("/organization/roles/delegatable"),
  delegationDepartments: () => api.get("/organization/delegation/departments"),
  delegationDeptUsers: () => api.get("/organization/delegation/dept-users"),
  delegationExecutiveUsers: () => api.get("/organization/delegation/executive-users"),
  updateDeptDelegation: (userId: string, data: object) =>
    api.patch(`/organization/delegation/dept-users/${userId}`, data),
  updateExecDelegation: (userId: string, data: object) =>
    api.patch(`/organization/delegation/executive-users/${userId}`, data),
  auditLogs: (limit = 50) => api.get("/organization/audit-logs", { params: { limit } }),
  createUser: (data: object) => api.post("/organization/users", data),
  downloadPermissionTemplate: (includeCurrent = false) =>
    downloadBlob(
      "/organization/permissions/import/template",
      includeCurrent ? "permission_export.xlsx" : "permission_import_template.xlsx",
      { include_current: includeCurrent },
    ),
  downloadDelegationPermissionTemplate: () =>
    downloadBlob("/organization/delegation/permissions/import/template", "dept_permission_import_template.xlsx"),
  previewPermissionImport: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.post("/organization/permissions/import/preview", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  applyPermissionImport: (rows: object[]) =>
    api.post("/organization/permissions/import/apply", { rows }),
  previewDelegationPermissionImport: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.post("/organization/delegation/permissions/import/preview", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  applyDelegationPermissionImport: (rows: object[]) =>
    api.post("/organization/delegation/permissions/import/apply", { rows }),
};

// ── IM Integrations ─────────────────────────────────
export const integrationsApi = {
  status: () => api.get("/integrations/status"),
  adminStatus: () => api.get("/integrations/admin/status"),
};

export const databaseApi = {
  presets: () => api.get("/database/admin/presets"),
  status: () => api.get("/database/admin/status"),
  test: (body: Record<string, unknown>) => api.post("/database/admin/test", body),
  saveConfig: (body: Record<string, unknown>) => api.post("/database/admin/config", body),
  initialize: (body: Record<string, unknown>) => api.post("/database/admin/initialize", body),
  initSqlPreview: (params: { db_schema?: string; seed_test_data?: boolean }) =>
    api.get("/database/admin/init-sql-preview", { params }),
};

export const setupApi = {
  status: () => api.get("/setup/status"),
  presets: (setupToken: string) =>
    api.get("/setup/presets", { headers: { "X-Setup-Token": setupToken } }),
  test: (body: Record<string, unknown>, setupToken: string) =>
    api.post("/setup/test", body, { headers: { "X-Setup-Token": setupToken } }),
  initialize: (body: Record<string, unknown>, setupToken: string) =>
    api.post("/setup/initialize", body, { headers: { "X-Setup-Token": setupToken } }),
};

export const SETUP_TOKEN_STORAGE_KEY = "aiagnet_setup_token";

// ── Digital Employees ───────────────────────────────
export const employeesApi = {
  list: () => api.get("/employees/"),
  orgTree: (sync = true) => api.get("/employees/org-tree", { params: { sync } }),
  syncOrgTree: () => api.post("/employees/org-tree/sync"),
  create: (data: object) => api.post("/employees/", data),
  get: (id: string) => api.get(`/employees/${id}`),
  update: (id: string, data: object) => api.patch(`/employees/${id}`, data),
  delete: (id: string) => api.delete(`/employees/${id}`),
  listTemplates: () => api.get("/employees/templates"),
  importTemplate: (data: { template_id: string; employee_name?: string }) =>
    api.post("/employees/import-template", data),
  listTasks: (id: string) => api.get(`/employees/${id}/tasks`),
  createTask: (id: string, data: object) => api.post(`/employees/${id}/tasks`, data),
  updateTask: (id: string, taskId: string, data: object) =>
    api.patch(`/employees/${id}/tasks/${taskId}`, data),
  deleteTask: (id: string, taskId: string) => api.delete(`/employees/${id}/tasks/${taskId}`),
  runTask: (id: string, taskId: string) => api.post(`/employees/${id}/tasks/${taskId}/run`),
  listRuns: (id: string) => api.get(`/employees/${id}/runs`),
  getRun: (id: string, runId: string) => api.get(`/employees/${id}/runs/${runId}`),
  downloadRunUrl: (id: string, runId: string, format = "md") =>
    `${API_BASE}/employees/${id}/runs/${runId}/download?format=${format}`,
  saveRunToKnowledge: (id: string, runId: string, data: { kb_id?: string; kb_name?: string }) =>
    api.post(`/employees/${id}/runs/${runId}/save-to-knowledge`, data),
  schedulerStatus: () => api.get("/employees/scheduler/status"),
};

// ── Streaming helper ──────────────────────────────────
export interface ChatStreamEvent {
  token?: string;
  thinking?: string;
  error?: string;
  event?: string;
  agent_id?: string;
  agent_name?: string;
  agent_role?: string;
  round?: number;
  is_synthesis?: boolean;
  message_id?: string;
  content?: string;
  label?: string;
  mode?: string;
}

export async function* streamChatResponse(
  url: string,
  body: object,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const err = await response.text().catch(() => "");
    throw new Error(err || `Stream failed (${response.status})`);
  }

  yield* readChatSseStream(response);
}

export async function* streamChatResponseForm(
  url: string,
  form: FormData,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
    signal,
  });

  if (!response.ok) {
    const err = await response.text().catch(() => "");
    throw new Error(err || `Stream failed (${response.status})`);
  }

  yield* readChatSseStream(response);
}

export async function* streamResponse(
  url: string,
  body: object,
): AsyncGenerator<string> {
  for await (const event of streamChatResponse(url, body)) {
    if (event.token) yield event.token;
  }
}

export async function* streamResponseForm(
  url: string,
  form: FormData,
): AsyncGenerator<string> {
  for await (const event of streamChatResponseForm(url, form)) {
    if (event.token) yield event.token;
  }
}

async function* readChatSseStream(response: Response): AsyncGenerator<ChatStreamEvent> {
  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6).trim();
      if (data === "[DONE]") return;
      try {
        const parsed = JSON.parse(data);
        const event: ChatStreamEvent = {};
        if (parsed.token) event.token = parsed.token;
        if (parsed.thinking) event.thinking = parsed.thinking;
        if (parsed.error) event.error = parsed.error;
        if (parsed.event) {
          Object.assign(event, parsed);
        }
        if (event.error) throw new Error(event.error);
        if (event.token || event.thinking || event.event) yield event;
      } catch (e) {
        if (e instanceof SyntaxError) continue;
        throw e;
      }
    }
  }
}
