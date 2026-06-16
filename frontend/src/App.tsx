import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { lazy, Suspense, useEffect } from "react";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AdminRoute } from "./admin/AdminRoute";
import { setUnauthorizedHandler } from "./api/client";
import { Shell } from "./components/Shell";

// экраны — ленивые chunk'и по роутам: каждый срез грузит своё, index не пухнет
const LoginPage = lazy(() => import("./pages/LoginPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const GamePage = lazy(() => import("./pages/GamePage"));
const NewGamePage = lazy(() => import("./pages/NewGamePage"));
const AdminPage = lazy(() => import("./admin/AdminPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));

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
        <Suspense fallback={<div>Загрузка…</div>}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<Shell />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/new" element={<NewGamePage />} />
                <Route path="/game/:gameId" element={<GamePage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route element={<AdminRoute />}>
                  <Route path="/admin" element={<AdminPage />} />
                </Route>
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  );
}
