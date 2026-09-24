// Supervised development preview: API and UI share one network namespace.
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
const python = process.env.CODEX_PRIMARY_RUNTIME_PYTHON || "python";
const env = {
  ...process.env,
  PYTHONPATH: path.resolve("backend"),
  APP_ORIGIN: process.env.APP_ORIGIN || "http://localhost:5173",
};
const migrated = spawnSync(
  python,
  ["-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
  { env, stdio: "inherit" },
);
if (migrated.error)
  console.error(
    "Python no disponible: instala las dependencias de backend o utiliza Docker.",
  );
if (migrated.status !== 0) process.exit(1);
const children = [
  spawn(
    python,
    [
      "-m",
      "uvicorn",
      "pablo.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
    ],
    { env, stdio: "inherit" },
  ),
  spawn(python, ["-m", "pablo.worker"], { env, stdio: "inherit" }),
  spawn(
    process.execPath,
    ["scripts/run-framework.mjs", "dev", ...process.argv.slice(2)],
    { env, stdio: "inherit" },
  ),
];
function stop() {
  children.forEach((p) => p.kill("SIGTERM"));
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
children.forEach((child) =>
  child.on("exit", (code) => {
    stop();
    process.exit(code || 0);
  }),
);
