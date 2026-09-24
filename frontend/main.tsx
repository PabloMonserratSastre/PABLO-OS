import { createRoot } from "react-dom/client";
import Pablo from "./pablo";
import "../app/globals.css";
createRoot(document.getElementById("root")!).render(<Pablo />);
if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
