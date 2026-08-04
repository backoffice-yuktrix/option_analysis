/**
 * Candlestick chart using lightweight-charts v5.
 * Overlays per PRD §4.5:
 *   - Hill swing points: downward triangle marker (▼) above candle high
 *   - Valley swing points: upward triangle marker (▲) below candle low
 *   - Qualifying legs (≥ pts_to_analyse): green (up) / red (down) connector lines
 *   - Non-qualifying legs (< pts_to_analyse): grey connector lines
 *   - Clicking a leg connector scrolls to + highlights its row in the 5A table
 */
import { useEffect, useRef } from 'react';
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  ColorType,
  LineSeries,
  TickMarkType,
  type IChartApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { ChartCandle, SwingPoint, LegRow, NonQualifyingLeg } from '@/api/module1';

// ---------------------------------------------------------------------------
// Theme helpers
// ---------------------------------------------------------------------------

const _colorCanvas = document.createElement('canvas');
_colorCanvas.width = _colorCanvas.height = 1;
const _colorCtx = _colorCanvas.getContext('2d')!;

function _cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function _toRgb(value: string, fallback: string): string {
  if (!value) return fallback;
  if (value.startsWith('#') || value.startsWith('rgb')) return value;
  try {
    _colorCtx.clearRect(0, 0, 1, 1);
    _colorCtx.fillStyle = value;
    _colorCtx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = _colorCtx.getImageData(0, 0, 1, 1).data;
    return a === 0 ? fallback : `rgb(${r},${g},${b})`;
  } catch {
    return fallback;
  }
}

function chartTheme() {
  return {
    bg:   _toRgb(_cssVar('--card'),           '#18181b'),
    text: _toRgb(_cssVar('--card-foreground'), '#e4e4e7'),
    grid: _toRgb(_cssVar('--border'),          '#27272a'),
  };
}

// ---------------------------------------------------------------------------
// IST formatters
// ---------------------------------------------------------------------------

const _IST = { timeZone: 'Asia/Kolkata' } as const;

function tickMarkFormatterIST(utcSeconds: number, type: TickMarkType): string {
  const d = new Date(utcSeconds * 1000);
  if (type === TickMarkType.Year)
    return d.toLocaleDateString('en-IN', { ..._IST, year: 'numeric' });
  if (type === TickMarkType.Month || type === TickMarkType.DayOfMonth)
    return d.toLocaleDateString('en-IN', { ..._IST, day: '2-digit', month: 'short' });
  return d.toLocaleTimeString('en-IN', { ..._IST, hour: '2-digit', minute: '2-digit' });
}

function timeFormatterIST(utcSeconds: number): string {
  return new Date(utcSeconds * 1000).toLocaleString('en-IN', {
    ..._IST, hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short',
  });
}

// ---------------------------------------------------------------------------
// Timestamp helper
// ---------------------------------------------------------------------------

function tsToUnix(ts: string): UTCTimestamp {
  return Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface CandlestickChartProps {
  candles: ChartCandle[];
  swingPoints: SwingPoint[];
  legs: LegRow[];
  nonQualifyingLegs: NonQualifyingLeg[];
  onLegClick?: (legIndex: number) => void;
}

export function CandlestickChart({ candles, swingPoints, legs, nonQualifyingLegs, onLegClick }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || !candles.length) return;

    const { bg, text, grid } = chartTheme();

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: bg },
        textColor: text,
      },
      grid: {
        vertLines: { color: grid },
        horzLines: { color: grid },
      },
      localization: { timeFormatter: timeFormatterIST },
      timeScale: {
        borderColor: grid,
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: tickMarkFormatterIST,
      },
      rightPriceScale: { borderColor: grid },
    });
    chartRef.current = chart;

    // Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#0dc789',
      downColor: '#cf1644',
      borderVisible: false,
      wickUpColor: '#0dc789',
      wickDownColor: '#cf1644',
      priceLineVisible: false,
    });

    const chartData = candles
      .map((c) => ({
        time: tsToUnix(c.timestamp),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
      .sort((a, b) => a.time - b.time);

    candleSeries.setData(chartData);

    const candleByTs = new Map<number, ChartCandle>();
    for (const c of candles) {
      candleByTs.set(tsToUnix(c.timestamp), c);
    }

    // Swing point markers
    const markers = swingPoints
      .map((sp) => {
        const unix = tsToUnix(sp.timestamp);
        if (!candleByTs.has(unix)) return null;
        return {
          time: unix,
          position: sp.swing_type === 'Hill' ? ('aboveBar' as const) : ('belowBar' as const),
          color: sp.swing_type === 'Hill' ? '#ef4444' : '#22c55e',
          shape: sp.swing_type === 'Hill' ? ('arrowDown' as const) : ('arrowUp' as const),
          size: 1,
        };
      })
      .filter(Boolean) as Parameters<typeof createSeriesMarkers>[1];

    createSeriesMarkers(candleSeries, markers);

    // Non-qualifying legs — grey connectors (PRD §4.5)
    nonQualifyingLegs.forEach((leg) => {
      const t0 = tsToUnix(`${leg.date}T${leg.start_time}:00`);
      const t1 = tsToUnix(`${leg.end_date}T${leg.end_time}:00`);
      if (t0 === t1) return; // zero-length leg — nothing to draw
      const lineSeries = chart.addSeries(LineSeries, {
        color: '#71717a',
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      const points = (
        t0 < t1
          ? [{ time: t0, value: leg.start_price }, { time: t1, value: leg.end_price }]
          : [{ time: t1, value: leg.end_price }, { time: t0, value: leg.start_price }]
      ) as { time: UTCTimestamp; value: number }[];
      lineSeries.setData(points);
    });

    // Qualifying leg connector lines — green (up) / red (down)
    // Build a map of leg time ranges for click detection
    const legRanges: { t0: number; t1: number; idx: number }[] = [];
    legs.forEach((leg, idx) => {
      const t0 = tsToUnix(`${leg.date}T${leg.start_time}:00`);
      const t1 = tsToUnix(`${leg.end_date}T${leg.end_time}:00`);
      if (t0 === t1) return; // zero-length leg — skip drawing but still register for click
      const color = leg.leg_type === 'Hill' ? '#0dc789' : '#cf1644';

      const lineSeries = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
      });

      const points = (
        t0 < t1
          ? [{ time: t0, value: leg.start_price }, { time: t1, value: leg.end_price }]
          : [{ time: t1, value: leg.end_price }, { time: t0, value: leg.start_price }]
      ) as { time: UTCTimestamp; value: number }[];

      lineSeries.setData(points);
      legRanges.push({ t0: Math.min(t0, t1), t1: Math.max(t0, t1), idx });
    });

    // Chart click → find which qualifying leg was clicked, invoke onLegClick (PRD §4.5)
    if (onLegClick) {
      chart.subscribeClick((param) => {
        if (!param.time) return;
        const clickedTime = param.time as number;
        for (const { t0, t1, idx } of legRanges) {
          if (clickedTime >= t0 && clickedTime <= t1) {
            onLegClick(idx);
            break;
          }
        }
      });
    }

    // Theme sync on dark/light toggle
    const mo = new MutationObserver(() => {
      setTimeout(() => {
        if (!chartRef.current) return;
        const { bg: bg2, text: text2, grid: grid2 } = chartTheme();
        chartRef.current.applyOptions({
          layout: { background: { color: bg2 }, textColor: text2 },
          grid: { vertLines: { color: grid2 }, horzLines: { color: grid2 } },
          timeScale: { borderColor: grid2 },
          rightPriceScale: { borderColor: grid2 },
        });
      }, 500);
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      mo.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, swingPoints, legs, nonQualifyingLegs, onLegClick]);

  return (
    <div className="rounded-lg border bg-card">
      <div className="px-4 py-3 border-b text-sm font-medium text-muted-foreground">
        Instrument Chart — swing points &amp; qualifying legs
      </div>
      <div ref={containerRef} className="w-full" style={{ minHeight: 360 }} />
    </div>
  );
}
