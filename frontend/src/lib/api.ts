import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
});

// ── Agents ──────────────────────────────────────────
export const agentsApi = {
  list: () => api.get("/agents/"),
  create: (data: object) => api.post("/agents/", data),
  get: (id: string) => api.get(`/agents/${id}`),
  update: (id: string, data: object) => api.patch(`/agents/${id}`, data),
  delete: (id: string) => api.delete(`/agents/${id}`),
  run: (id: string, data: object) => api.post(`/agents/${id}/run`, data),
  generate: (description: string) => api.post("/agents/generate", { description }),
  seedTemplates: () => api.post("/agents/seed-templates"),
};

// ── Workflows ────────────────────────────────────────
export const workflowsApi = {
  list: () => api.get("/workflows/"),
  create: (data: object) => api.post("/workflows/", data),
  get: (id: string) => api.get(`/workflows/${id}`),
  update: (id: string, data: object) => api.patch(`/workflows/${id}`, data),
  delete: (id: string) => api.delete(`/workflows/${id}`),
  execute: (id: string, data: object) => api.post(`/workflows/${id}/execute`, data),
  executions: (id: string) => api.get(`/workflows/${id}/executions`),
  seedTemplates: () => api.post("/workflows/seed-templates"),
};

// ── Chat ─────────────────────────────────────────────
export const chatApi = {
  createConversation: (data: object) => api.post("/chat/conversations", data),
  listConversations: () => api.get("/chat/conversations"),
  getMessages: (id: string) => api.get(`/chat/conversations/${id}/messages`),
  sendMessage: (id: string, data: object) => api.post(`/chat/conversations/${id}/messages`, data),
  quickChat: (data: object) => api.post("/chat/quick", data),
};

// ── Knowledge Base ───────────────────────────────────
export const knowledgeApi = {
  list: () => api.get("/knowledge/"),
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
  search: (kbId: string, data: object) => api.post(`/knowledge/${kbId}/search`, data),
};

// ── Models ────────────────────────────────────────────
export const modelsApi = {
  listAvailable: () => api.get("/models/available"),
  listConfigs: () => api.get("/models/configs"),
};

// ── Tools ─────────────────────────────────────────────
export const toolsApi = {
  list: () => api.get("/tools/"),
};

// ── Streaming helper ──────────────────────────────────
export async function* streamResponse(
  url: string,
  body: object,
): AsyncGenerator<string> {
  const response = await fetch(`${API_URL}/api/v1${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const err = await response.text().catch(() => "");
    throw new Error(err || `Stream failed (${response.status})`);
  }

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
