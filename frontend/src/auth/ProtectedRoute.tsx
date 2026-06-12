import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div>Загрузка…</div>; // сплэш: не моргаем логином при валидной куке
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}
