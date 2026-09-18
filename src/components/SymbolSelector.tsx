import React, { useState } from 'react';
import {
  Sparkles,
  Search,
  Plus,
  Trash2,
  Clock,
  Zap,
  BarChart3,
  CheckCircle2,
  XCircle,
  Save,
  Check,
  AlertCircle
} from 'lucide-react';
import { SymbolMetadata, BestPerSymbolItem } from '../types';
import { AutocompleteInput } from './AutocompleteInput';

interface SymbolSelectorProps {
  symbolsMetadata: Record<string, SymbolMetadata>;
  availableSymbols: string[];
  activeSymbols: string[];
  accountBalance: number;
  onUpdateActiveSymbols: (symbols: string[]) => void;
  onUpdateSymbolSetting: (
    symbol: string,
    setting: 'lot' | 'risk_pct' | 'timeframe' | 'strategy',
    value: any
  ) => void;
  onOpenDeepSearch: () => void;
  onSaveConfig?: () => void;
}

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'];
const STRATEGIES = ['simple_trend', 'forex', 'syntx', 'ai_strategy'];

export const SymbolSelector: React.FC<SymbolSelectorProps> = ({
  symbolsMetadata,
  availableSymbols,
  activeSymbols,
  accountBalance,
  onUpdateActiveSymbols,
  onUpdateSymbolSetting,
  onOpenDeepSearch,
  onSaveConfig,
}) => {
  const [newSymbolInput, setNewSymbolInput] = useState<string>('');
  const [searchTableQuery, setSearchTableQuery] = useState<string>('');
  const [saveFeedback, setSaveFeedback] = useState<string | null>(null);

  // Add a symbol from input / autocomplete
  const handleAddSymbol = (symToAdd?: string) => {
    const raw = (symToAdd || newSymbolInput).trim();
    if (!raw) return;

    // Look for case-insensitive match in availableSymbols
    const matched = availableSymbols.find((s) => s.toLowerCase() === raw.toLowerCase()) || raw;

    if (!activeSymbols.includes(matched)) {
      const updated = [...activeSymbols, matched];
      onUpdateActiveSymbols(updated);
    }
    setNewSymbolInput('');
  };

  // Remove a symbol
  const handleRemoveSymbol = (sym: string) => {
    const updated = activeSymbols.filter((s) => s !== sym);
    onUpdateActiveSymbols(updated);
  };

  // Toggle active state for symbol
  const handleToggleSymbol = (sym: string) => {
    if (activeSymbols.includes(sym)) {
      onUpdateActiveSymbols(activeSymbols.filter((s) => s !== sym));
    } else {
      onUpdateActiveSymbols([...activeSymbols, sym]);
    }
  };

  // Quick batch actions
  const handleActivateAll = () => {
    onUpdateActiveSymbols([...availableSymbols]);
  };

  const handleDeactivateAll = () => {
    onUpdateActiveSymbols([]);
  };

  const handleApplySuggestedAll = () => {
    activeSymbols.forEach((sym) => {
      const meta = symbolsMetadata[sym];
      if (meta?.suggested_timeframe) {
        onUpdateSymbolSetting(sym, 'timeframe', meta.suggested_timeframe.timeframe_str);
        if (meta.suggested_timeframe.strategy) {
          onUpdateSymbolSetting(sym, 'strategy', meta.suggested_timeframe.strategy);
        }
      }
    });
    setSaveFeedback('Sugerencias de Deep Search aplicadas a todos los pares');
    setTimeout(() => setSaveFeedback(null), 3000);
  };

  const handleTriggerSave = () => {
    if (onSaveConfig) {
      onSaveConfig();
      setSaveFeedback('Configuración guardada en config.json');
      setTimeout(() => setSaveFeedback(null), 3000);
    }
  };

  // Table items: all symbols currently active, optionally filtered by table search
  const displayedSymbols = activeSymbols.filter((sym) => {
    if (!searchTableQuery.trim()) return true;
    return sym.toLowerCase().includes(searchTableQuery.toLowerCase());
  });

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col h-full text-slate-100">
      {/* Header */}
      <div className="p-4 border-b border-slate-800 bg-slate-950 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20">
            <Zap className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-100 flex items-center gap-2">
              🎯 Selección de Símbolos y Configuración por Par
              <span className="text-[11px] font-normal px-2 py-0.5 rounded-full bg-slate-800 text-sky-300 border border-slate-700 font-mono">
                {activeSymbols.length} / {availableSymbols.length} Pares Activos
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              Ajusta lotes, riesgo porcentual, estrategias y timeframes óptimos con sugerencias cuantitativas.
            </p>
          </div>
        </div>

        {/* Top Action Buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={onOpenDeepSearch}
            className="px-3 py-1.5 rounded-lg bg-sky-950/80 hover:bg-sky-800 text-sky-300 border border-sky-700/60 text-xs font-bold transition-all shadow-xs flex items-center gap-1.5"
          >
            <BarChart3 className="w-3.5 h-3.5 text-sky-400" />
            <span>📊 Abrir Deep Search</span>
          </button>

          <button
            type="button"
            onClick={handleApplySuggestedAll}
            className="px-3 py-1.5 rounded-lg bg-purple-950/80 hover:bg-purple-800 text-purple-200 border border-purple-700/60 text-xs font-bold transition-all shadow-xs flex items-center gap-1.5"
          >
            <Sparkles className="w-3.5 h-3.5 text-purple-400" />
            <span>⚡ Aplicar Sugeridos</span>
          </button>

          <button
            type="button"
            onClick={handleTriggerSave}
            className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition-all shadow-md shadow-emerald-600/20 flex items-center gap-1.5"
          >
            <Save className="w-3.5 h-3.5" />
            <span>💾 Guardar Cambios</span>
          </button>
        </div>
      </div>

      {/* Notification feedback banner */}
      {saveFeedback && (
        <div className="px-4 py-2 bg-emerald-950/90 border-b border-emerald-800 text-emerald-300 text-xs flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>{saveFeedback}</span>
        </div>
      )}

      {/* Autocomplete Add & Filter Bar */}
      <div className="p-3.5 bg-slate-900/60 border-b border-slate-800 flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3">
        {/* Símbolo Search & Autocomplete */}
        <div className="flex items-center gap-2 flex-1 max-w-xl">
          <div className="flex-1">
            <AutocompleteInput
              id="symbol-selector-autocomplete"
              value={newSymbolInput}
              onChange={setNewSymbolInput}
              onSelectSymbol={(sym) => handleAddSymbol(sym)}
              symbolsMetadata={symbolsMetadata}
              availableSymbols={availableSymbols}
              activeSymbols={activeSymbols}
              excludeActive={false}
              placeholder="Añadir símbolo (ej. EURUSD, GBPJPY, XAUUSD)..."
              compact={false}
            />
          </div>
          <button
            type="button"
            onClick={() => handleAddSymbol()}
            disabled={!newSymbolInput.trim()}
            className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold transition-all shadow-xs flex items-center gap-1 shrink-0"
          >
            <Plus className="w-4 h-4" />
            <span>Añadir</span>
          </button>
        </div>

        {/* Filter table */}
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
            <input
              type="text"
              placeholder="Filtrar activos..."
              value={searchTableQuery}
              onChange={(e) => setSearchTableQuery(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-hidden focus:border-sky-500 font-mono w-40"
            />
          </div>
        </div>
      </div>

      {/* Active Symbols Table */}
      <div className="overflow-x-auto flex-1 max-h-[500px]">
        <table className="w-full text-left text-xs border-collapse">
          <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 sticky top-0 z-10 font-mono select-none">
            <tr>
              <th className="p-2.5 w-12 text-center">Activo</th>
              <th className="p-2.5">Símbolo</th>
              <th className="p-2.5 w-24">Lote</th>
              <th className="p-2.5 w-36">Riesgo % ($)</th>
              <th className="p-2.5">Timeframe</th>
              <th className="p-2.5">Estrategia</th>
              <th className="p-2.5">Horario Sesión</th>
              <th className="p-2.5 w-12 text-center">Eliminar</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {displayedSymbols.length === 0 ? (
              <tr>
                <td colSpan={8} className="p-8 text-center text-slate-500 font-sans">
                  <AlertCircle className="w-6 h-6 mx-auto mb-2 text-slate-600" />
                  No hay pares en la lista activa. Usa el buscador superior para añadir pares o monta desde Deep Search.
                </td>
              </tr>
            ) : (
              displayedSymbols.map((sym) => {
                const meta = symbolsMetadata[sym];
                const lot = meta?.lot ?? 0.01;
                const riskPct = meta?.risk_pct ?? 1.0;
                const currentTf = meta?.timeframe ?? 'M15';
                const currentStrat = meta?.strategy ?? 'simple_trend';
                const session = meta?.session;
                const sugg = meta?.suggested_timeframe;

                // Calculate USD risk amount
                const riskUsd = ((accountBalance * riskPct) / 100).toFixed(2);

                return (
                  <tr key={sym} className="hover:bg-slate-800/40 transition-colors">
                    {/* Switch Toggle Activo */}
                    <td className="p-2.5 text-center">
                      <button
                        type="button"
                        onClick={() => handleToggleSymbol(sym)}
                        className={`w-8 h-4.5 rounded-full transition-colors relative inline-flex items-center ${
                          meta?.isActive !== false ? 'bg-emerald-600' : 'bg-slate-700'
                        }`}
                      >
                        <span
                          className={`w-3.5 h-3.5 rounded-full bg-white transition-transform ${
                            meta?.isActive !== false ? 'translate-x-4' : 'translate-x-0.5'
                          }`}
                        />
                      </button>
                    </td>

                    {/* Símbolo */}
                    <td className="p-2.5 font-bold text-slate-100 flex items-center gap-2">
                      <span className="tracking-wide text-sm">{sym}</span>
                      {meta?.category && (
                        <span className="text-[10px] font-normal px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 border border-slate-700/80">
                          {meta.category}
                        </span>
                      )}
                    </td>

                    {/* Lote */}
                    <td className="p-2.5">
                      <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        max="100"
                        value={lot}
                        onChange={(e) => onUpdateSymbolSetting(sym, 'lot', parseFloat(e.target.value) || 0.01)}
                        className="w-20 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-hidden focus:border-sky-500 font-mono text-right"
                      />
                    </td>

                    {/* Riesgo % y USD */}
                    <td className="p-2.5">
                      <div className="flex items-center gap-1.5">
                        <input
                          type="number"
                          step="0.1"
                          min="0.1"
                          max="10"
                          value={riskPct}
                          onChange={(e) => onUpdateSymbolSetting(sym, 'risk_pct', parseFloat(e.target.value) || 1.0)}
                          className="w-14 bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-slate-200 focus:outline-hidden focus:border-sky-500 font-mono text-right"
                        />
                        <span className="text-slate-400 text-xs">%</span>
                        <span className="text-[10px] text-emerald-400/90 font-mono">(${riskUsd})</span>
                      </div>
                    </td>

                    {/* Timeframe + Sugerido Badge */}
                    <td className="p-2.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <select
                          value={currentTf}
                          onChange={(e) => onUpdateSymbolSetting(sym, 'timeframe', e.target.value)}
                          className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-sky-300 font-bold focus:outline-hidden focus:border-sky-500"
                        >
                          {TIMEFRAMES.map((tf) => (
                            <option key={tf} value={tf}>
                              {tf}
                            </option>
                          ))}
                        </select>

                        {/* Clickable Suggested Timeframe Pill */}
                        {sugg && (
                          <button
                            type="button"
                            onClick={() => onUpdateSymbolSetting(sym, 'timeframe', sugg.timeframe_str)}
                            title="Haz clic para aplicar el timeframe sugerido por Deep Search"
                            className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-purple-950/80 hover:bg-purple-800 text-purple-300 border border-purple-700/60 transition-colors flex items-center gap-1"
                          >
                            <Sparkles className="w-2.5 h-2.5 text-purple-400" />
                            <span>
                              {sugg.timeframe_str} ({sugg.avg_r >= 0 ? `+${sugg.avg_r.toFixed(1)}` : sugg.avg_r.toFixed(1)}R)
                            </span>
                          </button>
                        )}
                      </div>
                    </td>

                    {/* Estrategia + Sugerido Badge */}
                    <td className="p-2.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <select
                          value={currentStrat}
                          onChange={(e) => onUpdateSymbolSetting(sym, 'strategy', e.target.value)}
                          className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-amber-300 font-semibold focus:outline-hidden focus:border-amber-500"
                        >
                          {STRATEGIES.map((st) => (
                            <option key={st} value={st}>
                              {st}
                            </option>
                          ))}
                        </select>

                        {sugg?.strategy && (
                          <button
                            type="button"
                            onClick={() => onUpdateSymbolSetting(sym, 'strategy', sugg.strategy)}
                            title="Haz clic para aplicar la mejor estrategia detectada"
                            className="text-[10px] font-semibold px-1.5 py-0.5 rounded-md bg-amber-950/60 hover:bg-amber-800 text-amber-300 border border-amber-800/50 transition-colors"
                          >
                            ⚡ {sugg.strategy}
                          </button>
                        )}
                      </div>
                    </td>

                    {/* Horario de Sesión */}
                    <td className="p-2.5">
                      {session ? (
                        <div className="flex items-center gap-1.5">
                          <Clock
                            className={`w-3.5 h-3.5 ${
                              session.isActive ? 'text-emerald-400' : 'text-amber-400/80'
                            }`}
                          />
                          <span
                            className={`text-xs ${
                              session.isActive ? 'text-emerald-300' : 'text-slate-400'
                            }`}
                          >
                            {session.startTime}-{session.endTime}
                          </span>
                          <span
                            className={`text-[10px] px-1 rounded ${
                              session.isActive
                                ? 'bg-emerald-950 text-emerald-400'
                                : 'bg-slate-800 text-slate-500'
                            }`}
                          >
                            {session.isActive ? 'Abierto' : 'Inactivo'}
                          </span>
                        </div>
                      ) : (
                        <span className="text-slate-500 text-xs">24/7</span>
                      )}
                    </td>

                    {/* Eliminar */}
                    <td className="p-2.5 text-center">
                      <button
                        type="button"
                        onClick={() => handleRemoveSymbol(sym)}
                        className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-950/40 transition-colors"
                        title="Quitar par del monitor"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Footer controls */}
      <div className="p-3 bg-slate-950 border-t border-slate-800 flex flex-wrap items-center justify-between text-xs text-slate-400 gap-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleActivateAll}
            className="hover:text-slate-200 underline font-medium"
          >
            Activar Todos ({availableSymbols.length})
          </button>
          <span>•</span>
          <button
            type="button"
            onClick={handleDeactivateAll}
            className="hover:text-slate-200 underline font-medium"
          >
            Desactivar Todos
          </button>
        </div>

        <div className="text-slate-400">
          Total asignado:{' '}
          <span className="text-slate-200 font-bold font-mono">
            {activeSymbols.length} pares
          </span>
        </div>
      </div>
    </div>
  );
};
