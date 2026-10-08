import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/archivo";
import App from "./App";
import { ModelExchangeViewer } from "./components/ModelExchangeViewer";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ModelExchangeViewer><App /></ModelExchangeViewer>
  </StrictMode>,
);
