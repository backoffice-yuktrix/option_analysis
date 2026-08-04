/**
 * Column picker panel — grouped checkboxes per PRD §8.4.
 * Groups A, D, E: flat list of checkboxes.
 * Groups B and C: 2D matrix — rows = strikes, columns = checkpoints, tabbed per expiry.
 */
import { useState } from 'react';
import { ChevronDown, ChevronRight, Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';

export interface ColumnMeta {
  label: string;
  group: string;
  exp_n?: number;
  strike_label?: string;
  side?: string;
  pct?: number;
  [key: string]: unknown;
}

interface ColumnPickerProps {
  columnMeta: Record<string, ColumnMeta>;
  selected: Set<string>;
  onToggle: (key: string) => void;
  onSelectAll: (keys: string[]) => void;
  onDeselectAll: (keys: string[]) => void;
}

const GROUP_LABELS: Record<string, string> = {
  A: 'Group A — Instrument Checkpoints',
  B: 'Group B — Along Options',
  C: 'Group C — Against Options',
  D: 'Group D — Metrics',
  E: 'Group E — DTE & Metrics',
};

// Canonical strike label order per PRD §3.3 (ATM-range … ATM … ATM+range, then cheapest)
const STRIKE_ORDER = ['ATMm3', 'ATMm2', 'ATMm1', 'ATM', 'ATMp1', 'ATMp2', 'ATMp3', 'cheapest'];

function strikeRank(label: string): number {
  const idx = STRIKE_ORDER.indexOf(label);
  return idx === -1 ? STRIKE_ORDER.length : idx;
}

// ---------------------------------------------------------------------------
// Flat group (A, D, E)
// ---------------------------------------------------------------------------

function FlatGroupSection({
  label,
  columns,
  selected,
  onToggle,
}: {
  label: string;
  columns: [string, ColumnMeta][];
  selected: Set<string>;
  onToggle: (k: string) => void;
}) {
  const [open, setOpen] = useState(true);
  if (!columns.length) return null;
  return (
    <div className="border rounded-md overflow-hidden">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium bg-muted/50 hover:bg-muted transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        <span>{label}</span>
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
      </button>
      {open && (
        <div className="grid grid-cols-2 gap-1 p-3 sm:grid-cols-3">
          {columns.map(([key, meta]) => (
            <label key={key} className="flex items-center gap-2 cursor-pointer text-xs">
              <Checkbox
                checked={selected.has(key)}
                onCheckedChange={() => onToggle(key)}
                id={`col-${key}`}
              />
              <span className="truncate" title={meta.label}>{meta.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Option group (B / C) — 2D matrix: strike rows × checkpoint columns, per expiry
// ---------------------------------------------------------------------------

function OptionGroupSection({
  label,
  columns,
  selected,
  onToggle,
}: {
  label: string;
  columns: [string, ColumnMeta][];
  selected: Set<string>;
  onToggle: (k: string) => void;
}) {
  const [open, setOpen] = useState(true);
  if (!columns.length) return null;

  // Collect unique exp_ns, strike_labels, pcts
  const expNs = [...new Set(columns.map(([, m]) => m.exp_n ?? 1))].sort((a, b) => a - b);
  const strikes = [...new Set(columns.map(([, m]) => m.strike_label ?? ''))].sort(
    (a, b) => strikeRank(a) - strikeRank(b),
  );
  const pcts = [...new Set(columns.map(([, m]) => m.pct ?? 0))].sort((a, b) => a - b);

  // Build lookup: `${exp_n}|${strike_label}|${pct}` → column key
  const lookup = new Map<string, string>();
  for (const [key, m] of columns) {
    lookup.set(`${m.exp_n}|${m.strike_label}|${m.pct}`, key);
  }

  const [activeExp, setActiveExp] = useState(expNs[0] ?? 1);

  return (
    <div className="border rounded-md overflow-hidden">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium bg-muted/50 hover:bg-muted transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        <span>{label}</span>
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
      </button>

      {open && (
        <div className="p-3 overflow-x-auto">
          {/* Expiry tabs */}
          {expNs.length > 1 && (
            <div className="flex gap-1 mb-2">
              {expNs.map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setActiveExp(n)}
                  className={cn(
                    'px-2 py-0.5 rounded text-xs font-medium transition-colors',
                    activeExp === n
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                  )}
                >
                  Expiry {n}
                </button>
              ))}
            </div>
          )}

          {/* Strike × checkpoint matrix */}
          <table className="text-xs border-collapse w-full min-w-max">
            <thead>
              <tr>
                <th className="px-2 py-1 text-left text-muted-foreground font-medium">Strike</th>
                {pcts.map((p) => (
                  <th key={p} className="px-2 py-1 text-center text-muted-foreground font-medium">
                    {p}%
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {strikes.map((strike) => (
                <tr key={strike} className="border-t border-border/40">
                  <td className="px-2 py-1 font-mono text-muted-foreground whitespace-nowrap">
                    {strike === 'cheapest' ? '★ Cheapest' : strike}
                  </td>
                  {pcts.map((p) => {
                    const key = lookup.get(`${activeExp}|${strike}|${p}`);
                    if (!key) return <td key={p} className="px-2 py-1 text-center">—</td>;
                    return (
                      <td key={p} className="px-2 py-1 text-center">
                        <Checkbox
                          checked={selected.has(key)}
                          onCheckedChange={() => onToggle(key)}
                          id={`col-${key}`}
                          className="mx-auto"
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ColumnPicker
// ---------------------------------------------------------------------------

export function ColumnPicker({ columnMeta, selected, onToggle }: ColumnPickerProps) {
  const [open, setOpen] = useState(false);

  const byGroup: Record<string, [string, ColumnMeta][]> = {};
  for (const [key, meta] of Object.entries(columnMeta)) {
    const g = meta.group ?? 'D';
    if (!byGroup[g]) byGroup[g] = [];
    byGroup[g].push([key, meta]);
  }

  return (
    <div className="relative">
      <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)}>
        <Settings2 className="size-4" />
        Columns
        <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} />
      </Button>

      {open && (
        <div className="absolute left-0 top-10 z-20 w-[600px] max-h-[520px] overflow-y-auto rounded-lg border bg-popover p-3 shadow-lg flex flex-col gap-2">
          <div className="text-sm font-medium text-muted-foreground mb-1">
            {selected.size} column{selected.size !== 1 ? 's' : ''} selected
          </div>

          {Object.entries(GROUP_LABELS).map(([g, glabel]) => {
            if (!byGroup[g]) return null;
            if (g === 'B' || g === 'C') {
              return (
                <OptionGroupSection
                  key={g}
                  label={glabel}
                  columns={byGroup[g]}
                  selected={selected}
                  onToggle={onToggle}
                />
              );
            }
            return (
              <FlatGroupSection
                key={g}
                label={glabel}
                columns={byGroup[g]}
                selected={selected}
                onToggle={onToggle}
              />
            );
          })}

          <div className="flex justify-end pt-1">
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Done
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
