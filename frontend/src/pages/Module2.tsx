/**
 * /module2 — Overnight Gap Analysis page.
 * Layout per PRD §8.5: Input panel → 5A Trade Table → 5B Summary (+ gap breakdown)
 */
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Play, Loader2, BarChart3 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { UpstoxButton } from '@/components/UpstoxButton';
import { ColumnPicker } from '@/components/ColumnPicker';
import { useModule2 } from '@/hooks/useModule2';
import { getModule2Result } from '@/api/module2';
import type { Module2Request, SessionRow } from '@/api/module2';
import { formatNumber, formatPercent, formatPts, cn } from '@/lib/utils';

// ── Summary helpers ─────────────────────────────────────────────────────────

function computeSummary(sessions: SessionRow[]) {
  const byDay: Record<string, SessionRow[]> = {};
  for (const s of sessions) {
    if (!byDay[s.date]) byDay[s.date] = [];
    byDay[s.date].push(s);
  }

  const dayRows = Object.entries(byDay)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, dSess]) => {
      const values = dSess.map((s) => (s.columns.profit_percent_optimal_option as number | null) ?? 0);
      const total = values.reduce((s, v) => s + v, 0);
      return { date, count: dSess.length, total, avg: dSess.length > 0 ? total / dSess.length : 0 };
    });

  const weekRows: Record<string, { count: number; total: number; startDate: string }> = {};
  for (const s of sessions) {
    const d = new Date(s.date);
    const day = d.getDay();
    const mon = new Date(d);
    mon.setDate(d.getDate() - (day === 0 ? 6 : day - 1));
    const wk = mon.toISOString().slice(0, 10);
    if (!weekRows[wk]) weekRows[wk] = { count: 0, total: 0, startDate: wk };
    weekRows[wk].count++;
    weekRows[wk].total += (s.columns.profit_percent_optimal_option as number | null) ?? 0;
  }

  // Gap size breakdown
  const gapBuckets = [
    { label: '0–25 pts', min: 0, max: 25 },
    { label: '25–50 pts', min: 25, max: 50 },
    { label: '50–100 pts', min: 50, max: 100 },
    { label: '100+ pts', min: 100, max: Infinity },
  ];
  const gapBreakdown = gapBuckets.map((b) => {
    const filtered = sessions.filter((s) => {
      const gap = Math.abs(s.gap_pts);
      return gap >= b.min && gap < b.max;
    });
    const values = filtered.map((s) => (s.columns.profit_percent_optimal_option as number | null) ?? 0);
    const total = values.reduce((s, v) => s + v, 0);
    return {
      label: b.label,
      count: filtered.length,
      avg: filtered.length > 0 ? total / filtered.length : 0,
    };
  });

  const allValues = sessions.map((s) => (s.columns.profit_percent_optimal_option as number | null) ?? 0);
  const totalAll = allValues.reduce((s, v) => s + v, 0);
  const best = dayRows.reduce((b, r) => (r.avg > (b?.avg ?? -Infinity) ? r : b), dayRows[0]);
  const worst = dayRows.reduce((b, r) => (r.avg < (b?.avg ?? Infinity) ? r : b), dayRows[0]);

  return {
    dayRows,
    weekRows: Object.values(weekRows).sort((a, b) => a.startDate.localeCompare(b.startDate)).map((r) => ({
      ...r,
      avg: r.count > 0 ? r.total / r.count : 0,
    })),
    overall: { count: sessions.length, total: totalAll, avg: sessions.length > 0 ? totalAll / sessions.length : 0 },
    best,
    worst,
    gapBreakdown,
  };
}

// ── Main component ───────────────────────────────────────────────────────────

export function Module2() {
  const { runId } = useParams<{ runId?: string }>();
  const { result, setLoadedResult, mutation, selectedCols, toggleColumn } = useModule2();

  const [form, setForm] = useState<Module2Request>({
    instrument: 'NIFTY',
    from_date: '',
    to_date: '',
    pts_to_analyse: 100,
    option_range: 3,
    expiry_count: 2,
  });

  // Load saved run when runId is in the URL
  const savedQuery = useQuery({
    queryKey: ['module2-saved', runId],
    queryFn: () => getModule2Result(runId!),
    enabled: !!runId,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (!savedQuery.data) return;
    const d = savedQuery.data;
    setForm({
      instrument: d.instrument as 'NIFTY' | 'BANKNIFTY',
      from_date: d.from_date,
      to_date: d.to_date,
      pts_to_analyse: d.pts_to_analyse,
      option_range: d.option_range,
      expiry_count: d.expiry_count,
    });
    setLoadedResult(d);
  }, [savedQuery.data, setLoadedResult]);

  function handleRun() {
    if (!form.from_date || !form.to_date) return;
    mutation.mutate(form);
  }

  const summary = result ? computeSummary(result.sessions) : null;
  const mustHaveCols = ['date', 'entry_time', 'exit_time', 'gap_pts', 'gap_direction', 'vix', 'start_price', 'end_price'];
  const extraCols = result ? [...selectedCols].filter((k) => result.column_meta[k]) : [];

  return (
    <div className="flex flex-col gap-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <BarChart3 className="size-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Module 2 — Overnight Gap Analysis</h1>
            <p className="text-sm text-muted-foreground">3:15 PM entry → 9:25 AM exit across all sessions in range</p>
          </div>
        </div>
        <UpstoxButton />
      </div>

      {/* Input panel */}
      <div className="rounded-lg border bg-card p-4 flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-6">
          <div className="flex flex-col gap-1.5">
            <Label>Instrument</Label>
            <Select value={form.instrument} onValueChange={(v) => setForm((f) => ({ ...f, instrument: v as 'NIFTY' | 'BANKNIFTY' }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="NIFTY">NIFTY</SelectItem>
                <SelectItem value="BANKNIFTY">BANKNIFTY</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>From Date</Label>
            <Input type="date" value={form.from_date} onChange={(e) => setForm((f) => ({ ...f, from_date: e.target.value }))} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>To Date</Label>
            <Input type="date" value={form.to_date} onChange={(e) => setForm((f) => ({ ...f, to_date: e.target.value }))} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>pts_to_analyse</Label>
            <Input type="number" value={form.pts_to_analyse} onChange={(e) => setForm((f) => ({ ...f, pts_to_analyse: parseInt(e.target.value) || 100 }))} min={25} step={25} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>option_range</Label>
            <Input type="number" value={form.option_range} onChange={(e) => setForm((f) => ({ ...f, option_range: parseInt(e.target.value) || 3 }))} min={1} max={10} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Expiry Count</Label>
            <Input type="number" value={form.expiry_count} onChange={(e) => setForm((f) => ({ ...f, expiry_count: parseInt(e.target.value) || 2 }))} min={1} max={5} />
          </div>
        </div>

        <div className="flex justify-end">
          <Button onClick={handleRun} disabled={mutation.isPending || !form.from_date || !form.to_date}>
            {mutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
            Run
          </Button>
        </div>
      </div>

      {savedQuery.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Loading saved run…
        </div>
      )}

      {savedQuery.isError && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load run: {String(savedQuery.error)}
        </div>
      )}

      {runId && result && (
        <div className="rounded-lg border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Viewing saved run <span className="font-mono text-foreground">{runId}</span> — hit Run to re-run with current settings.
        </div>
      )}

      {mutation.isError && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {String(mutation.error)}
        </div>
      )}

      {/* 5A + 5B */}
      {result && (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="secondary">{result.sessions.length} sessions</Badge>
            <span>Run ID: {result.run_id}</span>
          </div>

          <Tabs defaultValue="5a">
            <TabsList>
              <TabsTrigger value="5a">Trade Table (5A)</TabsTrigger>
              <TabsTrigger value="5b">Summary (5B)</TabsTrigger>
            </TabsList>

            {/* 5A */}
            <TabsContent value="5a">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm text-muted-foreground">{result.sessions.length} overnight sessions</p>
                <ColumnPicker
                  columnMeta={result.column_meta}
                  selected={selectedCols}
                  onToggle={toggleColumn}
                  onSelectAll={() => {}}
                  onDeselectAll={() => {}}
                />
              </div>

              <div className="rounded-lg border overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50">
                    <tr>
                      {mustHaveCols.map((c) => (
                        <th key={c} className="px-3 py-2 text-left font-medium text-muted-foreground whitespace-nowrap">
                          {c.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                        </th>
                      ))}
                      {extraCols.map((k) => (
                        <th key={k} className="px-3 py-2 text-left font-medium text-muted-foreground whitespace-nowrap">
                          {result.column_meta[k]?.label ?? k}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.sessions.map((s, i) => (
                      <tr key={i} className="border-t hover:bg-muted/30 transition-colors">
                        <td className="px-3 py-2 font-mono text-xs">{s.date}</td>
                        <td className="px-3 py-2 font-mono text-xs">{s.entry_time}</td>
                        <td className="px-3 py-2 font-mono text-xs">{s.exit_time}</td>
                        <td className={cn('px-3 py-2 text-right font-mono', s.gap_pts >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                          {formatPts(s.gap_pts)}
                        </td>
                        <td className="px-3 py-2">
                          <Badge variant={s.gap_direction === 'GapUp' ? 'success' : 'destructive'} className="text-xs">
                            {s.gap_direction}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{formatNumber(s.vix, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{formatNumber(s.start_price, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{formatNumber(s.end_price, 1)}</td>
                        {extraCols.map((k) => {
                          const val = s.columns[k];
                          const isPercent = k.includes('percent');
                          return (
                            <td key={k} className="px-3 py-2 text-right font-mono">
                              {isPercent ? formatPercent(val as number | null) : formatNumber(val as number | null)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </TabsContent>

            {/* 5B */}
            <TabsContent value="5b">
              {summary && <SummarySection summary={summary} />}
            </TabsContent>
          </Tabs>
        </div>
      )}
    </div>
  );
}

function SummarySection({ summary }: { summary: ReturnType<typeof computeSummary> }) {
  return (
    <Tabs defaultValue="day">
      <TabsList>
        <TabsTrigger value="day">Day-wise</TabsTrigger>
        <TabsTrigger value="week">Week-wise</TabsTrigger>
        <TabsTrigger value="overall">Overall</TabsTrigger>
      </TabsList>

      <TabsContent value="day">
        <SummaryTable
          rows={summary.dayRows.map((r) => ({ label: r.date, count: r.count, total: r.total, avg: r.avg }))}
          labelHeader="Date"
        />
      </TabsContent>

      <TabsContent value="week">
        <SummaryTable
          rows={summary.weekRows.map((r) => ({ label: r.startDate, count: r.count, total: r.total, avg: r.avg }))}
          labelHeader="Week (Mon)"
        />
      </TabsContent>

      <TabsContent value="overall">
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <tbody>
                <tr className="border-b"><td className="px-4 py-2 font-medium text-muted-foreground">Total Sessions</td><td className="px-4 py-2 text-right font-mono">{summary.overall.count}</td></tr>
                <tr className="border-b"><td className="px-4 py-2 font-medium text-muted-foreground">Total profit %</td><td className="px-4 py-2 text-right font-mono">{formatPercent(summary.overall.total)}</td></tr>
                <tr className="border-b"><td className="px-4 py-2 font-medium text-muted-foreground">Avg profit %</td><td className="px-4 py-2 text-right font-mono">{formatPercent(summary.overall.avg)}</td></tr>
                {summary.best && <tr className="border-b bg-green-500/5"><td className="px-4 py-2 font-medium text-muted-foreground">Best Day</td><td className="px-4 py-2 text-right font-mono">{summary.best.date} ({formatPercent(summary.best.avg)})</td></tr>}
                {summary.worst && <tr className="bg-red-500/5"><td className="px-4 py-2 font-medium text-muted-foreground">Worst Day</td><td className="px-4 py-2 text-right font-mono">{summary.worst.date} ({formatPercent(summary.worst.avg)})</td></tr>}
              </tbody>
            </table>
          </div>

          {/* Gap size breakdown */}
          <div>
            <h3 className="text-sm font-semibold mb-2 text-muted-foreground">Gap Size Breakdown</h3>
            <div className="rounded-lg border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-muted-foreground">Gap Bucket</th>
                    <th className="px-3 py-2 text-right font-medium text-muted-foreground">Session Count</th>
                    <th className="px-3 py-2 text-right font-medium text-muted-foreground">Avg profit%</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.gapBreakdown.map((b) => (
                    <tr key={b.label} className="border-t">
                      <td className="px-3 py-2">{b.label}</td>
                      <td className="px-3 py-2 text-right font-mono">{b.count}</td>
                      <td className="px-3 py-2 text-right font-mono">{b.count > 0 ? formatPercent(b.avg) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </TabsContent>
    </Tabs>
  );
}

function SummaryTable({ rows, labelHeader }: { rows: { label: string; count: number; total: number; avg: number }[]; labelHeader: string }) {
  return (
    <div className="rounded-lg border overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-muted/50">
          <tr>
            <th className="px-3 py-2 text-left font-medium text-muted-foreground">{labelHeader}</th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">Sessions</th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">Total profit%</th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">Avg profit%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-t hover:bg-muted/30">
              <td className="px-3 py-2 font-mono text-xs">{r.label}</td>
              <td className="px-3 py-2 text-right font-mono">{r.count}</td>
              <td className="px-3 py-2 text-right font-mono">{formatPercent(r.total)}</td>
              <td className="px-3 py-2 text-right font-mono">{formatPercent(r.avg)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
