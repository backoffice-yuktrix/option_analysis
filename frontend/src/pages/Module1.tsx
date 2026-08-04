/**
 * /module1 — Intraday Swing Analysis page.
 * Layout per PRD §8.1: Input panel → Chart → 5A Trade Table → 5B Summary
 */
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Play, ChevronDown, ChevronRight, Loader2, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { UpstoxButton } from '@/components/UpstoxButton';
import { ColumnPicker } from '@/components/ColumnPicker';
import { CandlestickChart } from '@/components/CandlestickChart';
import { useModule1 } from '@/hooks/useModule1';
import { getModule1Result } from '@/api/module1';
import type { Module1Request, ATRConfig, LegRow } from '@/api/module1';
import { formatNumber, formatPercent, cn } from '@/lib/utils';

// ── Summary helpers ─────────────────────────────────────────────────────────

function computeSummary(legs: LegRow[]) {
  const byDay: Record<string, LegRow[]> = {};
  for (const leg of legs) {
    if (!byDay[leg.date]) byDay[leg.date] = [];
    byDay[leg.date].push(leg);
  }

  const dayRows = Object.entries(byDay)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, dLegs]) => {
      const values = dLegs.map((l) => (l.columns.profit_percent_optimal_option as number | null) ?? 0);
      const total = values.reduce((s, v) => s + v, 0);
      return { date, count: dLegs.length, total, avg: total / dLegs.length };
    });

  const weekRows: Record<string, { count: number; total: number; startDate: string }> = {};
  for (const leg of legs) {
    const d = new Date(leg.date);
    const day = d.getDay();
    const mon = new Date(d);
    mon.setDate(d.getDate() - (day === 0 ? 6 : day - 1));
    const wk = mon.toISOString().slice(0, 10);
    if (!weekRows[wk]) weekRows[wk] = { count: 0, total: 0, startDate: wk };
    weekRows[wk].count++;
    weekRows[wk].total += (leg.columns.profit_percent_optimal_option as number | null) ?? 0;
  }

  const allValues = legs.map((l) => (l.columns.profit_percent_optimal_option as number | null) ?? 0);
  const totalAll = allValues.reduce((s, v) => s + v, 0);
  const best = dayRows.reduce((b, r) => (r.avg > (b?.avg ?? -Infinity) ? r : b), dayRows[0]);
  const worst = dayRows.reduce((b, r) => (r.avg < (b?.avg ?? Infinity) ? r : b), dayRows[0]);

  return {
    dayRows,
    weekRows: Object.values(weekRows).sort((a, b) => a.startDate.localeCompare(b.startDate)).map((r) => ({
      ...r,
      avg: r.count > 0 ? r.total / r.count : 0,
    })),
    overall: { count: legs.length, total: totalAll, avg: legs.length > 0 ? totalAll / legs.length : 0 },
    best,
    worst,
  };
}

// ── Main component ───────────────────────────────────────────────────────────

export function Module1() {
  const { runId } = useParams<{ runId?: string }>();
  const { result, setLoadedResult, mutation, selectedCols, toggleColumn } = useModule1();
  const [atrOpen, setAtrOpen] = useState(false);
  const [highlightRow, setHighlightRow] = useState<number | null>(null);

  const [form, setForm] = useState<Module1Request>({
    instrument: 'NIFTY',
    from_date: '',
    to_date: '',
    pts_to_analyse: 100,
    option_range: 3,
    expiry_count: 2,
    atr: { period: 14, multiplier: 2.0, candle_tf: '15m', price_source: 'close' },
  });

  // Load saved run when runId is in the URL
  const savedQuery = useQuery({
    queryKey: ['module1-saved', runId],
    queryFn: () => getModule1Result(runId!),
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
      atr: d.atr,
    });
    setLoadedResult(d);
  }, [savedQuery.data, setLoadedResult]);

  function setAtr(patch: Partial<ATRConfig>) {
    setForm((f) => ({ ...f, atr: { ...f.atr, ...patch } }));
  }

  function handleRun() {
    if (!form.from_date || !form.to_date) return;
    mutation.mutate(form);
  }

  const summary = result ? computeSummary(result.legs) : null;
  const mustHaveCols = ['date', 'start_time', 'end_time', 'leg_type', 'vix', 'abs_pts', 'start_price', 'end_price'];
  const extraCols = result ? [...selectedCols].filter((k) => result.column_meta[k]) : [];

  return (
    <div className="flex flex-col gap-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <TrendingUp className="size-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Module 1 — Intraday Swing Analysis</h1>
            <p className="text-sm text-muted-foreground">ATR-based swing detection with time-proportional option checkpoints</p>
          </div>
        </div>
        <UpstoxButton />
      </div>

      {/* Input panel */}
      <div className="rounded-lg border bg-card p-4 flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-6">
          {/* Instrument */}
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

          {/* From Date */}
          <div className="flex flex-col gap-1.5">
            <Label>From Date</Label>
            <Input type="date" value={form.from_date} onChange={(e) => setForm((f) => ({ ...f, from_date: e.target.value }))} />
          </div>

          {/* To Date */}
          <div className="flex flex-col gap-1.5">
            <Label>To Date</Label>
            <Input type="date" value={form.to_date} onChange={(e) => setForm((f) => ({ ...f, to_date: e.target.value }))} />
          </div>

          {/* pts_to_analyse */}
          <div className="flex flex-col gap-1.5">
            <Label>pts_to_analyse</Label>
            <Input type="number" value={form.pts_to_analyse} onChange={(e) => setForm((f) => ({ ...f, pts_to_analyse: parseInt(e.target.value) || 100 }))} min={25} step={25} />
          </div>

          {/* option_range */}
          <div className="flex flex-col gap-1.5">
            <Label>option_range</Label>
            <Input type="number" value={form.option_range} onChange={(e) => setForm((f) => ({ ...f, option_range: parseInt(e.target.value) }))} min={0} max={10} />
          </div>

          {/* expiry_count */}
          <div className="flex flex-col gap-1.5">
            <Label>Expiry Count</Label>
            <Input type="number" value={form.expiry_count} onChange={(e) => setForm((f) => ({ ...f, expiry_count: parseInt(e.target.value) }))} min={0} max={5} />
          </div>
        </div>

        {/* ATR Config — collapsible */}
        <div className="flex flex-col gap-2">
          <button
            type="button"
            className="flex w-fit items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setAtrOpen((o) => !o)}
          >
            {atrOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            ATR Config
          </button>

          {atrOpen && (
            <div className="rounded-md border bg-muted/30 p-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="flex flex-col gap-1.5">
                <Label>ATR Period</Label>
                <Input type="number" value={form.atr.period} onChange={(e) => setAtr({ period: parseInt(e.target.value) || 14 })} min={2} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>ATR Multiplier</Label>
                <Input type="number" value={form.atr.multiplier} onChange={(e) => setAtr({ multiplier: parseFloat(e.target.value) || 2.0 })} step={0.1} min={0.1} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Candle TF</Label>
                <Select value={form.atr.candle_tf} onValueChange={(v) => setAtr({ candle_tf: v as '5m' | '15m' | '30m' })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="5m">5min</SelectItem>
                    <SelectItem value="15m">15min</SelectItem>
                    <SelectItem value="30m">30min</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Price Source</Label>
                <Select value={form.atr.price_source} onValueChange={(v) => setAtr({ price_source: v as 'close' | 'hl' })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="close">Close</SelectItem>
                    <SelectItem value="hl">High/Low</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}
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

      {/* Chart */}
      {result && result.chart_candles.length > 0 && (
        <CandlestickChart
          candles={result.chart_candles}
          swingPoints={result.swing_points}
          legs={result.legs}
          nonQualifyingLegs={result.non_qualifying_legs}
          onLegClick={(i) => {
            setHighlightRow(i);
            // Scroll the 5A table row into view (PRD §4.5)
            setTimeout(() => {
              document.getElementById(`leg-row-${i}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 50);
          }}
        />
      )}

      {/* 5A Table + 5B Summary */}
      {result && (
        <div className="flex flex-col gap-4">
          {/* Run info badge */}
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="secondary">{result.legs.length} legs</Badge>
            <span>Run ID: {result.run_id}</span>
          </div>

          <Tabs defaultValue="5a">
            <TabsList>
              <TabsTrigger value="5a">Trade Table (5A)</TabsTrigger>
              <TabsTrigger value="5b">Summary (5B)</TabsTrigger>
            </TabsList>

            {/* 5A — Trade Table */}
            <TabsContent value="5a">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm text-muted-foreground">{result.legs.length} qualifying legs</p>
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
                    {result.legs.map((leg, i) => (
                      <tr
                        key={i}
                        id={`leg-row-${i}`}
                        className={cn(
                          'border-t hover:bg-muted/30 transition-colors cursor-default',
                          highlightRow === i && 'bg-primary/10',
                        )}
                      >
                        <td className="px-3 py-2 font-mono text-xs">{leg.date}</td>
                        <td className="px-3 py-2 font-mono text-xs">{leg.start_time}</td>
                        <td className="px-3 py-2 font-mono text-xs">{leg.end_time}</td>
                        <td className="px-3 py-2">
                          <Badge variant={leg.leg_type === 'Hill' ? 'success' : 'destructive'} className="text-xs">
                            {leg.leg_type}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{formatNumber(leg.vix, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{formatNumber(leg.abs_pts, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{formatNumber(leg.start_price, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{formatNumber(leg.end_price, 1)}</td>
                        {extraCols.map((k) => {
                          const val = leg.columns[k];
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

            {/* 5B — Summary */}
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
          rows={summary.dayRows.map((r) => ({
            label: r.date,
            count: r.count,
            total: r.total,
            avg: r.avg,
          }))}
          labelHeader="Date"
        />
      </TabsContent>

      <TabsContent value="week">
        <SummaryTable
          rows={summary.weekRows.map((r) => ({
            label: r.startDate,
            count: r.count,
            total: r.total,
            avg: r.avg,
          }))}
          labelHeader="Week (Mon)"
        />
      </TabsContent>

      <TabsContent value="overall">
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <tbody>
              <tr className="border-b">
                <td className="px-4 py-2 font-medium text-muted-foreground">Total Trades</td>
                <td className="px-4 py-2 font-mono text-right">{summary.overall.count}</td>
              </tr>
              <tr className="border-b">
                <td className="px-4 py-2 font-medium text-muted-foreground">Total profit %</td>
                <td className="px-4 py-2 font-mono text-right">{formatPercent(summary.overall.total)}</td>
              </tr>
              <tr className="border-b">
                <td className="px-4 py-2 font-medium text-muted-foreground">Avg profit %</td>
                <td className="px-4 py-2 font-mono text-right">{formatPercent(summary.overall.avg)}</td>
              </tr>
              {summary.best && (
                <tr className="border-b bg-green-500/5">
                  <td className="px-4 py-2 font-medium text-muted-foreground">Best Day</td>
                  <td className="px-4 py-2 font-mono text-right">{summary.best.date} ({formatPercent(summary.best.avg)} avg)</td>
                </tr>
              )}
              {summary.worst && (
                <tr className="bg-red-500/5">
                  <td className="px-4 py-2 font-medium text-muted-foreground">Worst Day</td>
                  <td className="px-4 py-2 font-mono text-right">{summary.worst.date} ({formatPercent(summary.worst.avg)} avg)</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </TabsContent>
    </Tabs>
  );
}

function SummaryTable({
  rows,
  labelHeader,
}: {
  rows: { label: string; count: number; total: number; avg: number }[];
  labelHeader: string;
}) {
  return (
    <div className="rounded-lg border overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-muted/50">
          <tr>
            <th className="px-3 py-2 text-left font-medium text-muted-foreground">{labelHeader}</th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">Total Trades</th>
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
