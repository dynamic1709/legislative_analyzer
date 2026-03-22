export const API_BASE = (import.meta.env.VITE_API_BASE || "").trim();

export function apiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  if (API_BASE) {
    return `${API_BASE.replace(/\/$/, "")}${normalizedPath}`;
  }

  // Dev default: use Vite proxy (/api -> backend)
  return `/api${normalizedPath}`;
}
