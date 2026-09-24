import { useCallback, useEffect, useState } from "react";
import { Bot, FolderCode, Play, RefreshCw, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Agent, RecordItem, Run, api, toolLabels } from "./api";
import { Badge, Blank, Choice } from "./common";
import { toast } from "sonner";

type Tool = { id: string; risk: string; agent: string };
const guides: Record<string, [string, string]> = {
  "Software Engineer": ["Programación", "Prepara proyectos de código, modifica archivos y ejecuta programas en tu carpeta de trabajo."],
  GitHub: ["Repositorios de GitHub", "Consulta código y prepara cambios en tus repositorios. Las acciones privadas necesitan conexión."],
  DevOps: ["Entorno de trabajo", "Consulta las acciones disponibles para revisar tu entorno técnico."],
  Research: ["Investigación", "Busca información, consulta fuentes y guarda informes o decisiones."],
  Study: ["Estudio", "Consulta tus documentos y recupera información para estudiar."],
  Productivity: ["Organización personal", "Consulta y gestiona tareas, proyectos y otros elementos de tu espacio."],
  Email: ["Correo de Gmail", "Busca y lee correos. También puedes preparar un envío para revisarlo y autorizarlo."],
  Calendar: ["Agenda y eventos", "Consulta tu agenda o crea eventos. El nombre de la acción indica si usa Google Calendar."],
  Automation: ["Automatizaciones", "Programa objetivos y gestiona sus horarios. PABLO OS debe estar encendido para ejecutarlos."],
  "Game Dev": ["Videojuegos", "Prepara una estructura inicial de videojuego en tu carpeta de trabajo."],
  Security: ["Revisión de seguridad", "Utiliza las comprobaciones disponibles para revisar tu espacio de trabajo."],
  File: ["Archivos y documentos", "Busca, lee y organiza archivos. Google Drive necesita una conexión autorizada."],
};
function actionLabel(tool: Tool) {
  return definitions[tool.id]?.label || toolLabels[tool.id] || tool.id;
}
type Field = {
  key: string;
  label: string;
  type?: "long" | "json" | "number" | "datetime" | "boolean";
  required?: boolean;
  placeholder?: string;
  options?: [string, string][];
  default?: string;
};
const field = (
  key: string,
  label: string,
  required = false,
  type?: Field["type"],
): Field => ({ key, label, required, type });
const path: Field = {
  key: "path",
  label: "Ruta relativa al workspace",
  placeholder: "carpeta/archivo",
  default: ".",
};
const filePath: Field = { ...path, required: true, default: "" };
const query = field("query", "Búsqueda", true);
const title = field("title", "Título", true);
const content = field("content", "Contenido", true, "long");
const description = field("description", "Descripción", false, "long");
const repository: Field = {
  key: "repository",
  label: "Repositorio GitHub",
  required: true,
  placeholder: "propietario/repositorio",
};
const mail = [
  field("to", "Destinatario", true),
  field("subject", "Asunto", true),
  field("body", "Mensaje", true, "long"),
];
const event = [
  title,
  field("start", "Inicio", true, "datetime"),
  field("end", "Fin", true, "datetime"),
  description,
];
const kindField: Field = { key: "kind", label: "Tipo de elemento", default: "tasks", options: [
  ["tasks", "Tareas"], ["projects", "Proyectos"], ["memory", "Recuerdos"], ["workflows", "Workflows"],
  ["calendar", "Eventos"], ["documents", "Documentos"], ["artifacts", "Informes"], ["drafts", "Borradores"],
] };
const definitions: Record<string, { label: string; fields: Field[] }> = {
  "daily.summary": { label: "Preparar mi resumen diario", fields: [] },
  "schedules.list": { label: "Consultar automatizaciones", fields: [] },
  "schedules.update": { label: "Modificar o pausar automatización", fields: [field("title", "Título exacto actual", true), field("changes", "Cambios (JSON)", true, "json")] },
  "schedules.delete": { label: "Eliminar automatización", fields: [field("title", "Título exacto", true)] },
  "items.list": { label: "Buscar elementos", fields: [kindField, { ...query, required: false }] },
  "items.create": { label: "Crear elemento", fields: [kindField, field("values", "Campos del elemento (JSON)", true, "json")] },
  "items.update": { label: "Modificar elemento", fields: [kindField, field("title", "Título exacto actual"), field("id", "ID si hay títulos repetidos"), field("changes", "Campos a cambiar (JSON)", true, "json")] },
  "items.delete": { label: "Eliminar elemento", fields: [kindField, field("title", "Título exacto"), field("id", "ID si hay títulos repetidos")] },
  "projects.summary": { label: "Resumen del proyecto", fields: [] },
  "decisions.create": {
    label: "Guardar una decisión",
    fields: [title, content],
  },
  "tasks.list": { label: "Consultar tareas", fields: [] },
  "tasks.create": {
    label: "Crear tarea",
    fields: [
      title,
      description,
      {
        key: "priority",
        label: "Prioridad",
        default: "MEDIUM",
        options: [
          ["LOW", "Baja"],
          ["MEDIUM", "Media"],
          ["HIGH", "Alta"],
        ],
      },
    ],
  },
  "projects.create": { label: "Crear proyecto", fields: [title, description] },
  "memory.search": { label: "Consultar memoria", fields: [query] },
  "documents.search": { label: "Buscar en documentos", fields: [query] },
  "report.create": { label: "Guardar informe", fields: [title, content] },
  "workspace.list": { label: "Explorar carpeta", fields: [path] },
  "workspace.read": { label: "Leer archivo", fields: [filePath] },
  "workspace.write": {
    label: "Guardar archivo",
    fields: [
      filePath,
      content,
      {
        key: "overwrite",
        label: "Reemplazar si ya existe",
        type: "boolean",
        default: "false",
      },
    ],
  },
  "code.scaffold": {
    label: "Crear proyecto de código",
    fields: [
      field("name", "Nombre de carpeta", true),
      {
        key: "kind",
        label: "Tipo",
        default: "app",
        options: [
          ["app", "Aplicación web"],
          ["game", "Videojuego"],
        ],
      },
      description,
    ],
  },
  "game.scaffold": {
    label: "Crear videojuego",
    fields: [field("name", "Nombre de carpeta", true), description],
  },
  "code.run": {
    label: "Ejecutar código o pruebas",
    fields: [
      filePath,
      {
        key: "runner",
        label: "Ejecutor",
        default: "python",
        options: [
          ["python", "Python"],
          ["unittest", "Python unittest"],
          ["pytest", "Pytest"],
          ["node", "Node.js"],
        ],
      },
      {
        key: "timeout_seconds",
        label: "Tiempo máximo en segundos",
        type: "number",
        default: "20",
      },
    ],
  },
  "git.status": { label: "Estado de Git", fields: [path] },
  "git.diff": {
    label: "Ver cambios de Git",
    fields: [
      path,
      {
        key: "staged",
        label: "Cambios preparados para commit",
        type: "boolean",
        default: "false",
      },
    ],
  },
  "git.branch": {
    label: "Crear rama local",
    fields: [path, field("name", "Nombre de rama", true)],
  },
  "security.audit": { label: "Revisar seguridad", fields: [path] },
  "devops.diagnose": { label: "Diagnosticar proyecto", fields: [path] },
  "study.create": {
    label: "Crear plan de estudio",
    fields: [
      title,
      content,
      { key: "days", label: "Número de días", type: "number", default: "7" },
    ],
  },
  "files.create": {
    label: "Crear documento",
    fields: [
      title,
      content,
      {
        key: "format",
        label: "Formato",
        default: "md",
        options: [
          ["md", "Markdown"],
          ["txt", "Texto"],
          ["html", "HTML"],
          ["csv", "CSV"],
        ],
      },
      { ...filePath, required: false },
    ],
  },
  "calendar.list": {
    label: "Consultar agenda local",
    fields: [
      field("from", "Desde", false, "datetime"),
      field("to", "Hasta", false, "datetime"),
    ],
  },
  "calendar.create": { label: "Añadir evento local", fields: event },
  "email.draft": { label: "Guardar borrador local de correo", fields: mail },
  "automation.create": {
    label: "Programar un objetivo",
    fields: [
      title,
      field("goal", "Objetivo", true, "long"),
      field("run_at", "Primera ejecución", true, "datetime"),
      {
        key: "interval_minutes",
        label: "Intervalo en minutos · 0 una vez",
        type: "number",
        default: "0",
      },
    ],
  },
  "google_calendar.list": {
    label: "Consultar Google Calendar",
    fields: [
      { ...query, required: false },
      field("start", "Desde", false, "datetime"),
      field("end", "Hasta", false, "datetime"),
    ],
  },
  "google_calendar.create": {
    label: "Crear evento en Google Calendar",
    fields: [...event, field("location", "Lugar")],
  },
  "email.list": {
    label: "Buscar correos",
    fields: [{ ...query, required: false, placeholder: "is:unread" }],
  },
  "email.read": {
    label: "Leer correo",
    fields: [field("id", "ID del mensaje", true)],
  },
  "email.send": { label: "Enviar correo", fields: mail },
  "github.inspect": { label: "Consultar repositorio", fields: [repository] },
  "github.tree": {
    label: "Explorar repositorio",
    fields: [repository, field("ref", "Rama o referencia · opcional")],
  },
  "github.read": {
    label: "Leer archivo de GitHub",
    fields: [
      repository,
      { ...filePath, label: "Ruta en el repositorio" },
      field("ref", "Rama o referencia · opcional"),
    ],
  },
  "github.diff": {
    label: "Comparar referencias de GitHub",
    fields: [
      repository,
      field("base", "Referencia base", true),
      field("head", "Referencia final", true),
    ],
  },
  "github.branch": {
    label: "Crear rama en GitHub",
    fields: [
      repository,
      field("branch", "Nombre de rama", true),
      field("from_ref", "Referencia de origen · opcional"),
    ],
  },
  "github.write": {
    label: "Guardar archivo en GitHub",
    fields: [
      repository,
      { ...filePath, label: "Ruta en el repositorio" },
      field("branch", "Rama", true),
      field("message", "Mensaje de commit", true),
      content,
      field("sha", "SHA del archivo existente · si se reemplaza"),
    ],
  },
  "n8n.trigger": {
    label: "Ejecutar webhook de n8n",
    fields: [
      {
        key: "payload",
        label: "Datos del webhook",
        type: "json",
        default: "{}",
      },
    ],
  },
  "web.search": { label: "Buscar en la web", fields: [query] },
  "drive.list": {
    label: "Buscar archivos en Drive",
    fields: [{ ...query, required: false }],
  },
  "drive.read": {
    label: "Leer archivo de Drive",
    fields: [field("id", "ID del archivo", true)],
  },
  "notion.search": {
    label: "Buscar páginas en Notion",
    fields: [{ ...query, required: false }],
  },
  "notion.read": {
    label: "Leer página de Notion",
    fields: [field("id", "ID de página", true)],
  },
  "notion.create": {
    label: "Crear página en Notion",
    fields: [
      field("parent_id", "ID de página contenedora", true),
      title,
      content,
    ],
  },
};
Object.entries(definitions).forEach(([id, definition]) => {
  toolLabels[id] = definition.label;
});
const workspacePrefixes = [
  "workspace.",
  "code.",
  "game.",
  "git.",
  "security.",
  "devops.",
  "files.",
];

export function ToolsPanel({
  projects,
  onRun,
  workspaceOnly = false,
}: {
  projects: RecordItem[];
  onRun: (id: string) => void;
  workspaceOnly?: boolean;
}) {
  const [tools, setTools] = useState<Tool[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Tool | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [project, setProject] = useState("none");
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [json, setJson] = useState("{}");
  const [formError, setFormError] = useState("");
  const load = useCallback(async () => {
    try {
      const [available, specialists] = await Promise.all([
        api<Tool[]>("/tools"),
        api<Agent[]>("/agents"),
      ]);
      setTools(available);
      setAgents(specialists);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void Promise.resolve().then(load);
  }, [load]);
  const visible = tools.filter(
    (tool) =>
      (!workspaceOnly ||
        workspacePrefixes.some((prefix) => tool.id.startsWith(prefix))) &&
      `${tool.agent} ${tool.id} ${actionLabel(tool)} ${guides[tool.agent]?.join(" ") || ""}`
        .toLowerCase()
        .includes(filter.toLowerCase()),
  );
  function open(tool: Tool) {
    setSelected(tool);
    setAdvanced(!definitions[tool.id]);
    setJson("{}");
    setFormError("");
    setValues(
      Object.fromEntries(
        (definitions[tool.id]?.fields || []).map((field) => [
          field.key,
          field.default || "",
        ]),
      ),
    );
  }
  function argumentsFromFields() {
    const args: Record<string, unknown> = {};
    for (const field of definitions[selected?.id || ""]?.fields || []) {
      const value = values[field.key];
      if (!value && field.required)
        throw new Error("Completa el campo: " + field.label);
      if (!value) continue;
      args[field.key] =
        field.type === "number"
          ? Number(value)
          : field.type === "boolean"
            ? value === "true"
            : field.type === "json"
              ? JSON.parse(value)
              : field.type === "datetime"
                ? new Date(value).toISOString()
                : value;
    }
    return args;
  }
  const groups = workspaceOnly
    ? [
        {
          name: "Herramientas del workspace",
          description: "",
          tools: visible.map((tool) => tool.id),
          status: "AVAILABLE",
        },
      ]
    : agents.filter((agent) =>
        visible.some((tool) => tool.agent === agent.name),
      ).sort((a, b) => {
        const order = ["Productivity", "Email", "Calendar", "File", "Study", "Research", "Automation", "Software Engineer", "GitHub", "Game Dev", "DevOps", "Security"];
        return order.indexOf(a.name) - order.indexOf(b.name);
      });
  return (
    <>
      <div className="section-header">
        <p className="section-note">
          {workspaceOnly
            ? "Explora y modifica archivos dentro de la carpeta de trabajo configurada. Usa rutas relativas; cada ejecución guarda sus resultados."
            : "Tus herramientas, organizadas por lo que quieres hacer. Elige una acción, completa sus datos y revisa el resultado. Funcionan sin tener que escribir una petición a la IA."}
        </p>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw size={15} />
          Actualizar
        </Button>
      </div>
      {!workspaceOnly && <section className="panel agents-guide">
        <h2>¿Por dónde empiezo?</h2>
        <p className="muted">Estos agentes son grupos de herramientas: no trabajan solos en segundo plano. Tú eliges la acción. Las conexiones y las aprobaciones habituales siguen siendo necesarias.</p>
        <div className="suggestions">
          {[
            ["email.list", "Consultar mis correos"],
            ["google_calendar.list", "Ver mi agenda de Google"],
            ["tasks.create", "Añadir una tarea"],
            ["drive.list", "Buscar en mi Drive"],
          ].map(([id, label]) => {
            const tool = tools.find(t => t.id === id);
            return tool && <button key={id} onClick={() => open(tool)}>{label}<Play size={14} /></button>;
          })}
        </div>
        <p className="muted">1. Elige una acción · 2. Completa el formulario · 3. Prepara la ejecución y aprueba si se solicita.</p>
      </section>}
      <div className="list-toolbar">
        <div className="search-field">
          <Search size={17} />
          <Input
            aria-label="Buscar herramientas"
            placeholder={workspaceOnly ? "Buscar herramienta…" : "Buscar agente o herramienta…"}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status" className="muted">
          Cargando herramientas…
        </p>
      ) : !visible.length ? (
        <Blank title="No hay herramientas para esta búsqueda">
          Prueba otra palabra o actualiza la lista.
        </Blank>
      ) : (
        <div className={workspaceOnly ? "tool-workspace" : "cards agent-cards"}>
          {groups.map((agent) => (
            <section className="panel agent-card" key={agent.name}>
              <div className="row between">
                <span className="agent-mark">
                  {workspaceOnly ? <FolderCode size={21} /> : <Bot size={21} />}
                </span>
                <Badge value={agent.status} />
              </div>
              <h2>{workspaceOnly ? agent.name : guides[agent.name]?.[0] || agent.name}</h2>
              {agent.description && (
                <p className="muted">{workspaceOnly ? agent.description : guides[agent.name]?.[1] || agent.description}</p>
              )}
              <div className="tool-list">
                {visible
                  .filter((tool) => workspaceOnly || tool.agent === agent.name)
                  .map((tool) => (
                    <button
                      className="tool-row"
                      key={tool.id}
                      onClick={() => open(tool)}
                    >
                      <span>
                        <strong>{workspaceOnly ? toolLabels[tool.id] || tool.id : actionLabel(tool)}</strong>
                        <small>{workspaceOnly ? tool.id : tool.risk === "SAFE" ? "Consultar · sin modificar datos" : ["HIGH", "CRITICAL"].includes(tool.risk) ? "Requiere tu aprobación" : "Crea o modifica datos"}</small>
                      </span>
                      <Play size={14} />
                    </button>
                  ))}
              </div>
            </section>
          ))}
        </div>
      )}
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open && !busy) setSelected(null);
        }}
      >
        <DialogContent className="editor-dialog tool-dialog">
          <DialogHeader>
            <DialogTitle>
              {selected && (workspaceOnly ? toolLabels[selected.id] || selected.id : actionLabel(selected))}
            </DialogTitle>
            <DialogDescription>
              Revisa los datos y prepara la ejecución. Los cambios que requieren
              autorización se detienen en el panel de aprobaciones.
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <form
              className="form-stack"
              onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setFormError("");
                try {
                  const args = advanced
                    ? JSON.parse(json)
                    : argumentsFromFields();
                  if (!args || typeof args !== "object" || Array.isArray(args))
                    throw new Error("Los parámetros deben ser un objeto JSON.");
                  const run = await api<Run>("/tool-runs", "POST", {
                    tool: selected.id,
                    arguments: args,
                    project_id: project === "none" ? null : project,
                  });
                  setSelected(null);
                  onRun(run.id);
                  toast.success("Ejecución preparada.");
                } catch (e) {
                  setFormError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <div className="row between">
                <Badge value={selected.risk} />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (!advanced) {
                      try {
                        setJson(JSON.stringify(argumentsFromFields(), null, 2));
                      } catch {
                        setJson("{}");
                      }
                    }
                    setAdvanced(!advanced);
                  }}
                >
                  {advanced ? "Formulario" : "Parámetros JSON"}
                </Button>
              </div>
              {selected.id === "code.run" && (
                <p className="notice">
                  El código se ejecuta con los permisos de tu usuario de
                  Windows. Puede acceder a archivos y red fuera del workspace.
                  Ejecuta únicamente código que hayas revisado.
                </p>
              )}
              {selected.id === "email.send" && (
                <p className="notice">
                  Esta acción envía un correo real al destinatario indicado.
                  Podrás revisar el envío antes de aprobarlo.
                </p>
              )}
              {advanced ? (
                <label>
                  Parámetros JSON
                  <Textarea
                    className="code-input"
                    rows={12}
                    value={json}
                    onChange={(e) => setJson(e.target.value)}
                  />
                </label>
              ) : (
                (definitions[selected.id]?.fields || []).map((field) => (
                  <label key={field.key}>
                    {field.label}
                    {field.options ? (
                      <Choice
                        label={field.label}
                        value={values[field.key] || field.options[0][0]}
                        onChange={(value) =>
                          setValues({ ...values, [field.key]: value })
                        }
                        options={field.options}
                      />
                    ) : field.type === "boolean" ? (
                      <Choice
                        label={field.label}
                        value={values[field.key] || "false"}
                        onChange={(value) =>
                          setValues({ ...values, [field.key]: value })
                        }
                        options={[
                          ["false", "No"],
                          ["true", "Sí"],
                        ]}
                      />
                    ) : field.type === "long" || field.type === "json" ? (
                      <Textarea
                        required={field.required}
                        rows={field.type === "json" ? 6 : 4}
                        className={field.type === "json" ? "code-input" : ""}
                        maxLength={100000}
                        value={values[field.key] || ""}
                        onChange={(e) =>
                          setValues({ ...values, [field.key]: e.target.value })
                        }
                      />
                    ) : (
                      <Input
                        required={field.required}
                        type={
                          field.type === "number"
                            ? "number"
                            : field.type === "datetime"
                              ? "datetime-local"
                              : "text"
                        }
                        min={field.type === "number" ? 0 : undefined}
                        placeholder={field.placeholder}
                        value={values[field.key] || ""}
                        onChange={(e) =>
                          setValues({ ...values, [field.key]: e.target.value })
                        }
                      />
                    )}
                  </label>
                ))
              )}
              <label>
                Contexto del proyecto
                <Choice
                  label="Proyecto de la ejecución"
                  value={project}
                  onChange={setProject}
                  options={[
                    ["none", "Sin proyecto"],
                    ...projects.map((p) => [p.id, p.title] as [string, string]),
                  ]}
                />
              </label>
              {formError && (
                <p className="error" role="alert">
                  {formError}
                </p>
              )}
              <Button disabled={busy}>
                <Play size={16} />
                {busy ? "Preparando…" : "Preparar ejecución"}
              </Button>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
