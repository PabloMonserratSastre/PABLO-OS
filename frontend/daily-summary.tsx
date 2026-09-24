import { useState } from "react";
import { Sun, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, Run, terminal, labels } from "./api";
import { RichText } from "./common";

export function DailySummary({ run, onRun }: { run?: Run | null; onRun: (id: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <section className="panel daily-summary" aria-label="Resumen diario">
    <div className="section-header">
      <div><h2><Sun size={20} /> Tu resumen diario</h2>
        <p className="muted">{run ? `Última ejecución: ${new Date(run.created_at).toLocaleString("es-ES")}` : "Tus correos y tu agenda, juntos aquí."}</p></div>
      <Button variant="outline" disabled={busy || !!run && !terminal.has(run.status)} onClick={async () => {
        setBusy(true); setError("");
        try { const result = await api<Run>("/commands", "POST", { goal: "Preparar mi resumen diario", mode: "DO" }); onRun(result.id); }
        catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
      }}><RefreshCw size={15} /> Actualizar resumen</Button>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    {run?.status === "COMPLETED" ? <RichText text={run.result.replace(/^Resumen diario\s*/, "")} /> :
      <p className="muted">{run ? `Estado: ${labels[run.status] || run.status}.` : "El resumen aparecerá aquí al ejecutarse tu programación. También puedes actualizarlo ahora."}</p>}
    {run && run.status !== "COMPLETED" && <Button variant="ghost" onClick={() => onRun(run.id)}>Ver ejecución</Button>}
  </section>;
}
