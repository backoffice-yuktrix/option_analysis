import { apiClient } from './client';

export interface Module2Request {
  instrument: 'NIFTY' | 'BANKNIFTY';
  from_date: string;
  to_date: string;
  pts_to_analyse: number;
  option_range: number;
  expiry_count: number;
}

export interface SessionRow {
  date: string;
  entry_time: string;
  exit_time: string;
  gap_pts: number;
  gap_direction: 'GapUp' | 'GapDown';
  vix: number | null;
  start_price: number;
  end_price: number;
  columns: Record<string, number | null>;
}

export interface ColumnMeta {
  label: string;
  group: 'B' | 'C' | 'E';
  exp_n?: number;
  strike_label?: string;
  side?: string;
  pct?: number;
}

export interface Module2Result {
  instrument: string;
  from_date: string;
  to_date: string;
  pts_to_analyse: number;
  option_range: number;
  expiry_count: number;
  sessions: SessionRow[];
  column_meta: Record<string, ColumnMeta>;
  run_id: string;
}

export async function runModule2(req: Module2Request): Promise<Module2Result> {
  const { data } = await apiClient.post<Module2Result>('/module2/run', req);
  return data;
}

export async function getModule2Result(runId: string): Promise<Module2Result> {
  const { data } = await apiClient.get<Module2Result>(`/module2/results/${runId}`);
  return data;
}
