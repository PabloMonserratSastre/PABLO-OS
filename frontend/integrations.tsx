import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Link2, Unplug, RefreshCw } from "lucide-react";
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
export function IntegrationsPanel() {
  const [items, setItems] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Integration | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [services, setServices] = useState(["calendar", "gmail", "drive"]);
  const [busy, setBusy] = useState(false);
  const [disconnect, setDisconnect] = useState(false);
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
  return (
    <>
      <div className="section-header">
        <p className="section-note">
          Conecta tus servicios para consultar información y ejecutar las
          acciones disponibles de sus agentes.
        </p>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw size={15} />
          Actualizar
        </Button>
      </div>
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
        <div className="cards">
          {items.map((item) => (
            <article className="panel integration" key={item.id || item.name}>
              <div className="row between">
                <span className="agent-mark">
                  <Link2 size={20} />
                </span>
                <Badge value={item.status} />
              </div>
              <h2>{item.name}</h2>
              <p>{item.detail}</p>
              {configFields[providerId(item)] && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setSelected(item);
                    setValues(
                      Object.fromEntries(
                        Object.entries(item.config || {}).map(
                          ([key, value]) => [key, String(value)],
                        ),
                      ),
                    );
                    setDisconnect(false);
                  }}
                >
                  {item.configured ? "Gestionar conexión" : "Configurar"}
                </Button>
              )}
            </article>
          ))}
        </div>
      )}
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
