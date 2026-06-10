import axios from "axios";
import type { DashboardOverview } from "@/lib/dashboardTypes";
import { getAuthToken, useAuthStore } from "@/lib/authStore";

/** Same-origin proxy via app/api/v1/[...path]/route.ts → BACKEND_URL (default 8000). */
export const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
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
  list: (lang?: string) => api.get("/agents/", { params: lang ? { lang } : {} }),
  create: (data: object) => api.post("/agents", data),
  get: (id: string) => api.get(`/agents/${id}`),
  update: (id: string, data: object) => api.patch(`/agents/${id}`, data),
  delete: (id: string) => api.delete(`/agents/${id}`),
  run: (id: string, data: object) => api.post(`/agents/${id}/run`, data),
  generate: (description: string) => api.post("/agents/generate", { description }),
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
  create: (data: object) => api.post("/workflows", data),
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
  deleteConversation: (id: string) => api.delete(`/chat/conversations/${id}`),
  deleteAllConversations: () => api.delete("/chat/conversations"),
  getMessages: (id: string) => api.get(`/chat/conversations/${id}/messages`),
  saveAsSkill: (id: string, data: object) => api.post(`/chat/conversations/${id}/save-as-skill`, data),
  saveToKnowledge: (id: string, data: object) => api.post(`/chat/conversations/${id}/save-to-knowledge`, data),
  sendMessage: (id: string, data: object) => api.post(`/chat/conversations/${id}/messages`, data),
  sendMessageWithFiles: (id: string, message: string, files: File[], stream = true) => {
    const form = new FormData();
    form.append("message", message);
    form.append("stream", stream ? "true" : "false");
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
  create: (data: object) => api.post("/knowledge", data),
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
};

// ── Tools ─────────────────────────────────────────────
export const toolsApi = {
  list: () => api.get("/tools"),
};

// ── Skills ────────────────────────────────────────────
export const skillsApi = {
  list: (lang?: string) => api.get("/skills", { params: lang ? { lang } : {} }),
  create: (data: object) => api.post("/skills", data),
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
  streamUrl: (interval = 30) => `/api/v1/dashboard/stream?interval=${interval}`,
};

// ── Digital Employees ───────────────────────────────
export const employeesApi = {
  list: () => api.get("/employees"),
  create: (data: object) => api.post("/employees", data),
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
  downloadRunUrl: (id: string, runId: string) => `${API_BASE}/employees/${id}/runs/${runId}/download`,
  saveRunToKnowledge: (id: string, runId: string, data: { kb_id?: string; kb_name?: string }) =>
    api.post(`/employees/${id}/runs/${runId}/save-to-knowledge`, data),
  schedulerStatus: () => api.get("/employees/scheduler/status"),
};

// ── Streaming helper ──────────────────────────────────
export async function* streamResponse(
  url: string,
  body: object,
): AsyncGenerator<string> {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const err = await response.text().catch(() => "");
    throw new Error(err || `Stream failed (${response.status})`);
  }

  yield* readSseStream(response);
}

export async function* streamResponseForm(
  url: string,
  form: FormData,
): AsyncGenerator<string> {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });

  if (!response.ok) {
    const err = await response.text().catch(() => "");
    throw new Error(err || `Stream failed (${response.status})`);
  }

  yield* readSseStream(response);
}

async function* readSseStream(response: Response): AsyncGenerator<string> {
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
        if (parsed.token) yield parsed.token;
        if (parsed.error) throw new Error(parsed.error);
      } catch (e) {
        if (e instanceof SyntaxError) continue;
        throw e;
      }
    }
  }
}
