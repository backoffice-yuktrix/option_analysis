/**
 * Axios instance for the option_analysis backend.
 * No JWT — this is a standalone single-user app.
 * Vite proxies /api → http://localhost:8000 in dev.
 */
import axios from 'axios';

export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 600_000,  // 10 min — analysis runs can be long
  headers: { 'Content-Type': 'application/json' },
});

// Normalize errors to a string message
export function extractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg ?? String(d)).join('; ');
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}
