import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { setUnauthorizedHandler } from "./api/client";
import LoginPage from "./pages/LoginPage";
import HomePage from "./pages/HomePage";
import { Shell } from "./components/Shell";

function UnauthorizedBridge() {
  const navigate = useNavigate();
  useEffect(() => {
    // глобальный 401 (протухшая сессия в любой момент) → на логин. Логин-вызов исключён (skipAuthRedirect).
    // navigate нестабилен (меняется на каждом переходе) → эффект пере-регистрирует хендлер свежим navigate.
    setUnauthorizedHandler(() => navigate("/login", { replace: true }));
    return () => setUnauthorizedHandler(() => {}); // сброс при размонтировании — явный контракт, без висячего замыкания
  }, [navigate]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <UnauthorizedBridge />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<Shell />}>
              <Route path="/" element={<HomePage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
