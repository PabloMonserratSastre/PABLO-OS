import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useState } from "react";
import { Approval, Run, api, terminal, toolLabels } from "./api";
import { Badge, RichText, withoutSynthesis } from "./common";

function ResultDownloads({ tool, result }: { tool: string; result: unknown }) {
  if (
    !result ||
    typeof result !== "object" ||
    ![
      "workspace.list",
      "workspace.read",
      "workspace.write",
      "code.scaffold",
      "game.scaffold",
      "files.create",
    ].includes(tool)
  )
    return null;
  const value = result as { path?: string; files?: { path: string }[] };
  const paths =
    value.files?.map((file) => file.path) || (value.path ? [value.path] : []);
  return (
    <div className="result-downloads">
      {paths.map((path) => (
        <a
          key={path}
          className="download-link"
          href={"/api/v1/workspace/download?path=" + encodeURIComponent(path)}
          download
        >
          Descargar {path}
        </a>
      ))}
    </div>
  );
}
export function Execution({
  run,
  approvals,
  close,
  refresh,
  onError,
}: {
  run: Run;
  approvals: Approval[];
  close: () => void;
  refresh: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  async function action(path: string, body?: unknown) {
    if (busy) return;
    setBusy(true);
    try {
      await api(path, "POST", body);
      refresh();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const done = run.plan.filter((s) => s.status === "DONE").length;
  return (
    <section className="panel execution-inline" aria-label="Detalle de ejecución">
      <div className="row between"><h3>Detalle de ejecución</h3><Button variant="ghost" size="sm" onClick={close}>Ocultar detalles</Button></div>
        <div className="execution-body">
          <Badge value={run.status} />
          <p className="muted">
            {done} de {run.plan.length} pasos verificados
          </p>
          <Progress
            value={run.plan.length ? (done / run.plan.length) * 100 : 0}
          />
          {run.plan.map((step, i) => (
            <div key={i} className="step">
              <span className="step-number">{i + 1}</span>
              <div>
                <strong>{toolLabels[step.tool] || step.tool}</strong>
                <p className="muted">
                  {step.status === "DONE"
                    ? "Resultado registrado"
                    : "Pendiente"}
                  {step.depends_on.length
                    ? " · depende de " +
                      step.depends_on.map((d) => d + 1).join(", ")
                    : ""}
                </p>
                <details>
                  <summary>Ver parámetros y resultado</summary>
                  <pre>
                    {JSON.stringify(
                      { arguments: step.arguments, result: step.result },
                      null,
                      2,
                    )}
                  </pre>
                </details>
                <ResultDownloads tool={step.tool} result={step.result} />
              </div>
            </div>
          ))}
          {approvals
            .filter((a) => a.run_id === run.id)
            .map((a) => (
              <div className="approval" key={a.id}>
                <h3>Necesito tu aprobación</h3>
                <p>
                  {toolLabels[a.tool.split(":").slice(1).join(":")] || a.tool}
                </p>
                <pre>{JSON.stringify(a.payload, null, 2)}</pre>
                <div className="row">
                  <Button
                    disabled={busy}
                    onClick={() =>
                      action("/approvals/" + a.id, { approve: true })
                    }
                  >
                    Aprobar este paso
                  </Button>
                  <Button
                    disabled={busy}
                    variant="outline"
                    onClick={() =>
                      action("/approvals/" + a.id, { approve: false })
                    }
                  >
                    Rechazar
                  </Button>
                </div>
              </div>
            ))}
          {!terminal.has(run.status) && (
            <Button
              disabled={busy}
              variant="outline"
              onClick={() => action("/runs/" + run.id + "/cancel")}
            >
              Detener ejecución
            </Button>
          )}
          {run.status === "FAILED" && (
            <Button
              disabled={busy}
              onClick={() => action("/runs/" + run.id + "/retry")}
            >
              Reintentar paso fallido
            </Button>
          )}
          <div className="result">
            <h3>Resultado</h3>
            <RichText text={withoutSynthesis(run.result || "Esperando al worker…")} />
          </div>
          <p className="muted">
            {run.usage.provider === "LOCAL_TEMPLATE"
              ? "Plantilla local · sin IA"
              : run.usage.provider === "LOCAL_COMMAND"
                ? "Orden exacta · sin IA"
              : run.usage.provider || "Proveedor pendiente"}
            {run.usage.total_tokens
              ? " · " + run.usage.total_tokens + " tokens"
              : ""}
          </p>
        </div>
    </section>
  );
}
