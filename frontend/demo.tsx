"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Folder,
  FolderCode,
  Home,
  LockKeyhole,
  Plus,
  RotateCcw,
  Send,
  Sparkles,
  Terminal,
} from "lucide-react";
import { Button } from "@/components/ui/button";

type DemoView = "Inicio" | "Asistente" | "Proyectos" | "Tareas";
type DemoTask = { id: number; title: string; project: string; priority: "Alta" | "Media" | "Baja"; done: boolean };
type DemoProject = { id: number; title: string; description: string };
type DemoMessage = { id: number; role: "user" | "assistant"; text: string };

const initialTasks: DemoTask[] = [
  { id: 1, title: "Preparar presentación de PABLO OS", project: "Lanzamiento público", priority: "Alta", done: false },
  { id: 2, title: "Revisar comentarios del repositorio", project: "Lanzamiento público", priority: "Media", done: false },
  { id: 3, title: "Diseñar la página del portfolio", project: "Portfolio personal", priority: "Media", done: true },
];

const initialProjects: DemoProject[] = [
  { id: 1, title: "Lanzamiento público", description: "Preparar PABLO OS para enseñarlo, recibir opiniones y seguir mejorándolo." },
  { id: 2, title: "Portfolio personal", description: "Reunir proyectos, experiencia y aprendizajes en una web clara." },
];

const nav = [
  ["Inicio", Home],
  ["Asistente", Terminal],
  ["Proyectos", Folder],
  ["Tareas", Check],
] as const;

function cleanTitle(value: string) {
  return value.replace(/[.!?]+$/, "").trim().slice(0, 90);
}

export default function Demo() {
  const [view, setView] = useState<DemoView>("Inicio");
  const [tasks, setTasks] = useState(initialTasks);
  const [projects, setProjects] = useState(initialProjects);
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [messages, setMessages] = useState<DemoMessage[]>([
    {
      id: 1,
      role: "assistant",
      text: "Hola. Esta demo usa respuestas de ejemplo, sin IA conectada. Pídeme tus tareas o prueba a crear una tarea o un proyecto.",
    },
  ]);

  const pending = tasks.filter((task) => !task.done);
  const completed = tasks.filter((task) => task.done).length;
  const date = new Intl.DateTimeFormat("es-ES", { weekday: "long", day: "numeric", month: "long" }).format(new Date());
  const projectProgress = useMemo(
    () =>
      Object.fromEntries(
        projects.map((project) => {
          const related = tasks.filter((task) => task.project === project.title);
          return [project.id, related.length ? Math.round((related.filter((task) => task.done).length / related.length) * 100) : 0];
        }),
      ),
    [projects, tasks],
  );

  function flash(text: string) {
    setNotice(text);
    window.setTimeout(() => setNotice(""), 2600);
  }

  function toggleTask(id: number) {
    setTasks((current) => current.map((task) => (task.id === id ? { ...task, done: !task.done } : task)));
    flash("Tarea actualizada en esta demo.");
  }

  function answer(input: string) {
    const normalized = input.toLocaleLowerCase("es-ES");
    const taskMatch = input.match(/(?:crea|añade|agrega)(?:me)?\s+(?:una\s+)?tarea(?:\s+llamada)?\s+(.+)/i);
    if (taskMatch) {
      const title = cleanTitle(taskMatch[1]);
      setTasks((current) => [
        ...current,
        { id: Date.now(), title, project: "Personal", priority: "Media", done: false },
      ]);
      return `He creado la tarea “${title}”. Puedes verla ahora en Tareas. El cambio solo existe en esta pestaña.`;
    }
    const projectMatch = input.match(/(?:crea|añade|empieza)(?:me)?\s+(?:un\s+)?proyecto(?:\s+llamado)?\s+(.+)/i);
    if (projectMatch) {
      const title = cleanTitle(projectMatch[1]);
      setProjects((current) => [...current, { id: Date.now(), title, description: "Proyecto creado durante la demostración." }]);
      return `He creado el proyecto “${title}”. Ya aparece en Proyectos y desaparecerá al cerrar la demo.`;
    }
    if (/(tareas?|pendiente|prioridad)/.test(normalized)) {
      const list = pending.map((task, index) => `${index + 1}. ${task.title} · prioridad ${task.priority.toLowerCase()}`).join("\n");
      return pending.length ? `Tienes ${pending.length} tareas pendientes:\n\n${list}` : "No tienes tareas pendientes en esta demo.";
    }
    if (/proyectos?/.test(normalized)) return projects.map((p) => "• " + p.title).join("\n") || "No hay proyectos.";
    if (/^(hola|buenas|hey|qué tal|que tal)/.test(normalized)) {
      return "¡Hola! Puedes pedirme algo concreto: “dime mis tareas”, “qué tengo mañana” o “crea una tarea llamada preparar la demo”.";
    }
    return "Puedo ayudarte a organizar tus tareas y proyectos. Esta demo interpreta un conjunto seguro de peticiones; la versión privada utiliza el proveedor de IA configurado por su propietario.";
  }

  function send(event?: FormEvent) {
    event?.preventDefault();
    const text = goal.trim();
    if (!text || busy) return;
    setMessages((current) => [...current, { id: Date.now(), role: "user", text }]);
    setGoal("");
    setBusy(true);
    setView("Asistente");
    window.setTimeout(() => {
      setMessages((current) => [...current, { id: Date.now() + 1, role: "assistant", text: answer(text) }]);
      setBusy(false);
    }, 520);
  }

  function reset() {
    setTasks(initialTasks);
    setProjects(initialProjects);
    setMessages((current) => current.slice(0, 1));
    setView("Inicio");
    flash("Demo restaurada.");
  }

  return (
    <div className="demo-shell">
      <aside className="demo-sidebar">
        <a className="demo-brand" href="/demo" aria-label="PABLO OS demo">
          <img src="/assets/pablo-logo-transparent.png" alt="" width={42} height={42} />
          <span>PABLO <em>OS</em></span>
        </a>
        <div className="demo-label">DEMO INTERACTIVA</div>
        <nav aria-label="Secciones de la demostración">
          {nav.map(([name, Icon]) => (
            <button key={name} className={view === name ? "active" : ""} onClick={() => setView(name)}>
              <Icon size={18} /><span>{name}</span>
              {name === "Tareas" && pending.length > 0 && <b>{pending.length}</b>}
            </button>
          ))}
        </nav>
        <div className="demo-privacy">
          <LockKeyhole size={18} />
          <div><strong>Prueba sin riesgos</strong><p>No se guarda ni se envía información personal.</p></div>
        </div>
        <Button variant="outline" onClick={reset}><RotateCcw size={15} /> Reiniciar demo</Button>
      </aside>

      <section className="demo-workspace">
        <header className="demo-topbar">
          <div><span>Demo pública</span><ArrowRight size={14} /><strong>{view}</strong></div>
          <div className="demo-top-actions">
            <span className="demo-pill"><i /> Datos temporales</span>
            <a href="https://github.com/PabloMonserratSastre/PABLO-OS" target="_blank" rel="noreferrer"><FolderCode size={17} /> Ver código</a>
            {/* Vite serves this route directly; it does not use the Next router. */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a href="/">Acceso privado</a>
          </div>
        </header>

        <main className="demo-content">
          <div className="demo-banner">
            <Sparkles size={20} />
            <p><strong>Simulación sin IA conectada.</strong> Prueba tareas y proyectos: los cambios se borran al recargar.</p>
            <span>DEMO</span>
          </div>
          {notice && <div className="demo-notice" role="status">{notice}</div>}

          <div className="demo-heading">
            <div><div className="eyebrow">{view === "Inicio" ? date : `TU ESPACIO / ${view.toUpperCase()}`}</div>
              <h1>{view === "Inicio" ? "Hola, visitante." : view === "Asistente" ? "Pide. Entiende. Actúa." : view}</h1>
              <p>{view === "Inicio" ? "Descubre cómo una IA convierte una intención en un siguiente paso." : view === "Asistente" ? "Prueba una petición cotidiana y observa el resultado." : "Datos preparados para explorar la experiencia sin usar información real."}</p>
            </div>
          </div>

          {view === "Inicio" && <>
            <section className="demo-hero">
              <div><span className="demo-kicker"><Sparkles size={16} /> TU COPILOTO PERSONAL</span>
                <h2>Todo tu día,<br />en una conversación.</h2>
                <p>Tus deberes, tareas y proyectos, organizados en una conversación. Menos pantallas, más claridad.</p>
                <Button onClick={() => setView("Asistente")}>Probar Asistente <ArrowRight size={17} /></Button>
              </div>
              <div className="demo-hero-card">
                <p>Prueba a escribir</p>
                {["Dime mis tareas pendientes", "Dime mis proyectos pendientes", "Crea una tarea llamada llamar al dentista"].map((hint) =>
                  <button key={hint} onClick={() => { setGoal(hint); setView("Asistente"); }}>{hint}<ArrowRight size={15} /></button>)}
              </div>
            </section>
            <div className="demo-metrics">
              <div><strong>{pending.length}</strong><span>Tareas pendientes</span></div>
              <div><strong>{projects.length}</strong><span>Proyectos abiertos</span></div>
              <div><strong>{completed}</strong><span>Tareas completadas</span></div>
              <div><strong>0</strong><span>Datos persistidos</span></div>
            </div>
            <div className="demo-dashboard">
              <section className="panel"><div className="demo-section-title"><div><span>DA EL SIGUIENTE PASO</span><h2>Tu foco</h2></div><button onClick={() => setView("Tareas")}>Ver tareas <ArrowRight size={14} /></button></div>
                {pending.slice(0, 3).map((task) => <div className="demo-task-row" key={task.id}><button aria-label={`Completar ${task.title}`} onClick={() => toggleTask(task.id)}><Check size={14} /></button><div><strong>{task.title}</strong><p>{task.project}</p></div><span>{task.priority}</span></div>)}
              </section>
              <section className="panel demo-agenda"><span>EN TU RADAR</span><h2>Tus proyectos</h2>{projects.map((p) => <div key={p.id}><p>{p.title}</p></div>)}<button onClick={() => setView("Proyectos")}>Ver proyectos <ArrowRight size={14} /></button></section>
            </div>
          </>}

          {view === "Asistente" && <section className="demo-command">
            <div className="demo-messages" role="log" aria-live="polite">
              {messages.map((message) => <article key={message.id} className={message.role}><span>{message.role === "user" ? "Tú" : "PABLO OS"}</span><p>{message.text}</p></article>)}
              {busy && <article className="assistant"><span>PABLO OS</span><p className="demo-thinking">Organizando la respuesta…</p></article>}
            </div>
            <form className="demo-composer" onSubmit={send}>
              <Sparkles size={22} /><input aria-label="Escribe una petición" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="¿Qué quieres conseguir?" maxLength={300} />
              <Button type="submit" size="icon" disabled={!goal.trim() || busy}><Send size={17} /></Button>
            </form>
            <div className="demo-chips">{["Dime mis tareas", "¿Qué tengo mañana?", "Crea un proyecto llamado Viaje a Japón"].map((hint) => <button key={hint} onClick={() => setGoal(hint)}>{hint}</button>)}</div>
          </section>}

          {view === "Proyectos" && <div className="demo-cards">{projects.map((project) => <article className="panel" key={project.id}><div className="demo-card-icon"><Folder size={19} /></div><h2>{project.title}</h2><p>{project.description}</p><div className="demo-progress"><i style={{ width: `${projectProgress[project.id]}%` }} /></div><small>{projectProgress[project.id]}% completado</small></article>)}<button className="demo-add-card" onClick={() => { setGoal("Crea un proyecto llamado "); setView("Asistente"); }}><Plus size={22} /> Crear un proyecto desde Asistente</button></div>}

          {view === "Tareas" && <section className="panel demo-list"><div className="demo-list-head"><div><h2>Todas las tareas</h2><p>{completed} completadas · {pending.length} pendientes</p></div><Button onClick={() => { setGoal("Crea una tarea llamada "); setView("Asistente"); }}><Plus size={16} /> Nueva tarea</Button></div>{tasks.map((task) => <div className={`demo-list-row ${task.done ? "done" : ""}`} key={task.id}><button onClick={() => toggleTask(task.id)}>{task.done ? <CheckCircle2 size={21} /> : <span />}</button><div><strong>{task.title}</strong><p>{task.project}</p></div><b>{task.priority}</b></div>)}</section>}


        </main>
      </section>
    </div>
  );
}
