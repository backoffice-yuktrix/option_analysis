import { apiClient } from './client';

export interface ATRConfig {
  period: number;
  multiplier: number;
  candle_tf: '5m' | '15m' | '30m';
  price_source: 'close' | 'hl';
}

export interface Module1Request {
  instrument: 'NIFTY' | 'BANKNIFTY';
  from_date: string;
  to_date: string;
  pts_to_analyse: number;
  option_range: number;
  expiry_count: number;
  atr: ATRConfig;
}

export interface SwingPoint {
  timestamp: string;
  price: number;
  swing_type: 'Hill' | 'Valley';
}

export interface NonQualifyingLeg {
  date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  start_price: number;
  end_price: number;
}

export interface LegRow {
  date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  leg_type: 'Hill' | 'Valley';
  vix: number | null;
  abs_pts: number;
  start_price: number;
  end_price: number;
  columns: Record<string, number | null>;
}

export interface ColumnMeta {
  label: string;
  group: 'A' | 'B' | 'C' | 'D';
  exp_n?: number;
  strike_label?: string;
  side?: string;
  pct?: number;
}

export interface ChartCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Module1Result {
  instrument: string;
  from_date: string;
  to_date: string;
  pts_to_analyse: number;
  option_range: number;
  expiry_count: number;
  atr: ATRConfig;
  swing_points: SwingPoint[];
  legs: LegRow[];
  non_qualifying_legs: NonQualifyingLeg[];
  column_meta: Record<string, ColumnMeta>;
  chart_candles: ChartCandle[];
  run_id: string;
}

export async function runModule1(req: Module1Request): Promise<Module1Result> {
  const { data } = await apiClient.post<Module1Result>('/module1/run', req);
  return data;
}

export async function getModule1Result(runId: string): Promise<Module1Result> {
  const { data } = await apiClient.get<Module1Result>(`/module1/results/${runId}`);
  return data;
}
