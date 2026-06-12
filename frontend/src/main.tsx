import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/reset.css"; // глобальный минимум (бокс-модель/высоты); токены — @value в tokens.module.css

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
