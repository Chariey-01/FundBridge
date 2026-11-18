import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App.tsx";
import { EnvironmentProvider } from "./session/EnvironmentContext.tsx";
import { SessionProvider } from "./session/SessionContext.tsx";
import "./styles/app.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <EnvironmentProvider>
          <App />
        </EnvironmentProvider>
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
);
