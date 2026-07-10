import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("No existe el elemento #root en index.html");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
