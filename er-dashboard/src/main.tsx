import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import App from "./App";
import { captureKeyFromUrl } from "./api";
import "./styles.css";

captureKeyFromUrl(); // ?key=… (demo lock): kept on this device and removed from the address bar

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
