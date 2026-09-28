export type RecordItem = {
  id: string;
  kind: string;
  title: string;
  description?: string;
  project_id?: string | null;
  status?: string;
  priority?: string;
  due?: string;
  category?: string;
  pinned?: boolean;
  dependencies?: string[];
  repository?: string;
  version: number;
  created_at: string;
  content?: string;
  role?: string;
  conversation_id?: string;
  chunks?: number;
};
export type Step = {
  tool: string;
  arguments: Record<string, unknown>;
  depends_on: number[];
  status: string;
  result: unknown;
};
export type Run = {
  id: string;
  goal: string;
  mode: string;
  status: string;
  conversation_id: string;
  plan: Step[];
  result: string;
  usage: { provider?: string; total_tokens?: number };
  created_at: string;
};
export type Profile = {
  name: string;
  timezone: string;
  autonomy: string;
  memory_enabled: boolean;
  memory_categories: string[];
  demo: boolean;
};
export type Approval = {
  id: string;
  run_id: string;
  tool: string;
  payload: Record<string, unknown>;
  status: string;
};
export type PulseSignal = {
  kind: string;
  title: string;
  detail: string;
  destination?: string;
  run_id?: string;
};
export type Pulse = {
  generated_at: string;
  score: number;
  label: string;
  tone: "calm" | "focus" | "attention";
  greeting: string;
  headline: string;
  pending: number;
  overdue: number;
  due_today: number;
  next_action: { title: string; detail: string; destination?: string; prompt?: string };
  signals: PulseSignal[];
  organize_prompt: string;
};
export type State = {
  daily_summary?: Run | null;
  truncated?: boolean;
  profile: Profile;
  items: RecordItem[];
  runs: Run[];
  approvals: Approval[];
  pulse: Pulse;
  ai: { configured: boolean; model: string; embeddings: boolean };
};
export type Agent = {
  name: string;
  description: string;
  status: string;
  tools: string[];
};
export type Integration = {
  id?: string;
  name: string;
  status: string;
  detail: string;
  configured?: boolean;
  config?: Record<string, unknown>;
  scopes?: string[];
  verified?: boolean;
};
export type Activity = {
  id: string;
  action: string;
  status: string;
  created_at: string;
  detail: Record<string, unknown>;
};
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const upload = body instanceof FormData;
  const response = await fetch("/api/v1" + path, {
    method,
    credentials: "same-origin",
    signal: AbortSignal.timeout(upload ? 120000 : 30000),
    headers: {
      "X-Pablo-Request": "1",
      ...(!upload && body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? (upload ? body : JSON.stringify(body)) : undefined,
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      const value = JSON.parse(text);
      message =
        typeof value.detail === "string"
          ? value.detail
          : "Comprueba los campos del formulario.";
    } catch {}
    throw new ApiError(message || `Error ${response.status}`, response.status);
  }
  return response.json();
}
export const labels: Record<string, string> = {
  TODO: "Pendiente",
  PLANNED: "Planificado",
  IN_PROGRESS: "En curso",
  WAITING_APPROVAL: "Espera aprobación",
  BLOCKED: "Bloqueado",
  TESTING: "En pruebas",
  DONE: "Completado",
  FAILED: "Error",
  CANCELLED: "Cancelado",
  QUEUED: "En cola",
  RUNNING: "En ejecución",
  COMPLETED: "Completado",
  ACTIVE: "Activo",
  IDEA: "Idea",
  PLANNING: "Planificación",
  REVIEW: "En revisión",
  ARCHIVED: "Archivado",
  HIGH: "Alta",
  MEDIUM: "Media",
  LOW: "Baja",
  CONNECTED: "Conectado",
  AVAILABLE: "Disponible",
  NEEDS_AUTH: "Necesita conexión",
  NOT_CONFIGURED: "Sin configurar",
  DISCONNECTED: "Desconectado",
  CONFIGURED: "Configurado",
  PUBLIC_READ: "Lectura pública",
  ERROR: "Necesita atención",
  SAFE: "Consulta",
  MODERATE: "Cambio local",
  CRITICAL: "Requiere aprobación",
  PENDING: "Pendiente",
};
export const terminal = new Set([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "BLOCKED",
  "PLANNED",
]);

export const toolLabels: Record<string, string> = {
  "tasks.list": "Consultar tareas",
  "projects.create": "Crear proyecto",
  "tasks.create": "Crear tarea",
  "memory.search": "Consultar memoria",
  "documents.search": "Buscar en documentos",
  "github.inspect": "Consultar repositorio",
  "report.create": "Guardar informe",
};
