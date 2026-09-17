import React, { useState } from 'react';
import { Sparkles, Brain, CheckSquare, Square, ArrowUpDown, UploadCloud, FileText, RefreshCw, AlertCircle } from 'lucide-react';
import { DeepSearchResultItem } from '../types';

interface DeepSearchProps {
  results: DeepSearchResultItem[];
  isLoading: boolean;
  onSendToAI: (selectedItems: DeepSearchResultItem[]) => void;
  onMountSymbols: (symbols: string[]) => void;
  onOpenChangelog: (symbol?: string) => void;
  isAiProcessing: boolean;
}

export const DeepSearch: React.FC<DeepSearchProps> = ({
  results,
  isLoading,
  onSendToAI,
  onMountSymbols,
  onOpenChangelog,
  isAiProcessing
}) => {
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set());
  const [sortField, setSortField] = useState<keyof DeepSearchResultItem>('score');
  const [sortAsc, setSortAsc] = useState<boolean>(false);
  const [filterText, setFilterText] = useState<string>('');

  const toggleSelect = (sym: string) => {
    const next = new Set(selectedSymbols);
    if (next.has(sym)) {
      next.delete(sym);
    } else {
      next.add(sym);
    }
    setSelectedSymbols(next);
  };

  const handleSelectAll = () => {
    if (selectedSymbols.size === filteredAndSorted.length) {
      setSelectedSymbols(new Set());
    } else {
      setSelectedSymbols(new Set(filteredAndSorted.map(r => r.symbol)));
    }
  };

  const handleSelectTop5 = () => {
    const top5 = filteredAndSorted.slice(0, 5).map(r => r.symbol);
    setSelectedSymbols(new Set(top5));
  };

  const handleSort = (field: keyof DeepSearchResultItem) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  };

  const filteredAndSorted = [...results]
    .filter(item => item.symbol.toLowerCase().includes(filterText.toLowerCase()))
    .sort((a, b) => {
      const valA = a[sortField] ?? 0;
      const valB = b[sortField] ?? 0;
      if (typeof valA === 'string' && typeof valB === 'string') {
        return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }
      return sortAsc ? Number(valA) - Number(valB) : Number(valB) - Number(valA);
    });

  const selectedItems = results.filter(r => selectedSymbols.has(r.symbol));

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full">
      {/* Top Controls Bar */}
      <div className="p-4 border-b border-slate-800 bg-slate-900/90 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Brain className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-100 flex items-center gap-2">
              Explorador Deep Search & Optimización
              <span className="text-[11px] font-normal px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                {results.length} Pares Auditados
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              Evaluación multitemporal cuantitativa con cálculo vectorial de R-Múltiplo, Win Rate y Drawdown.
            </p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            placeholder="Filtrar por par (ej: EURUSD)..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-44"
          />

          <button
            onClick={handleSelectTop5}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 transition-colors"
          >
            Top 5 Score
          </button>

          <button
            onClick={() => onMountSymbols(Array.from(selectedSymbols))}
            disabled={selectedSymbols.size === 0}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
          >
            <UploadCloud className="w-3.5 h-3.5" />
            Montar ({selectedSymbols.size})
          </button>

          <button
            onClick={() => onSendToAI(selectedItems)}
            disabled={selectedSymbols.size === 0 || isAiProcessing}
            className="text-xs font-semibold px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white shadow-md shadow-purple-600/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5"
          >
            {isAiProcessing ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Aprendiendo...
              </>
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5" />
                Enviar a IA ({selectedSymbols.size})
              </>
            )}
          </button>

          <button
            onClick={() => onOpenChangelog()}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 transition-colors flex items-center gap-1.5"
          >
            <FileText className="w-3.5 h-3.5 text-purple-400" />
            MR Changelog
          </button>
        </div>
      </div>

      {/* Table Content */}
      <div className="overflow-x-auto flex-1 max-h-[480px]">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800 sticky top-0 z-10 select-none">
            <tr>
              <th className="p-3 w-10 text-center">
                <button onClick={handleSelectAll} className="hover:text-slate-200">
                  {selectedSymbols.size === filteredAndSorted.length && filteredAndSorted.length > 0 ? (
                    <CheckSquare className="w-4 h-4 text-indigo-400" />
                  ) : (
                    <Square className="w-4 h-4" />
                  )}
                </button>
              </th>
              <th className="p-3 cursor-pointer hover:text-slate-200" onClick={() => handleSort('symbol')}>
                <div className="flex items-center gap-1">
                  Par / Símbolo
                  <ArrowUpDown className="w-3 h-3" />
                </div>
              </th>
              <th className="p-3 cursor-pointer hover:text-slate-200" onClick={() => handleSort('timeframe')}>
                TF
              </th>
              <th className="p-3 cursor-pointer hover:text-slate-200" onClick={() => handleSort('trades_count')}>
                <div className="flex items-center gap-1">
                  Trades
                  <ArrowUpDown className="w-3 h-3" />
                </div>
              </th>
              <th className="p-3 cursor-pointer hover:text-slate-200" onClick={() => handleSort('win_rate')}>
                <div className="flex items-center gap-1">
                  Win Rate
                  <ArrowUpDown className="w-3 h-3" />
                </div>
              </th>
              <th className="p-3 cursor-pointer hover:text-slate-200" onClick={() => handleSort('avg_r_multiple')}>
                <div className="flex items-center gap-1">
                  Avg R
                  <ArrowUpDown className="w-3 h-3" />
                </div>
              </th>
              <th className="p-3 cursor-pointer hover:text-slate-200" onClick={() => handleSort('profit_factor')}>
                <div className="flex items-center gap-1">
                  Profit Factor
                  <ArrowUpDown className="w-3 h-3" />
                </div>
              </th>
              <th className="p-3 cursor-pointer hover:text-slate-200" onClick={() => handleSort('max_drawdown_pct')}>
                <div className="flex items-center gap-1">
                  Max DD
                  <ArrowUpDown className="w-3 h-3" />
                </div>
              </th>
              <th className="p-3 cursor-pointer hover:text-slate-200" onClick={() => handleSort('score')}>
                <div className="flex items-center gap-1">
                  Score Total
                  <ArrowUpDown className="w-3 h-3" />
                </div>
              </th>
              <th className="p-3 text-right">Acción</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {filteredAndSorted.length === 0 ? (
              <tr>
                <td colSpan={10} className="p-8 text-center text-slate-500">
                  <AlertCircle className="w-6 h-6 mx-auto mb-2 text-slate-600" />
                  No hay resultados de backtesting disponibles aún.
                </td>
              </tr>
            ) : (
              filteredAndSorted.map((item) => {
                const isSelected = selectedSymbols.has(item.symbol);
                const wrColor = item.win_rate >= 55 ? 'text-emerald-400' : item.win_rate >= 45 ? 'text-amber-400' : 'text-rose-400';
                const rColor = item.avg_r_multiple >= 0.2 ? 'text-emerald-400' : item.avg_r_multiple >= 0 ? 'text-slate-300' : 'text-rose-400';

                return (
                  <tr
                    key={`${item.symbol}-${item.timeframe}`}
                    onClick={() => toggleSelect(item.symbol)}
                    className={`cursor-pointer transition-colors ${
                      isSelected ? 'bg-indigo-950/30 hover:bg-indigo-950/40' : 'hover:bg-slate-800/40'
                    }`}
                  >
                    <td className="p-3 text-center" onClick={(e) => e.stopPropagation()}>
                      <button onClick={() => toggleSelect(item.symbol)} className="text-slate-400 hover:text-slate-200">
                        {isSelected ? (
                          <CheckSquare className="w-4 h-4 text-indigo-400" />
                        ) : (
                          <Square className="w-4 h-4" />
                        )}
                      </button>
                    </td>
                    <td className="p-3 font-bold text-slate-100 flex items-center gap-1.5">
                      {item.symbol}
                      <span className="text-[10px] font-normal px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                        {item.strategy || 'ai_strategy'}
                      </span>
                    </td>
                    <td className="p-3 text-slate-300 font-mono">{item.timeframe || 'M15'}</td>
                    <td className="p-3 text-slate-300">{item.trades_count}</td>
                    <td className={`p-3 font-bold ${wrColor}`}>{item.win_rate.toFixed(1)}%</td>
                    <td className={`p-3 font-bold ${rColor}`}>{item.avg_r_multiple > 0 ? `+${item.avg_r_multiple.toFixed(2)}` : item.avg_r_multiple.toFixed(2)}R</td>
                    <td className="p-3 text-slate-300 font-medium">
                      {item.profit_factor >= 999 ? '∞' : item.profit_factor.toFixed(2)}
                    </td>
                    <td className="p-3 text-rose-400">{item.max_drawdown_pct.toFixed(1)}%</td>
                    <td className="p-3">
                      <span className="px-2 py-0.5 rounded font-bold text-indigo-300 bg-indigo-500/10 border border-indigo-500/20">
                        {item.score.toFixed(1)}
                      </span>
                    </td>
                    <td className="p-3 text-right" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => onOpenChangelog(item.symbol)}
                        className="text-[11px] font-medium text-slate-400 hover:text-purple-400 hover:underline transition-colors"
                      >
                        Ver MR
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
