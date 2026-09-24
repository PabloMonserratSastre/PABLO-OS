import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Trash2,
  CalendarDays,
} from "lucide-react";
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
import { api, RecordItem } from "./api";
import { Blank, Choice } from "./common";
import { toast } from "sonner";

type CalendarEvent = {
  id: string;
  title: string;
  start: string;
  end: string;
  description: string;
  project_id?: string | null;
  source?: "google";
  all_day?: boolean;
};
function dayKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function inputTime(value: string) {
  const date = new Date(value);
  return `${dayKey(date)}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
export function CalendarPanel({
  projects,
  tasks,
}: {
  projects: RecordItem[];
  tasks: RecordItem[];
}) {
  const [month, setMonth] = useState(
    () => new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  );
  const [selected, setSelected] = useState(() => dayKey(new Date()));
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [googleEvents, setGoogleEvents] = useState<CalendarEvent[]>([]);
  const [googleStatus, setGoogleStatus] = useState("");
  const [googleBusy, setGoogleBusy] = useState(false);
  const googleRequest = useRef(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState<CalendarEvent | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const load = useCallback(async () => {
    try {
      setEvents(await api<CalendarEvent[]>("/calendar"));
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
  const loadGoogle = useCallback(async () => {
    const request = ++googleRequest.current;
    setGoogleBusy(true);
    const from = new Date(month);
    from.setDate(from.getDate() - ((from.getDay() + 6) % 7));
    const until = new Date(from);
    until.setDate(until.getDate() + 42);
    try {
      const query = new URLSearchParams({ start: from.toISOString(), end: until.toISOString() });
      const result = await api<{ events: CalendarEvent[]; connected: boolean; truncated: boolean }>(
        "/integrations/google/calendar-events?" + query,
      );
      if (request !== googleRequest.current) return;
      setGoogleEvents(result.events);
      setGoogleStatus(!result.connected ? "Conecta Google Calendar desde Integraciones para ver sus eventos." :
        result.truncated ? "Google Calendar: hay más eventos de los que se pueden mostrar en este intervalo." :
        `Google Calendar · calendario principal · ${result.events.length} eventos en el intervalo visible.`);
    } catch (e) {
      if (request !== googleRequest.current) return;
      setGoogleEvents([]);
      setGoogleStatus("No se pudo cargar Google Calendar: " + (e as Error).message);
    } finally {
      if (request === googleRequest.current) setGoogleBusy(false);
    }
  }, [month]);
  useEffect(() => {
    let mounted = true;
    const requests = googleRequest;
    void Promise.resolve().then(() => {
      if (!mounted) return;
      setGoogleEvents([]);
      void loadGoogle();
    });
    const update = () => { if (document.visibilityState === "visible") void loadGoogle(); };
    const timer = window.setInterval(update, 60000);
    document.addEventListener("visibilitychange", update);
    window.addEventListener("online", update);
    return () => {
      mounted = false;
      ++requests.current;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", update);
      window.removeEventListener("online", update);
    };
  }, [loadGoogle]);
  const visibleEvents = [...events, ...googleEvents];
  const start = new Date(month.getFullYear(), month.getMonth(), 1);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  const days = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(date.getDate() + index);
    return date;
  });
  const onDay = (event: CalendarEvent, day: string) => {
    const from = new Date(day + "T00:00:00");
    const to = new Date(from);
    to.setDate(to.getDate() + 1);
    return new Date(event.start) < to && new Date(event.end) > from;
  };
  const dayEvents = visibleEvents
    .filter((event) => onDay(event, selected))
    .sort((a, b) => a.start.localeCompare(b.start));
  const dayTasks = tasks.filter(
    (task) =>
      task.due?.slice(0, 10) === selected &&
      !["DONE", "CANCELLED"].includes(task.status || ""),
  );
  function create() {
    setConfirmDelete(false);
    setForm({
      id: "",
      title: "",
      start: selected + "T09:00",
      end: selected + "T10:00",
      description: "",
      project_id: null,
    });
  }
  return (
    <>
      <div className="section-header calendar-toolbar">
        <div>
          <h2>Agenda personal</h2>
          <p className="muted">
            Eventos locales, Google Calendar y fechas de tus tareas · hora de este dispositivo.
          </p>
        </div>
        <Button onClick={create}>
          <Plus size={16} />
          Nuevo evento
        </Button>
      </div>
      <div className="notice" role="status">
        {googleBusy ? "Cargando Google Calendar…" : googleStatus}{" "}
        <Button variant="outline" size="sm" disabled={googleBusy} onClick={() => void loadGoogle()}>
          Actualizar Google Calendar
        </Button>
      </div>
      {error && (
        <div className="notice" role="alert">
          {error}{" "}
          <Button variant="outline" size="sm" onClick={() => void load()}>
            Reintentar
          </Button>
        </div>
      )}
      <div className="calendar-layout">
        <section
          className="panel calendar-panel"
          aria-label="Calendario mensual"
        >
          <div className="row between">
            <h2 className="calendar-month">
              {month.toLocaleDateString("es", {
                month: "long",
                year: "numeric",
              })}
            </h2>
            <div className="row">
              <Button
                variant="ghost"
                size="icon"
                aria-label="Mes anterior"
                onClick={() =>
                  setMonth(
                    new Date(month.getFullYear(), month.getMonth() - 1, 1),
                  )
                }
              >
                <ChevronLeft size={18} />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setMonth(
                    new Date(
                      new Date().getFullYear(),
                      new Date().getMonth(),
                      1,
                    ),
                  );
                  setSelected(dayKey(new Date()));
                }}
              >
                Hoy
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Mes siguiente"
                onClick={() =>
                  setMonth(
                    new Date(month.getFullYear(), month.getMonth() + 1, 1),
                  )
                }
              >
                <ChevronRight size={18} />
              </Button>
            </div>
          </div>
          <div className="calendar-grid">
            {["L", "M", "X", "J", "V", "S", "D"].map((day, index) => (
              <span className="weekday" key={index}>
                {day}
              </span>
            ))}
            {days.map((date) => {
              const key = dayKey(date);
              const count =
                visibleEvents.filter((event) => onDay(event, key)).length +
                tasks.filter(
                  (task) =>
                    task.due?.slice(0, 10) === key &&
                    !["DONE", "CANCELLED"].includes(task.status || ""),
                ).length;
              return (
                <button
                  key={key}
                  className={`calendar-day ${date.getMonth() !== month.getMonth() ? "outside" : ""} ${key === selected ? "selected" : ""} ${key === dayKey(new Date()) ? "today" : ""}`}
                  aria-pressed={key === selected}
                  aria-label={`${date.toLocaleDateString("es", { dateStyle: "full" })}, ${count} elementos`}
                  onClick={() => setSelected(key)}
                >
                  <span>{date.getDate()}</span>
                  {count > 0 && <span className="calendar-count">{count}</span>}
                </button>
              );
            })}
          </div>
        </section>
        <section className="panel agenda-day">
          <div className="row">
            <CalendarDays size={19} />
            <h2>
              {new Date(selected + "T12:00:00").toLocaleDateString("es", {
                weekday: "long",
                day: "numeric",
                month: "long",
              })}
            </h2>
          </div>
          {loading ? (
            <p role="status" className="muted">
              Cargando agenda…
            </p>
          ) : !dayEvents.length && !dayTasks.length ? (
            <Blank title="Tu día está libre">
              Reserva tiempo para lo importante.
              <Button variant="outline" onClick={create}>
                Añadir evento
              </Button>
            </Blank>
          ) : (
            <div className="agenda-list">
              {dayEvents.map((event) => (
                <button
                  className="agenda-event"
                  key={event.id}
                  onClick={() => {
                    if (event.source === "google") {
                      window.open("https://calendar.google.com/calendar/u/0/r", "_blank", "noopener,noreferrer");
                      return;
                    }
                    setConfirmDelete(false);
                    setForm({
                      ...event,
                      start: inputTime(event.start),
                      end: inputTime(event.end),
                    });
                  }}
                >
                  <time>
                    {event.all_day ? "Todo el día" : new Date(event.start).toLocaleTimeString("es", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    {!event.all_day && "– "}
                    {!event.all_day && new Date(event.end).toLocaleTimeString("es", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </time>
                  <strong>{event.title}</strong>
                  {event.description && <p>{event.description}</p>}
                  <span className="muted">
                    {event.source === "google" ? "Google Calendar · abrir en Google" :
                      projects.find((p) => p.id === event.project_id)?.title || "Personal"}
                  </span>
                </button>
              ))}
              {dayTasks.map((task) => (
                <div className="agenda-event task-event" key={task.id}>
                  <time>Fecha objetivo · tarea</time>
                  <strong>{task.title}</strong>
                  <span className="muted">
                    {projects.find((p) => p.id === task.project_id)?.title ||
                      "Personal"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
      <Dialog
        open={!!form}
        onOpenChange={(open) => {
          if (!open && !busy) setForm(null);
        }}
      >
        <DialogContent className="editor-dialog">
          <DialogHeader>
            <DialogTitle>
              {form?.id ? "Editar evento" : "Nuevo evento"}
            </DialogTitle>
            <DialogDescription>
              Se guarda en tu agenda local. Las fechas usan la zona horaria de
              este dispositivo.
            </DialogDescription>
          </DialogHeader>
          {form && (
            <form
              className="form-stack"
              onSubmit={async (e) => {
                e.preventDefault();
                if (new Date(form.end) <= new Date(form.start)) {
                  toast.error("El final debe ser posterior al inicio.");
                  return;
                }
                setBusy(true);
                try {
                  await api(
                    "/calendar" + (form.id ? "/" + form.id : ""),
                    form.id ? "PATCH" : "POST",
                    {
                      title: form.title,
                      description: form.description,
                      start: new Date(form.start).toISOString(),
                      end: new Date(form.end).toISOString(),
                      project_id: form.project_id || null,
                    },
                  );
                  await load();
                  setForm(null);
                  toast.success("Evento guardado.");
                } catch (error) {
                  toast.error((error as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label>
                Título
                <Input
                  autoFocus
                  required
                  maxLength={300}
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                />
              </label>
              <div className="two-fields">
                <label>
                  Inicio
                  <Input
                    type="datetime-local"
                    required
                    value={form.start}
                    onChange={(e) =>
                      setForm({ ...form, start: e.target.value })
                    }
                  />
                </label>
                <label>
                  Fin
                  <Input
                    type="datetime-local"
                    required
                    value={form.end}
                    onChange={(e) => setForm({ ...form, end: e.target.value })}
                  />
                </label>
              </div>
              <label>
                Descripción
                <Textarea
                  maxLength={10000}
                  value={form.description}
                  onChange={(e) =>
                    setForm({ ...form, description: e.target.value })
                  }
                />
              </label>
              <label>
                Proyecto
                <Choice
                  label="Proyecto del evento"
                  value={form.project_id || "none"}
                  onChange={(value) =>
                    setForm({
                      ...form,
                      project_id: value === "none" ? null : value,
                    })
                  }
                  options={[
                    ["none", "Personal"],
                    ...projects.map((p) => [p.id, p.title] as [string, string]),
                  ]}
                />
              </label>
              <div className="row between">
                <Button disabled={busy}>
                  {busy ? "Guardando…" : "Guardar evento"}
                </Button>
                {form.id && (
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => setConfirmDelete(true)}
                  >
                    <Trash2 size={15} />
                    Eliminar
                  </Button>
                )}
              </div>
              {confirmDelete && (
                <div className="notice">
                  <p>Se eliminará este evento de la agenda.</p>
                  <div className="row">
                    <Button
                      type="button"
                      variant="destructive"
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true);
                        try {
                          await api("/calendar/" + form.id, "DELETE");
                          await load();
                          setForm(null);
                          toast.success("Evento eliminado.");
                        } catch (e) {
                          toast.error((e as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      Confirmar eliminación
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setConfirmDelete(false)}
                    >
                      Cancelar
                    </Button>
                  </div>
                </div>
              )}
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
