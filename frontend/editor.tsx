import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { api, RecordItem } from "./api";
import { Choice } from "./common";
export function Editor({
  kind,
  item,
  projects,
  close,
  saved,
}: {
  kind: string;
  item?: RecordItem;
  projects: RecordItem[];
  close: () => void;
  saved: () => void;
}) {
  const [title, setTitle] = useState(item?.title || "");
  const [description, setDescription] = useState(item?.description || "");
  const [status, setStatus] = useState(
    item?.status || (kind === "projects" ? "IDEA" : "TODO"),
  );
  const [priority, setPriority] = useState(item?.priority || "MEDIUM");
  const [due, setDue] = useState(item?.due || "");
  const [project, setProject] = useState(item?.project_id || "none");
  const [category, setCategory] = useState(item?.category || "user");
  const [pinned, setPinned] = useState(item?.pinned || false);
  const [repository, setRepository] = useState(item?.repository || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nouns: Record<string, string> = {
    projects: "proyecto",
    tasks: "tarea",
    memory: "recuerdo",
    workflows: "workflow",
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className="editor-dialog">
        <DialogHeader>
          <DialogTitle>
            {item ? "Editar" : "Crear"} {nouns[kind]}
          </DialogTitle>
          <DialogDescription>
            {kind === "memory"
              ? "Tú decides qué recordar."
              : "Guarda el objetivo y el siguiente paso."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="form-stack"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api(
                item ? "/items/" + item.id : "/items/" + kind,
                item ? "PUT" : "POST",
                {
                  title,
                  description,
                  status,
                  priority,
                  due,
                  project_id: project === "none" ? null : project,
                  category,
                  pinned,
                  repository,
                  dependencies: item?.dependencies || [],
                  version: item?.version || null,
                },
              );
              saved();
              close();
            } catch (error) {
              setError((error as Error).message);
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
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label>
            {kind === "memory"
              ? "Información que quieres recordar"
              : "Descripción u objetivo"}
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={20000}
            />
          </label>
          {kind === "projects" ? (
            <label>
              Repositorio GitHub
              <Input
                placeholder="propietario/repositorio"
                value={repository}
                onChange={(e) => setRepository(e.target.value)}
              />
            </label>
          ) : (
            <label>
              Proyecto
              <Choice
                label="Proyecto"
                value={project}
                onChange={setProject}
                options={[
                  ["none", "Sin proyecto"],
                  ...projects.map((p) => [p.id, p.title] as [string, string]),
                ]}
              />
            </label>
          )}
          {["projects", "tasks"].includes(kind) && (
            <div className="two-fields">
              <label>
                Estado
                <Choice
                  label="Estado"
                  value={status}
                  onChange={setStatus}
                  options={
                    kind === "projects"
                      ? [
                          "IDEA",
                          "PLANNING",
                          "ACTIVE",
                          "BLOCKED",
                          "REVIEW",
                          "COMPLETED",
                          "ARCHIVED",
                        ]
                      : [
                          "TODO",
                          "PLANNED",
                          "IN_PROGRESS",
                          "WAITING_APPROVAL",
                          "BLOCKED",
                          "TESTING",
                          "DONE",
                          "FAILED",
                          "CANCELLED",
                        ]
                  }
                />
              </label>
              <label>
                Prioridad
                <Choice
                  label="Prioridad"
                  value={priority}
                  onChange={setPriority}
                  options={["HIGH", "MEDIUM", "LOW"]}
                />
              </label>
              <label>
                Fecha objetivo
                <Input
                  type="date"
                  value={due}
                  onChange={(e) => setDue(e.target.value)}
                />
              </label>
            </div>
          )}
          {kind === "memory" && (
            <>
              <label>
                Tipo
                <Choice
                  label="Tipo de memoria"
                  value={category}
                  onChange={setCategory}
                  options={[
                    ["user", "Personal"],
                    ["project", "Proyecto"],
                    ["conversation", "Conversación"],
                    ["knowledge", "Conocimiento"],
                  ]}
                />
              </label>
              <label className="check-label">
                <Checkbox
                  checked={pinned}
                  onCheckedChange={(v) => setPinned(v === true)}
                />
                Fijar en el contexto
              </label>
            </>
          )}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? "Guardando…" : "Guardar " + nouns[kind]}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
