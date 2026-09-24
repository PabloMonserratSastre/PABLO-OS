import { useCallback, useEffect, useState } from "react";
import { Clock3, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { api, RecordItem } from "./api";
import { Badge, Blank, Choice } from "./common";
import { toast } from "sonner";
type Schedule = {
  id: string;
  title: string;
  goal: string;
  mode: string;
  project_id: string | null;
  next_run: string;
  interval_minutes: number;
  enabled: boolean;
  last_run_id: string | null;
};
export function Automations({
  projects,
  onRun,
}: {
  projects: RecordItem[];
  onRun: (id: string) => void;
}) {
  const [rows, setRows] = useState<Schedule[]>([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [remove, setRemove] = useState<string | null>(null);
  const [worker, setWorker] = useState("");
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const mode = "CHAT";
  const [project, setProject] = useState("none");
  const [at, setAt] = useState("");
  const [interval, setRepeatInterval] = useState("0");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        api<Schedule[]>("/schedules"),
        api<{ worker: string }>("/runtime"),
      ]);
      setRows(s);
      setWorker(r.worker);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    let active = true;
    api<Schedule[]>("/schedules")
      .then((s) => {
        if (active) setRows(s);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    api<{ worker: string }>("/runtime")
      .then((s) => {
        if (active) setWorker(s.worker);
      })
      .catch(() => {});
    const timer = setInterval(() => void load(), 10000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [load]);
  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Automatizaciones</h2>
          <p className="muted">
            Se ejecutan mientras PABLO OS está encendido. Los cambios conservan
            sus reglas de aprobación.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>
          <Plus size={16} />
          Programar
        </Button>
      </div>
      {worker === "OFFLINE" && (
        <p className="notice">
          El ejecutor no responde. Reinicia PABLO OS antes de confiar en las
          próximas ejecuciones.
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!rows.length ? (
        <Blank title="Tu próximo paso, a su hora">
          Programa una revisión de tareas o un plan para más tarde.
        </Blank>
      ) : (
        <div className="record-list">
          {rows.map((row) => (
            <article className="panel record" key={row.id}>
              <Clock3 size={20} />
              <div className="record-main">
                <h2>{row.title}</h2>
                <p>{row.goal}</p>
                <div className="record-meta">
                  <time>{new Date(row.next_run).toLocaleString("es")}</time>
                  <span>
                    {row.interval_minutes
                      ? "Cada " + row.interval_minutes + " min"
                      : "Una vez"}
                  </span>
                  <Badge
                    value={row.enabled ? "Programada" : "Pausada / terminada"}
                  />
                </div>
              </div>
              <div className="record-actions">
                {row.last_run_id && (
                  <Button
                    variant="ghost"
                    onClick={() => onRun(row.last_run_id!)}
                  >
                    Ver resultado
                  </Button>
                )}
                <Switch
                  aria-label={"Activar " + row.title}
                  checked={row.enabled}
                  onCheckedChange={async (value) => {
                    try {
                      await api("/schedules/" + row.id, "PUT", {
                        enabled: value,
                      });
                      await load();
                    } catch (e) {
                      toast.error((e as Error).message);
                    }
                  }}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={"Eliminar " + row.title}
                  onClick={() => setRemove(row.id)}
                >
                  <Trash2 size={16} />
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Programar un objetivo</DialogTitle>
            <DialogDescription>
              La fecha usa la hora de este dispositivo. Los intervalos son
              duraciones exactas, incluso si cambia el horario de verano.
            </DialogDescription>
          </DialogHeader>
          <form
            className="form-stack"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                await api("/schedules", "POST", {
                  title,
                  goal,
                  mode,
                  project_id: project === "none" ? null : project,
                  run_at: new Date(at).toISOString(),
                  interval_minutes: Number(interval),
                });
                setOpen(false);
                setTitle("");
                setGoal("");
                await load();
                toast.success("Automatización programada.");
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Nombre
              <Input
                required
                maxLength={300}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label>
              Objetivo
              <Textarea
                required
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
              />
            </label>
            <label>
              Primera ejecución
              <Input
                required
                type="datetime-local"
                value={at}
                onChange={(e) => setAt(e.target.value)}
              />
            </label>
            <div className="two-fields">
              <label>
                Repetición
                <Choice
                  value={interval}
                  onChange={setRepeatInterval}
                  label="Repetición"
                  options={[
                    ["0", "Una vez"],
                    ["60", "Cada hora"],
                    ["1440", "Cada 24 horas"],
                    ["10080", "Cada 7 días"],
                  ]}
                />
              </label>
              <p className="muted">Describe lo que necesitas, como en el chat. Las acciones sensibles seguirán pidiendo tu aprobación.</p>
            </div>
            <label>
              Proyecto
              <Choice
                value={project}
                onChange={setProject}
                label="Proyecto programado"
                options={[
                  ["none", "Sin proyecto"],
                  ...projects.map((p) => [p.id, p.title] as [string, string]),
                ]}
              />
            </label>
            <Button disabled={busy}>
              {busy ? "Guardando…" : "Guardar programación"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
      <AlertDialog
        open={!!remove}
        onOpenChange={(v) => {
          if (!v) setRemove(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar esta programación?</AlertDialogTitle>
            <AlertDialogDescription>
              No volverá a dispararse. Las ejecuciones que ya estén en cola se
              conservan y puedes detenerlas desde su panel.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                try {
                  await api("/schedules/" + remove, "DELETE");
                  await load();
                } catch (e) {
                  toast.error((e as Error).message);
                }
                setRemove(null);
              }}
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
