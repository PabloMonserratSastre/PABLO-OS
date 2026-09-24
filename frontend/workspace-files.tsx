import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Button } from "@/components/ui/button";

export function WorkspaceFiles() {
  const [files, setFiles] = useState<{path: string; bytes: number}[]>([]);
  const [content, setContent] = useState<{path: string; content: string} | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [truncated, setTruncated] = useState(false);
  const selection = useRef(0);
  const groups = new Map<string, typeof files>();
  for (const file of files) {
    const folder = file.path.includes("/") ? file.path.split("/")[0] : "Archivos sueltos";
    groups.set(folder, [...(groups.get(folder) || []), file]);
  }
  const load = useCallback(async () => {
    try { const data = await api<{files: typeof files; truncated: boolean}>("/workspace/files"); setFiles(data.files); setTruncated(data.truncated); setError(""); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { let mounted = true; const requests = selection; void Promise.resolve().then(() => {if (mounted) void load();}); return () => {mounted = false; requests.current++;}; }, [load]);
  return <section className="panel" style={{marginBottom: 24}}>
    <div className="section-header"><div><h2>Archivos de tu workspace</h2><p className="muted">Cada web nueva tiene su carpeta. Despliega un proyecto para ver y descargar sus archivos.</p></div><Button variant="outline" onClick={() => {setLoading(true); void load();}} disabled={loading}>Actualizar archivos</Button></div>
    {error && <p className="error" role="alert">{error}</p>}
    {loading ? <p role="status">Cargando archivos…</p> : !files.length ? <p>Aún no hay archivos generados.</p> : Array.from(groups, ([folder, entries]) => <details key={folder} style={{padding: "12px 0"}}>
      <summary style={{cursor: "pointer"}}><strong>{folder}</strong> · {entries.length} archivos</summary>
      {entries.filter(file => /\.html?$/i.test(file.path)).map(file => <a key={file.path} className="inline-flex items-center rounded-md border px-4 py-2 my-2" href={"/api/v1/workspace/preview/" + file.path.split('/').map(encodeURIComponent).join('/')} target="_blank" rel="noopener noreferrer">Abrir web · {file.path.split('/').at(-1)}</a>)}
      {entries.map(file => <div className="row between" key={file.path} style={{padding: "8px 0", flexWrap: "wrap"}}>
      <Button variant="ghost" onClick={async () => { const current = ++selection.current; setError(""); try { const result = await api<{path: string; content: string}>("/workspace/content?path=" + encodeURIComponent(file.path)); if (current === selection.current) setContent(result); } catch(e) {if (current === selection.current) setError((e as Error).message);} }}>{file.path}</Button>
      <a href={"/api/v1/workspace/download?path=" + encodeURIComponent(file.path)} download>Descargar · {file.bytes} bytes</a>
    </div>)}</details>)}
    {truncated && <p className="muted">Se muestran los primeros 500 archivos.</p>}
    {content && <div><div className="row between"><h3>{content.path}</h3><Button variant="ghost" onClick={() => { selection.current++; setContent(null); }}>Cerrar archivo</Button></div><pre style={{overflow: "auto", maxHeight: 450, whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>{content.content}</pre></div>}
  </section>;
}
