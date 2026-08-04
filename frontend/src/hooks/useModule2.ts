import { useCallback, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { runModule2, type Module2Request, type Module2Result } from '@/api/module2';
import { extractError } from '@/api/client';

const DEFAULT_COLS = new Set([
  'profit_percent_optimal_option',
]);

export function useModule2() {
  const [result, setResult] = useState<Module2Result | null>(null);
  const [selectedCols, setSelectedCols] = useState<Set<string>>(DEFAULT_COLS);

  const mutation = useMutation({
    mutationFn: (req: Module2Request) => runModule2(req),
    onSuccess: (data) => {
      setResult(data);
      const defaults = buildDefaultColumns(data);
      setSelectedCols(defaults);
      toast.success(`Run complete — ${data.sessions.length} overnight sessions`);
    },
    onError: (err) => toast.error(`Run failed: ${extractError(err)}`),
  });

  function toggleColumn(key: string) {
    setSelectedCols((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const setLoadedResult = useCallback((data: Module2Result) => {
    setResult(data);
    setSelectedCols(buildDefaultColumns(data));
  }, []);

  return { result, setLoadedResult, mutation, selectedCols, toggleColumn };
}

function buildDefaultColumns(result: Module2Result): Set<string> {
  const cols = new Set<string>(['profit_percent_optimal_option']);
  // Default expiry: 2nd if expiry_count >= 2, else 1st (PRD §3.2)
  const defaultExpN = result.expiry_count >= 2 ? 2 : 1;
  for (const pct of [0, 100]) {
    const key = `along_exp${defaultExpN}_cheapest_${pct}pct`;
    if (result.column_meta[key]) cols.add(key);
  }
  const dteKey = `dte_exp${defaultExpN}`;
  if (result.column_meta[dteKey]) cols.add(dteKey);
  return cols;
}
