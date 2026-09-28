"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  ArrowUpRight,
  Bell,
  Bot,
  Brain,
  Check,
  FileText,
  Folder,
  Home,
  Layers,
  LogOut,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Terminal,
  Trash2,
  Zap,
  Activity as ActivityIcon,
  ChevronRight,
  CalendarDays,
  FolderCode,
  RefreshCw,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CommandDialog,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
  CommandGroup,
} from "@/components/ui/command";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import { api, ApiError, labels, RecordItem, Run, State, terminal } from "./api";
import { Badge, Blank, Choice, RichText, withoutSynthesis } from "./common";
import { Login } from "./auth";
import { Automations } from "./automations";
import { useHistory } from "./history";
import { Editor } from "./editor";
import { Execution } from "./execution";
import { RemotePanel, SettingsPanel } from "./panels";
import { CalendarPanel } from "./calendar";
import { Dictation, ReadAloud } from "./voice";
import { ToolsPanel } from "./tools";
import { WorkspaceFiles } from "./workspace-files";
import { DailySummary } from "./daily-summary";
import { Pulse } from "./pulse";
const navigation = [
  ["Inicio", Home],
  ["Command", Terminal],
  ["Proyectos", Folder],
  ["Tareas", Check],
  ["Calendario", CalendarDays],
  ["Workspace", FolderCode],
  ["Memoria", Brain],
  ["Archivos", FileText],
  ["Workflows", Zap],
  ["Integraciones", Layers],
  ["Actividad", ActivityIcon],
  ["Ajustes", Settings],
] as const;
const kinds: Record<string, string> = {
  Proyectos: "projects",
  Tareas: "tasks",
  Memoria: "memory",
  Archivos: "documents",
  Workflows: "workflows",
};
const hints = [
  "¿Qué debería priorizar hoy?",
  "Quiero crear un videojuego. Organiza el desarrollo.",
  "Busca información en mis documentos.",
];
export default function Pablo() {
  const [state, setState] = useState<State | null>(null);
  const [auth, setAuth] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [view, setView] = useState("Inicio");
  const [editor, setEditor] = useState<{
    kind: string;
    item?: RecordItem;
  } | null>(null);
  const [deleting, setDeleting] = useState<RecordItem | null>(null);
  const [goal, setGoal] = useState("");
  const mode = "CHAT";
  const [project, setProject] = useState("all");
  const [conversation, setConversation] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [commandOpen, setCommandOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [reindexing, setReindexing] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const refreshGeneration = useRef(0);
  const refresh = useCallback(async () => {
    const generation = ++refreshGeneration.current;
    try {
      const data = await api<State>("/state");
      if (generation !== refreshGeneration.current) return;
      setState(data);
      setAuth(true);
      setLoadError("");
    } catch (e) {
      setLoadError((e as Error).message);
      if (e instanceof ApiError && e.status === 401) setAuth(false);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    let live = true;
    api<State>("/state")
      .then((data) => {
        if (live) {
          setState(data);
          setAuth(true);
        }
      })
      .catch((e) => {
        if (live) setLoadError(e.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    const updateConnection = () => setOnline(navigator.onLine);
    updateConnection();
    window.addEventListener("online", updateConnection);
    window.addEventListener("offline", updateConnection);
    return () => {
      window.removeEventListener("online", updateConnection);
      window.removeEventListener("offline", updateConnection);
    };
  }, []);
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setCommandOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const activeKey =
    state?.runs
      .filter((r) => !terminal.has(r.status) && r.status !== "WAITING_APPROVAL")
      .map((r) => r.id)
      .join(",") || "";
  useEffect(() => {
    // Scheduled runs can start even when no conversation is executing.
    const update = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const timer = setInterval(update, 15000);
    document.addEventListener("visibilitychange", update);
    window.addEventListener("online", update);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", update);
      window.removeEventListener("online", update);
    };
  }, [refresh]);
  useEffect(() => {
    if (!activeKey) return;
    const sources = activeKey.split(",").map((id) => {
      const source = new EventSource("/api/v1/runs/" + id + "/events");
      source.onmessage = (e) => {
        const run = JSON.parse(e.data) as Run;
        setState((previous) =>
          previous
            ? {
                ...previous,
                runs: previous.runs.map((r) => (r.id === run.id ? run : r)),
              }
            : previous,
        );
        if (terminal.has(run.status) || run.status === "WAITING_APPROVAL") {
          source.close();
          void refresh();
        }
      };
      source.onerror = () => source.close();
      return source;
    });
    const timer = setInterval(() => void refresh(), 4000);
    return () => {
      sources.forEach((s) => s.close());
      clearInterval(timer);
    };
  }, [activeKey, refresh]);
  const history = useHistory(
    conversation,
    state?.runs
      .filter((r) => r.conversation_id === conversation)
      .map((r) => r.id + ":" + r.status)
      .join(",") || "",
  );
  const messagesRef = useRef<HTMLDivElement>(null);
  const latestMessageId = history.messages.at(-1)?.id;
  useEffect(() => {
    const element = messagesRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [conversation, latestMessageId, view]);
  async function openRun(id: string) {
    try {
      const item = await api<Run>("/runs/" + id);
      setState((previous) =>
        previous
          ? {
              ...previous,
              runs: [item, ...previous.runs.filter((r) => r.id !== id)],
            }
          : previous,
      );
      setSelectedRun(id);
      setConversation(item.conversation_id);
      setView("Command");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  function navigate(name: string) {
    setView(name);
    setFilter("");
  }
  async function send(custom?: string) {
    const text = custom || goal;
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      const run = await api<Run>("/commands", "POST", {
        goal: text,
        mode,
        project_id: project === "all" ? null : project,
        conversation_id: view === "Command" ? conversation : null,
      });
      setConversation(run.conversation_id);
      setGoal("");
      setView("Command");
      setSelectedRun(null);
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function complete(item: RecordItem) {
    try {
      await api("/items/" + item.id, "PUT", {
        title: item.title,
        description: item.description || "",
        project_id: item.project_id || null,
        status: item.status === "DONE" ? "TODO" : "DONE",
        priority: item.priority || "MEDIUM",
        due: item.due || "",
        category: item.category || "user",
        pinned: item.pinned || false,
        dependencies: item.dependencies || [],
        repository: item.repository || "",
        version: item.version,
      });
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  if (loading)
    return (
      <div className="loading-space">
        <Skeleton className="h-12 w-56" />
        <Skeleton className="h-48 w-full" />
        <p>Cargando tu espacio…</p>
      </div>
    );
  if (!auth || !state)
    return (
      <>
        <Login onLogin={() => void refresh()} />
        {loadError && !loadError.includes("sesión") && (
          <p className="connection-error">{loadError}</p>
        )}
      </>
    );
  const projects = state.items.filter((i) => i.kind === "projects");
  const tasks = state.items.filter((i) => i.kind === "tasks");
  const pending = tasks.filter(
    (t) => !["DONE", "CANCELLED"].includes(t.status || ""),
  );
  const memories = state.items.filter((i) => i.kind === "memory");
  const docs = state.items.filter((i) => i.kind === "documents");
  const filtered = state.items.filter(
    (i) =>
      i.kind === kinds[view] &&
      (project === "all" || i.project_id === project || i.id === project) &&
      `${i.title} ${i.description || ""}`
        .toLowerCase()
        .includes(filter.toLowerCase()),
  );
  const focus = [...pending]
    .sort(
      (a, b) =>
        (({ HIGH: 0, MEDIUM: 1, LOW: 2 })[a.priority as "HIGH"] ?? 1) -
        ({ HIGH: 0, MEDIUM: 1, LOW: 2 }[b.priority as "HIGH"] ?? 1),
    )
    .slice(0, 4);
  const messages = history.messages;

  const date = new Intl.DateTimeFormat("es", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: state.profile.timezone,
  }).format(new Date());
  const composer = (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      <div className="composer-input">
        <Sparkles size={23} />
        <Textarea
          aria-label="¿Qué quieres conseguir?"
          placeholder="¿Qué quieres conseguir?"
          value={goal}
          maxLength={12000}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
      </div>
      <Dictation
        disabled={busy}
        onText={(text) =>
          setGoal((value) =>
            (value + (value ? " " : "") + text).slice(0, 12000),
          )
        }
      />
      <div className="composer-footer">
        <Button
          type="submit"
          size="icon"
          aria-label="Enviar objetivo"
          disabled={busy || !goal.trim()}
        >
          <ArrowUp size={19} />
        </Button>
      </div>
      <p className="muted" role="status">
        Pide lo que necesitas. Revisarás las acciones sensibles antes de que se ejecuten.
      </p>
    </form>
  );
  function projectCard(p: RecordItem) {
    const associated = tasks.filter((t) => t.project_id === p.id);
    const progress = associated.length
      ? (associated.filter((t) => t.status === "DONE").length /
          associated.length) *
        100
      : 0;
    return (
      <article className="project-card panel" key={p.id}>
        <div className="row between">
          <span className="project-icon">
            <Folder size={19} />
          </span>
          <Badge value={p.status || "IDEA"} />
        </div>
        <button
          className="project-title"
          onClick={() => {
            setProject(p.id);
            navigate("Tareas");
          }}
        >
          {p.title}
          <ArrowUpRight size={16} />
        </button>
        <p>
          {p.description ||
            "Añade un objetivo para dar contexto a este proyecto."}
        </p>
        <div className="row between muted">
          <span>
            {associated.length ? `${associated.filter((t) => t.status === "DONE").length}/${associated.length} tareas terminadas` : "Sin tareas asociadas"}
          </span>
          {associated.length > 0 && <span>{Math.round(progress)}%</span>}
        </div>
        {associated.length > 0 && <Progress value={progress} />}
        <div className="row between">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditor({ kind: "projects", item: p })}
          >
            Editar
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={"Eliminar " + p.title}
            onClick={() => setDeleting(p)}
          >
            <Trash2 size={15} />
          </Button>
        </div>
      </article>
    );
  }
  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="brand">
          <img className="logo" src="/assets/pablo-logo-transparent.png" alt="" width={44} height={44} />
          <span>
            PABLO <em>OS</em>
          </span>
        </SidebarHeader>
        <SidebarContent>
          <button
            className="sidebar-search"
            onClick={() => setCommandOpen(true)}
          >
            <Search size={16} />
            Buscar en tu espacio<kbd>Ctrl K</kbd>
          </button>
          <div className="nav-label">ESPACIO DE TRABAJO</div>
          <SidebarMenu>
            {navigation.map(([name, Icon]) => (
              <SidebarMenuItem key={name}>
                <SidebarMenuButton
                  isActive={view === name}
                  onClick={() => navigate(name)}
                  className="nav-item"
                >
                  <Icon />
                  <span>{name}</span>
                  {name === "Tareas" && pending.length > 0 && (
                    <span className="nav-count">{pending.length}</span>
                  )}
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
          <div className="sidebar-context">
            <ShieldCheck size={17} />
            <div>
              <strong>Siempre bajo tu control</strong>
              <p>
                {state.profile.autonomy === "ASSISTED"
                  ? "Los cambios necesitan tu aprobación."
                  : state.profile.autonomy === "MANUAL"
                    ? "Cada herramienta necesita aprobación."
                    : "Cambios locales autorizados."}
              </p>
            </div>
          </div>
        </SidebarContent>
        <SidebarFooter>
          <div className="profile">
            <span className="avatar">{state.profile.name.slice(0, 1)}</span>
            <div>
              <strong>{state.profile.name}</strong>
              <p>Espacio personal</p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Cerrar sesión"
              onClick={async () => {
                try {
                  await api("/auth/logout", "POST");
                  setAuth(false);
                  setState(null);
                  setConversation(null);
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              <LogOut size={16} />
            </Button>
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset className="workspace">
        <header className="topbar">
          <div className="row">
            <SidebarTrigger />
            <span className="breadcrumb">Mi espacio</span>
            <ChevronRight size={14} />
            <strong>{view}</strong>
          </div>
          <div className="row">
            <span className={`runtime-badge ${online ? "" : "offline"}`}>
              {!online
                ? "Sin conexión"
                : state.profile.demo
                ? "MOCK · modo demo"
                : state.ai.configured
                  ? "Proveedor configurado"
                  : "Modo local · sin IA"}
            </span>
            <button
              className="notification-button"
              aria-label={`${state.approvals.length} aprobaciones pendientes`}
              onClick={() => {
                const approval = state.approvals[0];
                if (approval) void openRun(approval.run_id);
                else toast("No tienes aprobaciones pendientes.");
              }}
            >
              <Bell size={18} />
              {state.approvals.length > 0 && (
                <span>{state.approvals.length}</span>
              )}
            </button>
          </div>
        </header>
        <main className="content">
          {loadError && (
            <div className="notice" role="alert">
              No se pudo actualizar: {loadError}{" "}
              <Button
                variant="outline"
                size="sm"
                onClick={() => void refresh()}
              >
                Reintentar
              </Button>
            </div>
          )}
          {state.truncated && (
            <p className="notice">
              Hay más de 5.000 elementos. La vista está limitada; la exportación
              conserva todos tus datos.
            </p>
          )}
          {!state.ai.configured && !state.profile.demo && view === "Inicio" && (
            <div className="setup-banner">
              <div>
                <strong>Tu espacio local está listo</strong>
                <p>
                  Gestiona tus proyectos, agenda y archivos. Conecta un
                  proveedor para conversar con IA.
                </p>
              </div>
              <Button variant="outline" onClick={() => navigate("Ajustes")}>
                Configurar IA
                <ArrowUpRight size={15} />
              </Button>
            </div>
          )}
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {view === "Inicio"
                  ? date
                  : "TU ESPACIO / " + view.toUpperCase()}
              </div>
              <h1>
                {view === "Inicio"
                  ? `Hola, ${state.profile.name}.`
                  : view === "Command"
                    ? "De una idea al siguiente paso."
                    : view}
              </h1>
              <p>
                {view === "Inicio"
                  ? "Pon intención a tu día. Elige lo que importa."
                  : view === "Command"
                    ? "Pregunta, prepara un plan o ejecuta acciones controladas."
                    : view === "Proyectos"
                      ? "Un lugar para cada objetivo."
                      : view === "Memoria"
                        ? "Lo que recuerdas, visible y bajo tu control."
                        : view === "Archivos"
                          ? "Tus documentos, convertidos en contexto."
                        : view === "Integraciones"
                          ? "Tus servicios trabajando juntos, desde una sola conversación."
                          : ""}
              </p>
            </div>
            {kinds[view] && view !== "Archivos" && (
              <Button onClick={() => setEditor({ kind: kinds[view] })}>
                <Plus size={17} />
                Crear{" "}
                {view === "Proyectos"
                  ? "proyecto"
                  : view === "Tareas"
                    ? "tarea"
                    : view === "Memoria"
                      ? "recuerdo"
                      : "workflow"}
              </Button>
            )}
            {view === "Archivos" && (
              <Button
                disabled={uploading}
                onClick={() => fileRef.current?.click()}
              >
                <Plus size={17} />
                {uploading ? "Indexando…" : "Subir documento"}
              </Button>
            )}
          </div>
          {view === "Inicio" && (
            <>
              <Pulse
                pulse={state.pulse}
                busy={busy}
                onPrompt={(prompt) => void send(prompt)}
                onNavigate={navigate}
              />
              <DailySummary run={state.daily_summary} onRun={(id) => void openRun(id)} />
              <div className="home-composer">
                {composer}
                <div className="suggestions">
                  {hints.map((hint, i) => (
                    <button
                      key={hint}
                      onClick={() => {
                        setGoal(hint);

                      }}
                    >
                      {
                        [
                          <Check size={15} key="c" />,
                          <Folder size={15} key="f" />,
                          <FileText size={15} key="d" />,
                        ][i]
                      }
                      {
                        [
                          "Organizar mi día",
                          "Empezar un proyecto",
                          "Consultar documentos",
                        ][i]
                      }
                      <ArrowUpRight size={14} />
                    </button>
                  ))}
                </div>
              </div>
              <div className="metric-strip">
                <div>
                  <strong>{pending.length}</strong>
                  <span>Tareas pendientes</span>
                </div>
                <div>
                  <strong>
                    {
                      projects.filter(
                        (p) =>
                          !["COMPLETED", "ARCHIVED"].includes(p.status || ""),
                      ).length
                    }
                  </strong>
                  <span>Proyectos abiertos</span>
                </div>
                <div>
                  <strong>{docs.length}</strong>
                  <span>Documentos indexados</span>
                </div>
                <div>
                  <strong>{state.approvals.length}</strong>
                  <span>Por aprobar</span>
                </div>
              </div>
              <div className="home-grid">
                <section className="panel focus-panel">
                  <div className="section-header">
                    <div>
                      <div className="eyebrow">DA EL SIGUIENTE PASO</div>
                      <h2>Tu foco</h2>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate("Tareas")}
                    >
                      Ver tareas
                      <ArrowUpRight size={15} />
                    </Button>
                  </div>
                  {!focus.length ? (
                    <Blank title="Espacio para lo importante">
                      Crea una tarea o pide un plan para tu próximo proyecto.
                      <Button
                        onClick={() => setEditor({ kind: "tasks" })}
                        variant="outline"
                      >
                        Crear mi primera tarea
                      </Button>
                    </Blank>
                  ) : (
                    focus.map((t, i) => (
                      <div className="focus-task" key={t.id}>
                        <button
                          className="task-check"
                          aria-label={"Completar " + t.title}
                          onClick={() => void complete(t)}
                        >
                          <Check size={15} />
                        </button>
                        <div>
                          <span className="focus-number">0{i + 1}</span>
                          <button
                            onClick={() =>
                              setEditor({ kind: "tasks", item: t })
                            }
                          >
                            {t.title}
                          </button>
                          <p>
                            {projects.find((p) => p.id === t.project_id)
                              ?.title || "Personal"}
                            {t.due ? " · " + t.due : ""}
                          </p>
                        </div>
                        <Badge value={t.priority || "MEDIUM"} />
                      </div>
                    ))
                  )}
                </section>
                <section className="panel next-panel">
                  <div className="eyebrow">EN TU RADAR</div>
                  <h2>Actividad reciente</h2>
                  {state.runs.length ? (
                    state.runs.slice(0, 3).map((r) => (
                      <button
                        className="run-preview"
                        key={r.id}
                        onClick={() => void openRun(r.id)}
                      >
                        <span className="mini-orb">
                          <Bot size={16} />
                        </span>
                        <div>
                          <strong>{r.goal}</strong>
                          <p>{labels[r.status] || r.status}</p>
                        </div>
                        <ChevronRight size={16} />
                      </button>
                    ))
                  ) : (
                    <Blank title="Todo listo para empezar">
                      Tu primera ejecución aparecerá aquí, con sus pasos y
                      resultados.
                    </Blank>
                  )}
                  <div className="calendar-note">
                    <span>Tu agenda</span>
                    <Badge value="Disponible" />
                    <p>
                      Organiza tus eventos y consulta las fechas de tus tareas.
                    </p>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate("Calendario")}
                    >
                      Abrir calendario
                      <ArrowUpRight size={14} />
                    </Button>
                  </div>
                </section>
              </div>
              <div className="section-header project-heading">
                <h2>Proyectos en marcha</h2>
                <Button
                  variant="ghost"
                  onClick={() => setEditor({ kind: "projects" })}
                >
                  <Plus size={16} />
                  Nuevo proyecto
                </Button>
              </div>
              {projects.length ? (
                <div className="cards">
                  {projects.slice(0, 3).map(projectCard)}
                </div>
              ) : (
                <button
                  className="new-project-empty"
                  onClick={() => setEditor({ kind: "projects" })}
                >
                  <Plus size={22} />
                  <span>Tu próximo proyecto empieza aquí</span>
                  <ArrowUpRight size={18} />
                </button>
              )}
            </>
          )}
          {view === "Command" && (
            <div className="command-layout">
              <aside className="conversation-list">
                <Button
                  variant="outline"
                  onClick={() => {
                    setConversation(null);
                    setGoal("");
                  }}
                >
                  <Plus size={16} />
                  Nueva conversación
                </Button>
                {conversation && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      const item = state.items.find(
                        (i) => i.id === conversation,
                      );
                      if (item) setDeleting(item);
                    }}
                  >
                    <Trash2 size={14} />
                    Eliminar conversación
                  </Button>
                )}
                {state.items
                  .filter((i) => i.kind === "conversations")
                  .map((c) => (
                    <button
                      className={conversation === c.id ? "selected" : ""}
                      key={c.id}
                      onClick={() => setConversation(c.id)}
                    >
                      {c.title}
                    </button>
                  ))}
              </aside>
              <section className="chat-area">
                <div className="row context-select">
                  <Choice
                    value={project}
                    onChange={setProject}
                    label="Contexto de proyecto"
                    options={[
                      ["all", "Contexto de conversación"],
                      ...projects.map(
                        (p) => [p.id, p.title] as [string, string],
                      ),
                    ]}
                  />
                  <span className="muted">
                    {state.ai.configured && !state.profile.demo
                      ? state.ai.model
                      : "Plantillas locales · interpretación limitada"}
                  </span>
                </div>
                <div className="messages" ref={messagesRef} role="log" aria-label="Mensajes de la conversación" aria-live="polite">
                  {history.error && (
                    <p className="error" role="alert">
                      {history.error}
                    </p>
                  )}
                  {history.hasMore && (
                    <Button
                      variant="outline"
                      onClick={() => void history.loadOlder()}
                    >
                      Cargar mensajes anteriores
                    </Button>
                  )}
                  {!messages.length && (
                    <Blank title="¿Qué quieres conseguir?">
                      Empieza por un objetivo. Puedes revisar el plan y
                      autorizar cada cambio.
                    </Blank>
                  )}
                  {messages.map((m) => (
                    <article key={m.id} className={"message " + m.role}>
                      <div className="message-author">
                        {m.role === "user" ? state.profile.name : "PABLO OS"}
                      </div>
                      <RichText text={m.role === "assistant" ? withoutSynthesis(m.content || "") : m.content || ""} />
                      {m.role === "assistant" && (
                        <ReadAloud text={withoutSynthesis(m.content || "")} />
                      )}
                    </article>
                  ))}
                </div>
                {state.runs.filter(r => r.conversation_id === conversation && (!terminal.has(r.status) || r.id === selectedRun)).map(r => (
                  <Execution key={r.id} run={r} approvals={state.approvals}
                    close={() => setSelectedRun(null)} refresh={() => void refresh()} onError={toast.error} />
                ))}
                {composer}
              </section>
            </div>
          )}
          {view === "Workflows" && (
            <Automations projects={projects} onRun={(id) => void openRun(id)} />
          )}
          {view === "Calendario" && (
            <CalendarPanel projects={projects} tasks={tasks} />
          )}
          {view === "Workspace" && (
            <><WorkspaceFiles />
            <details className="panel">
            <summary style={{cursor: "pointer"}}>Herramientas avanzadas</summary>
            <ToolsPanel
              workspaceOnly
              projects={projects}
              onRun={(id) => void openRun(id)}
            />
            </details>
            </>
          )}
          {kinds[view] && (
            <>
              <div className="list-toolbar">
                <div className="search-field">
                  <Search size={17} />
                  <Input
                    aria-label="Filtrar elementos"
                    placeholder={"Buscar en " + view.toLowerCase()}
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  />
                </div>
                {view !== "Proyectos" && (
                  <Choice
                    label="Filtrar proyecto"
                    value={project}
                    onChange={setProject}
                    options={[
                      ["all", "Todos los proyectos"],
                      ...projects.map(
                        (p) => [p.id, p.title] as [string, string],
                      ),
                    ]}
                  />
                )}
              </div>
              {view === "Memoria" && !state.profile.memory_enabled && (
                <p className="notice">
                  La memoria está desactivada. Puedes consultar o eliminar lo
                  que guardaste, pero no se usa como contexto.
                </p>
              )}
              {view === "Workflows" && (
                <p className="notice">
                  Estas instrucciones guardadas se pueden reutilizar en Command.
                  Arriba puedes programar objetivos para ejecutarlos
                  automáticamente.
                </p>
              )}
              {!filtered.length ? (
                <Blank title="Todavía no hay elementos">
                  {filter
                    ? "Prueba otra búsqueda."
                    : view === "Archivos"
                      ? "Sube PDF, DOCX, TXT, Markdown o código. Máximo 5 MB."
                      : "Crea el primero para empezar."}
                </Blank>
              ) : view === "Proyectos" ? (
                <div className="cards">{filtered.map(projectCard)}</div>
              ) : (
                <div className={view === "Memoria" ? "cards" : "record-list"}>
                  {filtered.map((item) => (
                    <article
                      className={
                        "panel record " +
                        (view === "Memoria" ? "memory-card" : "")
                      }
                      key={item.id}
                    >
                      {view === "Tareas" && (
                        <button
                          className={
                            "task-check " +
                            (item.status === "DONE" ? "checked" : "")
                          }
                          aria-label={"Cambiar estado de " + item.title}
                          onClick={() => void complete(item)}
                        >
                          <Check size={15} />
                        </button>
                      )}
                      <div className="record-main">
                        <h2>{item.title}</h2>
                        <p>{item.description || "Sin descripción"}</p>
                        <div className="record-meta">
                          {view === "Tareas" && (
                            <>
                              <Badge value={item.status || "TODO"} />
                              <Badge value={item.priority || "MEDIUM"} />
                              {item.due && <span>{item.due}</span>}
                            </>
                          )}
                          {view === "Memoria" && (
                            <span>
                              {item.pinned ? "Fijado · " : ""}
                              {item.category}
                            </span>
                          )}
                          {view === "Archivos" && (
                            <span>
                              {item.chunks || 0} fragmentos
                              {item.chunks
                                ? " · indexado"
                                : " · sin texto indexado"}
                            </span>
                          )}
                          {item.project_id && (
                            <span>
                              {
                                projects.find((p) => p.id === item.project_id)
                                  ?.title
                              }
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="record-actions">
                        {view === "Archivos" && (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={reindexing !== null}
                            onClick={async () => {
                              setReindexing(item.id);
                              try {
                                await api(
                                  "/documents/" + item.id + "/reindex",
                                  "POST",
                                );
                                await refresh();
                                toast.success(
                                  "Índice del documento actualizado.",
                                );
                              } catch (e) {
                                toast.error((e as Error).message);
                              } finally {
                                setReindexing(null);
                              }
                            }}
                          >
                            <RefreshCw size={14} />
                            {reindexing === item.id
                              ? "Indexando…"
                              : "Reindexar"}
                          </Button>
                        )}
                        {view === "Workflows" && (
                          <Button
                            variant="outline"
                            onClick={() => {
                              setGoal(item.description || item.title);

                              navigate("Command");
                            }}
                          >
                            Preparar ejecución
                          </Button>
                        )}
                        {view !== "Archivos" && (
                          <Button
                            variant="ghost"
                            onClick={() =>
                              setEditor({ kind: kinds[view], item })
                            }
                          >
                            Editar
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={"Eliminar " + item.title}
                          onClick={() => setDeleting(item)}
                        >
                          <Trash2 size={16} />
                        </Button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              {view === "Archivos" &&
                state.items.some((i) => i.kind === "artifacts") && (
                  <section className="panel">
                    <h2>Informes generados</h2>
                    {state.items
                      .filter((i) => i.kind === "artifacts")
                      .map((i) => (
                        <details key={i.id}>
                          <summary>{i.title}</summary>
                          <RichText text={i.description || ""} />
                        </details>
                      ))}
                  </section>
                )}
            </>
          )}
          {["Integraciones", "Actividad"].includes(view) && (
            <RemotePanel
              key={view}
              view={view}
              onPrompt={(prompt) => void send(prompt)}
            />
          )}
          {view === "Ajustes" && (
            <SettingsPanel
              profile={state.profile}
              refresh={() => void refresh()}
              onDeleted={() => {
                setAuth(false);
                setState(null);
                setConversation(null);
                setSelectedRun(null);
                setView("Inicio");
              }}
            />
          )}
          <footer className="workspace-footer">
            <span>
              PABLO OS <span className="muted">/</span> TU ESPACIO PERSONAL
            </span>
            <span>
              {memories.length} recuerdos ·{" "}
              {state.profile.autonomy.toLowerCase()}
            </span>
          </footer>
        </main>
      </SidebarInset>
      <input
        type="file"
        ref={fileRef}
        hidden
        accept=".pdf,.docx,.txt,.md,.py,.js,.ts,.tsx,.cs,.json,.csv,.sql"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          if (file.size > 5 * 1024 * 1024) {
            toast.error("El documento supera el máximo de 5 MB.");
            e.target.value = "";
            return;
          }
          setUploading(true);
          try {
            const form = new FormData();
            form.append("file", file);
            await api(
              "/documents" +
                (project !== "all"
                  ? "?project_id=" + encodeURIComponent(project)
                  : ""),
              "POST",
              form,
            );
            await refresh();
            toast.success("Documento indexado. Ya puedes consultarlo.");
          } catch (e) {
            toast.error((e as Error).message);
          } finally {
            setUploading(false);
            if (fileRef.current) fileRef.current.value = "";
          }
        }}
      />
      {editor && (
        <Editor
          kind={editor.kind}
          item={editor.item}
          projects={projects}
          close={() => setEditor(null)}
          saved={() => void refresh()}
        />
      )}
      <AlertDialog
        open={!!deleting}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar {deleting?.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleting?.kind === "projects"
                ? "Se eliminará el proyecto. Sus tareas, archivos, eventos y conversaciones se conservarán en el espacio general. Sus automatizaciones quedarán en pausa."
                : "Se eliminará este elemento. Los documentos pierden sus fragmentos; las conversaciones, sus mensajes y ejecuciones. Esta acción no puede deshacerse."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (!deleting) return;
                try {
                  await api("/items/" + deleting.id, "DELETE");
                  if (deleting.id === project) setProject("all");
                  if (deleting.id === conversation) setConversation(null);
                  await refresh();
                  toast.success("Elemento eliminado.");
                } catch (e) {
                  toast.error((e as Error).message);
                }
                setDeleting(null);
              }}
            >
              Eliminar definitivamente
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <CommandDialog open={commandOpen} onOpenChange={setCommandOpen}>
        <CommandInput placeholder="Buscar proyectos, tareas, documentos…" />
        <CommandList>
          <CommandEmpty>No hay resultados.</CommandEmpty>
          <CommandGroup heading="Ir a">
            {navigation.map(([name, Icon]) => (
              <CommandItem
                key={name}
                onSelect={() => {
                  navigate(name);
                  setCommandOpen(false);
                }}
              >
                <Icon size={16} />
                {name}
              </CommandItem>
            ))}
          </CommandGroup>
          <CommandGroup heading="Tu espacio">
            {state.items
              .filter((i) => !["messages", "artifacts"].includes(i.kind))
              .map((i) => (
                <CommandItem
                  key={i.id}
                  value={i.title + " " + i.id}
                  onSelect={() => {
                    if (i.kind === "conversations") {
                      setConversation(i.id);
                      navigate("Command");
                    } else {
                      navigate(
                        Object.keys(kinds).find((k) => kinds[k] === i.kind) ||
                          "Inicio",
                      );
                      setFilter(i.title);
                    }
                    setCommandOpen(false);
                  }}
                >
                  {i.title}
                  <span className="muted">{i.kind}</span>
                </CommandItem>
              ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
      <Toaster theme="light" richColors />
    </SidebarProvider>
  );
}

