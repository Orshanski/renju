import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

// Гейт админки: пускает только role==="admin". Не-admin → на главную (бэк всё равно
// сторожит эндпоинт 403; это UX-гейт, не безопасность).
export function AdminRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div>Загрузка…</div>;
  if (user?.role !== "admin") return <Navigate to="/" replace />;
  return <Outlet />;
}
