import { useEffect, useRef, useState } from "react";
import { Download, KeyRound, ShieldCheck, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "./api";
import { Badge, Choice } from "./common";
import { toast } from "sonner";

type Provider = {
  base_url: string;
  model: string;
  embed_model?: string;
  configured: boolean;
  credential_error?: string;
  key_present: boolean;
  monthly_budget_usd: number;
  input_cost_per_million: number;
  output_cost_per_million: number;
  usage?: { estimated_cost_usd?: number; total_tokens?: number };
  estimated_cost_usd?: number;
  spent_usd?: number;
  budget_usage?: { estimated_cost_usd?: number; spent_usd?: number };
};
export function ProviderSettings({ refresh }: { refresh: () => void }) {
  const [provider, setProvider] = useState<Provider | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [local, setLocal] = useState<{ available: boolean; models: { name: string; size: number }[]; message: string } | null>(null);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    let live = true;
    api<Provider>("/provider")
      .then((data) => {
        if (live) setProvider(data);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, []);
  if (!provider)
    return (
      <section className="panel settings-form">
        <h2>Proveedor de inteligencia artificial</h2>
        <p
          role={error ? "alert" : "status"}
          className={error ? "error" : "muted"}
        >
          {error || "Cargando configuración…"}
        </p>
        {error && (
          <Button
            variant="outline"
            onClick={async () => {
              try {
                setProvider(await api<Provider>("/provider"));
                setError("");
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Reintentar
          </Button>
        )}
      </section>
    );
  const cost =
    provider.estimated_cost_usd ??
    provider.spent_usd ??
    provider.usage?.estimated_cost_usd ??
    provider.budget_usage?.estimated_cost_usd ??
    provider.budget_usage?.spent_usd ??
    0;
  return (
    <form
      className="panel settings-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
          await api("/provider", "PUT", {
            base_url: provider.base_url,
            model: provider.model,
            embed_model: provider.embed_model || "",
            monthly_budget_usd: Number(provider.monthly_budget_usd),
            input_cost_per_million: Number(provider.input_cost_per_million),
            output_cost_per_million: Number(provider.output_cost_per_million),
            ...(key.trim() ? { api_key: key.trim() } : {}),
          });
          setKey("");
          setProvider(await api<Provider>("/provider"));
          refresh();
          toast.success(
            "Proveedor guardado. Los siguientes objetivos usarán esta configuración.",
          );
        } catch (error) {
          setError((error as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="row between">
        <div className="row">
          <KeyRound size={20} />
          <h2>Inteligencia artificial</h2>
        </div>
        <Badge value={provider.configured ? "Configurado" : "Sin configurar"} />
      </div>
      <p className="muted">
        Usa Ollama en tu ordenador para conversar sin pagar por mensajes.
        Los proveedores externos son opcionales y pueden cobrar por uso.
      </p>
      {provider.credential_error && <p role="alert" className="error">{provider.credential_error}</p>}
      <div className="notice form-stack">
        <strong>Groq · GPT-OSS 120B con cuenta Free</strong>
        <p>Crea tu clave en una cuenta Free de Groq, sin activar facturación. El programa no puede comprobar el plan de tu cuenta: poner las tarifas a cero aquí no impide cargos si activas un plan de pago en Groq.</p>
        <p>Las consultas y el contexto enviado se procesan fuera de tu ordenador. Si alcanzas la cuota, podrás volver a Ollama con el botón de detección local.</p>
        <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer">Crear mi clave en Groq</a>
        <Button type="button" variant="outline" disabled={busy} onClick={() => {
          setProvider({ ...provider, base_url: "https://api.groq.com/openai/v1", model: "openai/gpt-oss-120b", embed_model: "", monthly_budget_usd: 0, input_cost_per_million: 0, output_cost_per_million: 0 });
          setKey("");
          setError("");
        }}>Preparar Groq Free</Button>
        <p>Pulsa Preparar, pega tu clave en el campo Clave API y guarda el proveedor. Ollama seguirá instalado.</p>
      </div>
      <Button type="button" variant="outline" disabled={checking || busy} onClick={async () => {
        setChecking(true);
        setError("");
        try { setLocal(await api("/provider/local-status")); }
        catch (e) { setError((e as Error).message); }
        finally { setChecking(false); }
      }}>{checking ? "Comprobando Ollama…" : "Detectar IA local gratuita"}</Button>
      {local && <div className="form-stack">
        <p role="status" className="muted">{local.message}</p>
        {local.models.length > 0 && <label>Usar un modelo descargado
          <Choice label="Modelo local descargado" value={local.models.some(m => m.name === provider.model) ? provider.model : "__select__"}
            options={[["__select__", "Selecciona un modelo"], ...local.models.map(m => [m.name, `${m.name} · ${(m.size / 1e9).toFixed(1)} GB`] as [string, string])]}
            onChange={(model) => {
              if (model === "__select__") return;
              setProvider({ ...provider, base_url: "http://127.0.0.1:11434/v1", model, embed_model: "", monthly_budget_usd: 0, input_cost_per_million: 0, output_cost_per_million: 0 });
              setKey("ollama");
            }} />
        </label>}
        {local.models.length > 0 ? <p className="muted">Selecciona el modelo y pulsa Guardar proveedor. Los modelos pequeños suelen responder más rápido.</p>
          : <p className="muted">Instala Ollama desde <a href="https://ollama.com/download/windows" target="_blank" rel="noreferrer">su página oficial</a>. Después descarga un modelo con <code>ollama pull llama3.2:1b</code> y repite la comprobación.</p>}
      </div>}
      <label>
        URL del proveedor
        <Input
          type="url"
          required
          placeholder="https://api.openai.com/v1"
          value={provider.base_url}
          onChange={(e) =>
            setProvider({ ...provider, base_url: e.target.value })
          }
        />
      </label>
      <div className="two-fields">
        <label>
          Modelo de conversación
          <Input
            required
            placeholder="Nombre exacto del modelo"
            value={provider.model}
            onChange={(e) =>
              setProvider({ ...provider, model: e.target.value })
            }
          />
        </label>
        <label>
          Modelo de embeddings · opcional
          <Input
            placeholder="Para búsqueda semántica"
            value={provider.embed_model || ""}
            onChange={(e) =>
              setProvider({ ...provider, embed_model: e.target.value })
            }
          />
        </label>
      </div>
      <label>
        {provider.key_present ? "Reemplazar clave API · opcional" : "Clave API"}
        <Input
          type="password"
          autoComplete="new-password"
          spellCheck={false}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={
            provider.key_present
              ? "Deja vacío para conservar la clave"
              : "Tu clave del proveedor"
          }
        />
      </label>
      <details className="settings-details">
        <summary>Presupuesto y estimación de costes</summary>
        <div className="form-stack">
          <p className="muted">
            Introduce las tarifas de tu proveedor. La estimación cubre el uso de
            conversación registrado por PABLO OS; no sustituye su factura.
          </p>
          <label>
            Límite mensual en USD · 0 sin límite
            <Input
              type="number"
              min="0"
              step="0.01"
              value={provider.monthly_budget_usd}
              onChange={(e) =>
                setProvider({
                  ...provider,
                  monthly_budget_usd: Number(e.target.value),
                })
              }
            />
          </label>
          <div className="two-fields">
            <label>
              USD por millón de tokens de entrada
              <Input
                type="number"
                min="0"
                step="0.001"
                value={provider.input_cost_per_million}
                onChange={(e) =>
                  setProvider({
                    ...provider,
                    input_cost_per_million: Number(e.target.value),
                  })
                }
              />
            </label>
            <label>
              USD por millón de tokens de salida
              <Input
                type="number"
                min="0"
                step="0.001"
                value={provider.output_cost_per_million}
                onChange={(e) =>
                  setProvider({
                    ...provider,
                    output_cost_per_million: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
        </div>
      </details>
      <div className="budget-meter">
        <div className="row between">
          <span>Estimación del mes</span>
          <strong>
            {cost.toLocaleString("es", {
              style: "currency",
              currency: "USD",
              maximumFractionDigits: 4,
            })}
            {provider.monthly_budget_usd > 0
              ? ` / ${provider.monthly_budget_usd} USD`
              : ""}
          </strong>
        </div>
        {provider.monthly_budget_usd > 0 && (
          <Progress
            value={Math.min(100, (cost / provider.monthly_budget_usd) * 100)}
          />
        )}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <Button disabled={busy}>
        {busy ? "Guardando…" : "Guardar proveedor"}
      </Button>
    </form>
  );
}

export function PrivacySettings({
  refresh,
  onDeleted,
}: {
  refresh: () => void;
  onDeleted: () => void;
}) {
  const [retention, setRetention] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [backup, setBackup] = useState<{ name: string; data: unknown } | null>(
    null,
  );
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => {
    let live = true;
    api<{ retention_days: number }>("/privacy")
      .then((data) => {
        if (live) setRetention(String(data.retention_days));
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, []);
  return (
    <section className="panel settings-form">
      <div className="row">
        <ShieldCheck size={20} />
        <h2>Privacidad y copias de seguridad</h2>
      </div>
      <p className="muted">
        Exporta tus datos antes de importarlos o eliminar tu cuenta. La copia
        contiene información personal: guárdala en un lugar privado.
      </p>
      <div className="row wrap">
        <a className="download-link row" href="/api/v1/export" download>
          <Download size={16} />
          Exportar mis datos
        </a>
        <Button
          type="button"
          variant="outline"
          onClick={() => file.current?.click()}
          disabled={busy}
        >
          <Upload size={16} />
          Importar copia
        </Button>
      </div>
      <input
        ref={file}
        type="file"
        hidden
        accept=".json,application/json"
        onChange={async (e) => {
          const selected = e.target.files?.[0];
          if (!selected) return;
          try {
            if (selected.size > 50 * 1024 * 1024)
              throw new Error("La copia supera 50 MB.");
            const data: unknown = JSON.parse(await selected.text());
            if (!data || typeof data !== "object" || Array.isArray(data))
              throw new Error("Selecciona una exportación JSON de PABLO OS.");
            setBackup({ name: selected.name, data });
            setError("");
          } catch (error) {
            setError((error as Error).message);
          } finally {
            if (file.current) file.current.value = "";
          }
        }}
      />
      {retention !== null && (
        <form
          className="form-stack"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await api("/privacy", "PUT", {
                retention_days: Number(retention),
              });
              toast.success("Política de conservación guardada.");
            } catch (error) {
              setError((error as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Conservar mensajes, actividad y ejecuciones terminadas
            <Choice
              label="Conservación de historial"
              value={retention}
              onChange={setRetention}
              options={[
                ["0", "Sin eliminación automática"],
                ["30", "30 días"],
                ["90", "90 días"],
                ["365", "Un año"],
                ...(!["0", "30", "90", "365"].includes(retention)
                  ? [[retention, `${retention} días`] as [string, string]]
                  : []),
              ]}
            />
          </label>
          <p className="muted">
            La limpieza conserva tus proyectos, tareas, recuerdos y documentos.
          </p>
          <Button variant="outline" disabled={busy}>
            Guardar conservación
          </Button>
        </form>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="danger-zone">
        <h3>Eliminar mi cuenta</h3>
        <p className="muted">
          Borra los datos del espacio, sus documentos y las conexiones
          guardadas. Es irreversible.
        </p>
        <Button
          type="button"
          variant="destructive"
          onClick={() => {
            setDeleting(true);
            setError("");
          }}
        >
          Eliminar mi cuenta
        </Button>
      </div>
      <Dialog
        open={!!backup}
        onOpenChange={(open) => {
          if (!open && !busy) setBackup(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Importar copia de seguridad</DialogTitle>
            <DialogDescription>
              Archivo: {backup?.name}. Se incorporarán los datos compatibles de
              esta copia al espacio actual. Revisa que sea una copia tuya antes
              de continuar.
            </DialogDescription>
          </DialogHeader>
          <Button
            disabled={busy}
            onClick={async () => {
              if (!backup) return;
              setBusy(true);
              try {
                const result = await api<{ imported?: number }>(
                  "/import",
                  "POST",
                  backup.data,
                );
                setBackup(null);
                refresh();
                toast.success(
                  typeof result.imported === "number"
                    ? `${result.imported} elementos importados.`
                    : "Copia importada.",
                );
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Importando…" : "Importar esta copia"}
          </Button>
        </DialogContent>
      </Dialog>
      <Dialog
        open={deleting}
        onOpenChange={(open) => {
          if (!busy) {
            setDeleting(open);
            if (!open) {
              setPassword("");
              setConfirmation("");
            }
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Eliminar la cuenta y sus datos</DialogTitle>
            <DialogDescription>
              Introduce tu contraseña y escribe ELIMINAR MI CUENTA para
              confirmar. Esta acción no se puede deshacer.
            </DialogDescription>
          </DialogHeader>
          <form
            className="form-stack"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                await api("/account", "DELETE", { password, confirmation });
                setPassword("");
                setConfirmation("");
                setDeleting(false);
                onDeleted();
                toast.success("Cuenta y datos eliminados.");
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Contraseña
              <Input
                required
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label>
              Confirmación
              <Input
                required
                autoComplete="off"
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
              />
            </label>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <Button
              variant="destructive"
              disabled={
                busy || confirmation !== "ELIMINAR MI CUENTA" || !password
              }
            >
              {busy ? "Eliminando…" : "Eliminar definitivamente"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
