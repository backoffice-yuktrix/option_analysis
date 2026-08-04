import { apiClient } from './client';

export interface UpstoxStatus {
  has_credentials: boolean;
  is_connected: boolean;
}

export interface UpstoxCredentials {
  api_key: string;
  api_secret: string;
  redirect_uri: string;
}

export async function getUpstoxStatus(): Promise<UpstoxStatus> {
  const { data } = await apiClient.get<UpstoxStatus>('/upstox/status');
  return data;
}

export async function saveCredentials(creds: UpstoxCredentials): Promise<void> {
  await apiClient.post('/upstox/credentials', creds);
}

export async function getAuthUrl(): Promise<string> {
  const { data } = await apiClient.get<{ auth_url: string }>('/upstox/auth-url');
  return data.auth_url;
}

export async function exchangeToken(code: string, state?: string): Promise<void> {
  await apiClient.post('/upstox/token', { code, state });
}

export async function disconnect(): Promise<void> {
  await apiClient.post('/upstox/disconnect');
}
