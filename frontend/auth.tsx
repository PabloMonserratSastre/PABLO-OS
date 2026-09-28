import { useEffect, useState } from "react";
import { ArrowUpRight, ShieldCheck } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { api } from "./api";
export function Login({ onLogin }: { onLogin: () => void }) {
  const [setup, setSetup] = useState<boolean | null>(null);
  const [name, setName] = useState("Pablo");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<{ setup_required: boolean }>("/auth/status")
      .then((s) => setSetup(s.setup_required))
      .catch((e) => setError(e.message));
  }, []);
  return (
    <main className="login-screen">
      <div className="login-brand">
        <img className="logo" src="/assets/pablo-logo-transparent.png" alt="" width={44} height={44} />PABLO <em>OS</em>
      </div>
      <div className="login-card">
        <div className="eyebrow">TU ESPACIO PERSONAL</div>
        <h1>
          {setup ? "Todo empieza con un objetivo." : "Vuelve a tu espacio."}
        </h1>
        <p className="muted">
          {setup
            ? "Crea tu cuenta local. Después podrás organizar proyectos, consultar tus documentos y dar el siguiente paso."
            : "Tus proyectos, tu memoria y tus próximos pasos."}
        </p>
        {setup === null && error && (
          <Button
            variant="outline"
            onClick={() => {
              setError("");
              api<{ setup_required: boolean }>("/auth/status")
                .then((s) => setSetup(s.setup_required))
                .catch((e) => setError(e.message));
            }}
          >
            Volver a comprobar la conexión
          </Button>
        )}
        <form
          className="form-stack"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api(setup ? "/auth/setup" : "/auth/login", "POST", {
                name,
                password,
              });
              onLogin();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {setup && (
            <label>
              Tu nombre
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                autoComplete="name"
              />
            </label>
          )}
          <label>
            Contraseña
            <Input
              type="password"
              minLength={12}
              maxLength={256}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={setup ? "new-password" : "current-password"}
            />
          </label>
          <p className="muted">Mínimo 12 caracteres.</p>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <Button disabled={busy || setup === null}>
            {busy ? "Entrando…" : setup ? "Crear mi espacio" : "Entrar"}
            <ArrowUpRight size={18} />
          </Button>
        </form>
        <div className="login-note">
          <ShieldCheck size={18} />
          Tú decides qué proveedor conectar.
        </div>
      </div>
      <p className="login-bottom">PABLO OS · v0.4 · PRIVADO Y SINCRONIZADO</p>
    </main>
  );
}
