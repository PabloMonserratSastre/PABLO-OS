import { createRoot } from "react-dom/client";
import Pablo from "./pablo";
import Demo from "./demo";
import "../app/globals.css";
const route = window.location.pathname.replace(/\/+$/, "") || "/";
createRoot(document.getElementById("root")!).render(route === "/demo" ? <Demo /> : <Pablo />);
if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
