import { ArrowUpRight, CheckCircle2, Clock3, Radar, Sparkles } from "lucide-react";
import type { CSSProperties } from "react";
import { Button } from "@/components/ui/button";
import type { Pulse as PulseState } from "./api";

export function Pulse({
  pulse,
  busy,
  onPrompt,
  onNavigate,
  onOpenRun,
}: {
  pulse: PulseState;
  busy: boolean;
  onPrompt: (prompt: string) => void;
  onNavigate: (destination: string) => void;
  onOpenRun: (runId: string) => void;
}) {
  const action = pulse.next_action;
  return (
    <section className={`pulse-board pulse-${pulse.tone}`} aria-labelledby="pulse-title">
      <div className="pulse-copy">
        <div className="pulse-kicker"><Radar size={15} /> PULSO DE HOY <span>Actualizado ahora</span></div>
        <h2 id="pulse-title">{pulse.greeting}.</h2>
        <p className="pulse-headline">{pulse.headline}</p>
        <div className="pulse-actions">
          <Button disabled={busy} onClick={() => onPrompt(pulse.organize_prompt)}>
            <Sparkles size={16} /> Organizar mi día
          </Button>
          <Button
            variant="ghost"
            onClick={() => action.prompt ? onPrompt(action.prompt) : onNavigate(action.destination || "Tareas")}
          >
            {action.title}<ArrowUpRight size={15} />
          </Button>
        </div>
      </div>
      <div className="pulse-score" aria-label={`Estado ${pulse.label}, ${pulse.score} de 100`}>
        <div className="pulse-ring" style={{ "--pulse-score": `${pulse.score * 3.6}deg` } as CSSProperties}>
          <div><strong>{pulse.score}</strong><span>de 100</span></div>
        </div>
        <span>{pulse.label}</span>
        <small>Claridad del día</small>
      </div>
      <div className="pulse-signals" aria-label="Señales importantes">
        {pulse.signals.map((signal, index) => (
          <button
            key={`${signal.kind}-${index}`}
            disabled={!signal.destination && !signal.run_id}
            onClick={() => signal.run_id ? onOpenRun(signal.run_id) : signal.destination && onNavigate(signal.destination)}
            aria-label={signal.run_id ? `${signal.title}: abrir el error` : undefined}
          >
            <span className={`signal-icon signal-${signal.kind}`}>
              {signal.kind === "clear" ? <CheckCircle2 size={16} /> : <Clock3 size={16} />}
            </span>
            <span><strong>{signal.title}</strong><small>{signal.detail}</small></span>
            {(signal.destination || signal.run_id) && <ArrowUpRight size={14} />}
          </button>
        ))}
      </div>
    </section>
  );
}
