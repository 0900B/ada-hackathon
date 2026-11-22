import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import "@fontsource-variable/inter";
import App from "./App";
import { captureKeyFromUrl } from "./adminKey";
import "./styles.css";

captureKeyFromUrl(); // ?key=… (demo lock): kept on this device, removed from the address bar before the router starts

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
