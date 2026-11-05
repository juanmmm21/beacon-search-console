import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import DocsApp from "./DocsApp";
import "../index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("No existe el elemento #root en docs.html");
}

createRoot(container).render(
  <StrictMode>
    <DocsApp />
  </StrictMode>,
);
