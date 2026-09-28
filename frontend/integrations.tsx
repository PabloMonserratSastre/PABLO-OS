import { useCallback, useEffect, useState } from "react";
import {
  ArrowUpRight,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  Cloud,
  ExternalLink,
  GitBranch,
  Globe2,
  Link2,
  Mail,
  RefreshCw,
  Sparkles,
  Unplug,
  Workflow,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Integration, api } from "./api";
import { Badge, Blank } from "./common";
import { toast } from "sonner";

type Field = {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
  optional?: boolean;
};
const configFields: Record<string, Field[]> = {
  github: [{ key: "token", label: "Token de acceso personal", secret: true }],
  google: [
    { key: "client_id", label: "ID de cliente OAuth" },
    { key: "client_secret", label: "Secreto de cliente OAuth", secret: true },
    {
      key: "redirect_uri",
      label: "URI de redirección",
      placeholder: "Deja vacío para usar la dirección local",
      optional: true,
    },
  ],
  n8n: [
    {
      key: "webhook_url",
      label: "URL del webhook",
      placeholder: "https://tu-instancia/webhook/...",
    },
    {
      key: "token",
      label: "Token del webhook · opcional",
      secret: true,
      optional: true,
    },
  ],
  notion: [{ key: "token", label: "Token de integración", secret: true }],
  search: [{ key: "api_key", label: "Clave de Brave Search", secret: true }],
};
const guidance: Record<string, string> = {
  github:
    "Tu token debe tener acceso a los repositorios que quieras consultar. Los repositorios públicos pueden consultarse sin token.",
  google:
    "Configura un cliente OAuth de aplicación web en Google Cloud y añade la URI de redirección de PABLO OS. Después, autoriza los servicios que quieras usar.",
  n8n: "Conecta un webhook activo de tu instancia. Su ejecución se revisa en el panel de aprobaciones.",
  notion:
    "Crea una integración en Notion y comparte con ella las páginas que quieres consultar.",
  search:
    "Usa una clave de Brave Search para buscar información actual con enlaces a sus fuentes.",
};
const providerDetails = {
  google: {
    icon: Cloud,
    color: "sky",
    capabilities: ["Consultar y crear eventos", "Buscar, leer y enviar correo", "Encontrar y leer archivos"],
  },
  github: {
    icon: GitBranch,
    color: "ink",
    capabilities: ["Explorar repositorios", "Comparar código", "Preparar ramas y cambios"],
  },
  notion: {
    icon: BookOpen,
    color: "violet",
    capabilities: ["Buscar conocimiento", "Leer páginas", "Crear documentación"],
  },
  search: {
    icon: Globe2,
    color: "amber",
    capabilities: ["Consultar Wikipedia sin clave", "Buscar en toda la web con Brave", "Mostrar enlaces a las fuentes"],
  },
  n8n: {
    icon: Workflow,
    color: "coral",
    capabilities: ["Activar automatizaciones", "Conectar cientos de aplicaciones", "Enviar datos revisados"],
  },
} as const;

const recipes = [
  {
    title: "Mi mañana en 30 segundos",
    description: "Correos recientes, agenda de hoy y tres prioridades claras.",
    provider: "google",
    icon: Sparkles,
    prompt: "Consulta mis 10 últimos correos recibidos en Gmail y los eventos de hoy en Google Calendar. Dame un resumen muy breve, separa lo urgente de lo informativo y termina con mis tres prioridades. No envíes ni modifiques nada.",
  },
  {
    title: "Limpiar mi bandeja mental",
    description: "Clasifica lo importante sin tocar ni enviar ningún correo.",
    provider: "google",
    icon: Mail,
    prompt: "Busca en Gmail los correos recibidos y no leídos de los últimos 7 días. Clasifícalos en: requiere respuesta, importante sin respuesta y prescindible. Sé conciso y no envíes ni modifiques nada.",
  },
  {
    title: "Preparar el día de mañana",
    description: "Revisa las citas de mañana y detecta choques o huecos.",
    provider: "google",
    icon: CalendarDays,
    prompt: "Consulta en Google Calendar todos mis eventos de mañana. Ordénalos por hora, avísame si se solapan y dime qué huecos libres tengo. No crees ni modifiques eventos.",
  },
  {
    title: "Encontrar un documento",
    description: "Busca en Drive por significado y resume el archivo correcto.",
    provider: "google",
    icon: Cloud,
    input: { label: "¿Qué documento buscas?", placeholder: "Ej.: presupuesto de vacaciones o apuntes de redes" },
    prompt: "Busca en Google Drive un documento relacionado con: {{input}}. Muéstrame los archivos que coincidan y resume el más relevante si puedes leerlo. No modifiques nada.",
  },
  {
    title: "Revisión semanal",
    description: "Une agenda y correo para cerrar la semana con perspectiva.",
    provider: "google",
    icon: CheckCircle2,
    prompt: "Prepara mi revisión semanal: consulta los eventos de los últimos 7 días en Google Calendar y mis correos relevantes de ese periodo. Muéstrame compromisos, asuntos pendientes y próximos pasos de forma breve. No guardes un informe, no envíes ni cambies nada.",
  },
  {
    title: "Entender un repositorio",
    description: "Explora un proyecto y explica su estructura sin cambiar código.",
    provider: "github",
    icon: GitBranch,
    input: { label: "Repositorio de GitHub", placeholder: "propietario/nombre o URL de GitHub" },
    prompt: "Analiza el repositorio de GitHub {{input}}. Consulta sus metadatos y README y explícame para qué sirve, cuál es su lenguaje principal y qué limitaciones tiene este análisis. No modifiques nada.",
  },
  {
    title: "Consultar mi conocimiento",
    description: "Encuentra información entre las páginas compartidas de Notion.",
    provider: "notion",
    icon: BookOpen,
    input: { label: "¿Qué quieres encontrar en Notion?", placeholder: "Ej.: plan del proyecto o notas de la reunión" },
    prompt: "Busca en las páginas compartidas de Notion información relacionada con: {{input}}. Muéstrame las páginas encontradas. No crees ni modifiques páginas.",
  },
  {
    title: "Consultar información",
    description: "Busca fuentes públicas y muestra resultados con enlaces.",
    provider: "search",
    icon: Globe2,
    input: { label: "Tema que quieres consultar", placeholder: "Ej.: qué es n8n o historia de la inteligencia artificial" },
    prompt: "Busca información pública sobre: {{input}}. Devuélveme los resultados más relevantes con una breve descripción y sus enlaces. No guardes ningún informe.",
  },
] as const;
function providerId(item: Integration) {
  return (
    item.id ||
    {
      GitHub: "github",
      Google: "google",
      Gmail: "google",
      "Google Calendar": "google",
      "Google Drive": "google",
      Notion: "notion",
      n8n: "n8n",
      "Web Search": "search",
      "Búsqueda web": "search",
    }[item.name] ||
    item.name.toLowerCase()
  );
}
export function IntegrationsPanel({ onPrompt }: { onPrompt: (prompt: string) => void }) {
  const [items, setItems] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Integration | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [services, setServices] = useState(["calendar", "gmail", "drive"]);
  const [busy, setBusy] = useState(false);
  const [disconnect, setDisconnect] = useState(false);
  const [selectedRecipe, setSelectedRecipe] = useState<(typeof recipes)[number] | null>(null);
  const [recipeValue, setRecipeValue] = useState("");
  const load = useCallback(async () => {
    try {
      setItems(await api<Integration[]>("/integrations"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void Promise.resolve().then(load);
    const query = new URLSearchParams(window.location.search);
    if (query.get("integration") === "google") {
      if (query.get("connected") === "1") toast.success("Google conectado.");
      else if (query.get("error"))
        toast.error(
          "No se pudo completar la conexión con Google. Revisa sus credenciales.",
        );
      query.delete("integration");
      query.delete("connected");
      query.delete("error");
      window.history.replaceState(
        null,
        "",
        window.location.pathname +
          (query.size ? "?" + query.toString() : "") +
          window.location.hash,
      );
    }
  }, [load]);
  const id = selected ? providerId(selected) : "";
  const privateConnections = items.filter((item) =>
    ["CONNECTED", "CONFIGURED"].includes(item.status),
  ).length;
  const isUsable = (provider: string) => {
    const item = items.find((candidate) => providerId(candidate) === provider);
    return !!item && (
      ["CONNECTED", "CONFIGURED"].includes(item.status) ||
      (["github", "search"].includes(provider) && item.status === "PUBLIC_READ")
    );
  };
  function manage(item: Integration) {
    setSelected(item);
    setValues(
      Object.fromEntries(
        Object.entries(item.config || {}).map(([key, value]) => [key, String(value)]),
      ),
    );
    setDisconnect(false);
  }
  return (
    <>
      <section className="integration-hero">
        <div>
          <div className="integration-eyebrow"><Zap size={15} /> ECOSISTEMA PABLO OS</div>
          <h2>Tus herramientas, una sola conversación.</h2>
          <p>Convierte correo, calendario, archivos y aplicaciones en acciones útiles. PABLO OS consulta primero y siempre pide aprobación antes de realizar cambios externos.</p>
        </div>
        <div className="integration-stats">
          <div><strong>{privateConnections}</strong><span>conexiones privadas</span></div>
          <div><strong>18</strong><span>acciones disponibles</span></div>
        </div>
      </section>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status" className="muted">
          Cargando conexiones…
        </p>
      ) : !items.length ? (
        <Blank title="Sin conexiones disponibles">
          Reintenta la conexión con el servidor.
        </Blank>
      ) : (
        <>
          <div className="integration-section-heading">
            <div><span>EMPIEZA AQUÍ</span><h2>Usos listos para ti</h2><p>Elige una receta. PABLO OS abrirá Command, consultará las fuentes necesarias y te mostrará el resultado.</p></div>
          </div>
          <div className="recipe-grid">
            {recipes.map((recipe) => {
              const Icon = recipe.icon;
              const available = isUsable(recipe.provider);
              const provider = items.find((item) => providerId(item) === recipe.provider);
              return (
                <article className={`recipe-card ${available ? "available" : "locked"}`} key={recipe.title}>
                  <div className="recipe-top"><span><Icon size={19} /></span>{available && <em><CheckCircle2 size={13} /> Disponible</em>}</div>
                  <h3>{recipe.title}</h3>
                  <p>{recipe.description}</p>
                  <Button
                    variant={available ? "default" : "outline"}
                    onClick={() => {
                      if (!available) return provider && manage(provider);
                      if ("input" in recipe) {
                        setSelectedRecipe(recipe);
                        setRecipeValue("");
                      } else onPrompt(recipe.prompt);
                    }}
                  >
                    {available ? "Usar ahora" : "Conectar para usar"}<ArrowUpRight size={15} />
                  </Button>
                </article>
              );
            })}
          </div>
          <div className="integration-section-heading connections-heading">
            <div><span>TUS CONEXIONES</span><h2>Servicios y capacidades</h2><p>Consulta exactamente qué aporta cada servicio y gestiona sus credenciales privadas.</p></div>
            <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw size={15} />Actualizar estados</Button>
          </div>
          <div className="integration-grid">
            {items.map((item) => {
              const provider = providerId(item) as keyof typeof providerDetails;
              const detail = providerDetails[provider];
              const Icon = detail?.icon || Link2;
              return (
                <article className="panel integration-card" key={item.id || item.name}>
                  <div className="row between">
                    <span className={`integration-mark integration-${detail?.color || "sky"}`}><Icon size={21} /></span>
                    <Badge value={item.status} />
                  </div>
                  <h2>{item.name}</h2>
                  <p>{item.detail}</p>
                  <ul>{(detail?.capabilities || []).map((capability) => <li key={capability}><CheckCircle2 size={14} />{capability}</li>)}</ul>
                  {provider === "google" && item.scopes && item.scopes.length > 0 && <small className="verified-note"><CheckCircle2 size={13} /> Permisos de Google verificados</small>}
                  {configFields[provider] && <Button variant="outline" onClick={() => manage(item)}>{item.configured ? "Gestionar" : "Configurar"}<ArrowUpRight size={15} /></Button>}
                </article>
              );
            })}
          </div>
        </>
      )}
      <Dialog
        open={!!selectedRecipe}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedRecipe(null);
            setRecipeValue("");
          }
        }}
      >
        <DialogContent className="editor-dialog">
          <DialogHeader>
            <DialogTitle>{selectedRecipe?.title}</DialogTitle>
            <DialogDescription>{selectedRecipe?.description}</DialogDescription>
          </DialogHeader>
          {selectedRecipe && "input" in selectedRecipe && (
            <form
              className="form-stack"
              onSubmit={(event) => {
                event.preventDefault();
                const value = recipeValue.trim();
                if (!value) return;
                onPrompt(selectedRecipe.prompt.replace("{{input}}", value));
                setSelectedRecipe(null);
                setRecipeValue("");
              }}
            >
              <label>
                {selectedRecipe.input.label}
                <Input
                  autoFocus
                  required
                  value={recipeValue}
                  placeholder={selectedRecipe.input.placeholder}
                  onChange={(event) => setRecipeValue(event.target.value)}
                />
              </label>
              <Button disabled={!recipeValue.trim()}>Continuar en Command</Button>
            </form>
          )}
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open && !busy) {
            setSelected(null);
            setValues({});
          }
        }}
      >
        <DialogContent className="editor-dialog">
          <DialogHeader>
            <DialogTitle>Conectar {selected?.name}</DialogTitle>
            <DialogDescription>
              {guidance[id]} Las claves guardadas nunca se devuelven al
              navegador.
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <form
              className="form-stack"
              onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                try {
                  const config: Record<string, string> = {};
                  const secrets: Record<string, string> = {};
                  for (const field of configFields[id] || []) {
                    const value = (values[field.key] || "").trim();
                    if (field.secret) {
                      if (value) secrets[field.key] = value;
                    } else if (value) config[field.key] = value;
                  }
                  await api("/integrations/" + id, "PUT", { config, secrets });
                  setValues(
                    Object.fromEntries(
                      Object.entries(values).filter(
                        ([key]) =>
                          !(configFields[id] || []).find((f) => f.key === key)
                            ?.secret,
                      ),
                    ),
                  );
                  await load();
                  setSelected({ ...selected, configured: true, config });
                  toast.success(
                    id === "google"
                      ? "Credenciales guardadas. Autoriza Google para completar la conexión."
                      : "Conexión guardada.",
                  );
                } catch (e) {
                  toast.error((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {(configFields[id] || []).map((field) => (
                <label key={field.key}>
                  {field.label}
                  <Input
                    type={field.secret ? "password" : "text"}
                    autoComplete={field.secret ? "new-password" : "off"}
                    spellCheck={false}
                    required={
                      !field.optional && !field.secret && !selected.configured
                    }
                    placeholder={
                      field.secret && selected.configured
                        ? "Deja vacío para conservar el secreto"
                        : field.placeholder
                    }
                    value={values[field.key] || ""}
                    onChange={(e) =>
                      setValues({ ...values, [field.key]: e.target.value })
                    }
                  />
                </label>
              ))}
              <Button disabled={busy}>
                {busy ? "Guardando…" : "Guardar conexión"}
              </Button>
              {id === "google" && (
                <div className="form-stack connection-authorize">
                  <h3>Servicios de Google</h3>
                  {[
                    ["calendar", "Calendar"],
                    ["gmail", "Gmail"],
                    ["drive", "Drive"],
                  ].map(([key, label]) => (
                    <label className="check-label" key={key}>
                      <Checkbox
                        checked={services.includes(key)}
                        onCheckedChange={(enabled) =>
                          setServices(
                            enabled
                              ? [...services, key]
                              : services.filter((s) => s !== key),
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy || !selected.configured || !services.length}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        const response = await api<{ url: string }>(
                          "/integrations/google/authorize",
                          "POST",
                          { services },
                        );
                        const url = new URL(response.url);
                        if (
                          url.protocol !== "https:" ||
                          url.hostname !== "accounts.google.com"
                        )
                          throw new Error(
                            "El servidor devolvió una dirección de autorización inesperada.",
                          );
                        window.location.assign(url.href);
                      } catch (e) {
                        toast.error((e as Error).message);
                        setBusy(false);
                      }
                    }}
                  >
                    <ExternalLink size={16} />
                    Autorizar en Google
                  </Button>
                </div>
              )}
              {selected.configured && (
                <div className="danger-zone">
                  {disconnect ? (
                    <>
                      <p>
                        Se borrarán las credenciales guardadas de esta conexión.
                      </p>
                      <div className="row wrap">
                        <Button
                          type="button"
                          variant="destructive"
                          disabled={busy}
                          onClick={async () => {
                            setBusy(true);
                            try {
                              await api("/integrations/" + id, "DELETE");
                              await load();
                              setSelected(null);
                              setValues({});
                              toast.success("Conexión eliminada.");
                            } catch (e) {
                              toast.error((e as Error).message);
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          Confirmar desconexión
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => setDisconnect(false)}
                        >
                          Cancelar
                        </Button>
                      </div>
                    </>
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setDisconnect(true)}
                    >
                      <Unplug size={16} />
                      Desconectar
                    </Button>
                  )}
                </div>
              )}
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
