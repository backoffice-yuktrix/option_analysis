import { useCallback, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { runModule1, type Module1Request, type Module1Result } from '@/api/module1';
import { extractError } from '@/api/client';

const DEFAULT_COLS = new Set([
  'instr_20pct',
  'instr_80pct',
  'profit_percent_optimal_option',
]);

export function useModule1() {
  const [result, setResult] = useState<Module1Result | null>(null);
  const [selectedCols, setSelectedCols] = useState<Set<string>>(DEFAULT_COLS);

  const mutation = useMutation({
    mutationFn: (req: Module1Request) => runModule1(req),
    onSuccess: (data) => {
      setResult(data);
      // Auto-select default columns based on result
      const defaults = buildDefaultColumns(data);
      setSelectedCols(defaults);
      toast.success(`Run complete — ${data.legs.length} qualifying legs found`);
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

  const setLoadedResult = useCallback((data: Module1Result) => {
    setResult(data);
    setSelectedCols(buildDefaultColumns(data));
  }, []);

  return { result, setLoadedResult, mutation, selectedCols, toggleColumn };
}

function buildDefaultColumns(result: Module1Result): Set<string> {
  const cols = new Set<string>(['instr_20pct', 'instr_80pct', 'profit_percent_optimal_option']);
  // Default expiry: 2nd if expiry_count >= 2, else 1st (PRD §3.2)
  const defaultExpN = result.expiry_count >= 2 ? 2 : 1;
  for (const pct of [0, 20, 80, 100]) {
    const key = `along_exp${defaultExpN}_cheapest_${pct}pct`;
    if (result.column_meta[key]) cols.add(key);
  }
  return cols;
}
