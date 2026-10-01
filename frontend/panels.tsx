import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Activity, Profile, api } from "./api";
import { Badge, Blank, Choice } from "./common";
import { ProviderSettings, PrivacySettings } from "./settings";
import { IntegrationsPanel } from "./integrations";
export function SettingsPanel({
  profile,
  refresh,
  onDeleted,
}: {
  profile: Profile;
  refresh: () => void;
  onDeleted: () => void;
}) {
  const [form, setForm] = useState(profile);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="settings-grid">
      <form
        className="panel settings-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api("/settings", "PUT", form);
            setMessage("Cambios guardados.");
            refresh();
          } catch (e) {
            setMessage((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <h2>Tu espacio, tus reglas</h2>
        <label>
          Nombre
          <Input
            required
            maxLength={100}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </label>
        <label>
          Zona horaria
          <Input
            value={form.timezone}
            onChange={(e) => setForm({ ...form, timezone: e.target.value })}
          />
        </label>
        <label>
          Cómo quieres que te ayude
          <Choice
            label="Cómo quieres que te ayude"
            value={form.autonomy}
            onChange={(v) => setForm({ ...form, autonomy: v })}
            options={[
              ["MANUAL", "Revisar consultas y cambios"],
              ["ASSISTED", "Revisar solo los cambios"],
              ["AUTONOMOUS", "Guardar y editar directamente"],
            ]}
          />
        </label>
        <p className="muted">
          Las eliminaciones siempre necesitan tu confirmación. Puedes permitir que el asistente guarde y edite tus tareas directamente.
        </p>
        <Button disabled={busy}>
          {busy ? "Guardando…" : "Guardar ajustes"}
        </Button>
        <p role="status">{message}</p>
      </form>
      <ProviderSettings refresh={refresh} />
      <PrivacySettings refresh={refresh} onDeleted={onDeleted} />
    </div>
  );
}
export function RemotePanel({
  view,
  onPrompt,
}: {
  view: string;
  onPrompt: (prompt: string) => void;
}) {
  const [activity, setActivity] = useState<Activity[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    async function load() {
      try {
        if (view === "Actividad") {
          const rows = await api<Activity[]>("/activity");
          if (live) setActivity(rows);
        }
      } catch (e) {
        if (live) setError((e as Error).message);
      } finally {
        if (live) setLoading(false);
      }
    }
    void load();
    return () => {
      live = false;
    };
  }, [view]);
  if (error)
    return (
      <p role="alert" className="error">
        {error}
      </p>
    );
  if (view === "Integraciones") return <IntegrationsPanel onPrompt={onPrompt} />;
  if (loading)
    return (
      <p role="status" className="muted">
        Cargando actividad…
      </p>
    );
  return (
    <div className="panel timeline">
      {!activity.length && (
        <Blank title="Aún no hay actividad">
          Tus acciones verificadas aparecerán aquí.
        </Blank>
      )}
      {activity.map((a) => (
        <div className="activity-row" key={a.id}>
          <time>
            {new Date(a.created_at).toLocaleString("es", {
              day: "2-digit",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </time>
          <div>
            <strong>{a.action}</strong>
            <p className="muted">
              {Object.entries(a.detail)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ")}
            </p>
          </div>
          <Badge value={a.status} />
        </div>
      ))}
    </div>
  );
}
