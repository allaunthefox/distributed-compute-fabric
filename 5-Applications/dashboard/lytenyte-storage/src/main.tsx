import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@1771technologies/lytenyte-core/css/design.css";
import "@1771technologies/lytenyte-core/css/dark.css";
import "@1771technologies/lytenyte-core/css/grid.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
