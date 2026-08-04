import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—';
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: decimals }).format(v);
}

export function formatPercent(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

export function formatPts(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}`;
}
