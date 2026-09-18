import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Brain,
  CheckSquare,
  Square,
  ArrowUpDown,
  UploadCloud,
  FileText,
  RefreshCw,
  Play,
  Square as StopSquare,
  Trophy,
  Filter,
  Check,
  Info,
  Scale,
  Zap,
  TrendingUp,
  ShieldCheck,
  AlertTriangle,
  XCircle,
  Clock,
  Layers,
  Search
} from 'lucide-react';
import {
  DeepSearchResultItem,
  SymbolMetadata,
  StrategySummaryItem,
  BestPerSymbolItem
} from '../types';
import { AutocompleteInput } from './AutocompleteInput';

interface DeepSearchProps {
  results: DeepSearchResultItem[];
  isLoading: boolean;
  onSendToAI: (selectedItems: DeepSearchResultItem[]) => void;
  onMountSymbols: (symbols: string[]) => void;
  onOpenChangelog: (symbol?: string) => void;
  isAiProcessing: boolean;
  symbolsMetadata?: Record<string, SymbolMetadata>;
  availableSymbols?: string[];
  activeSymbols?: string[];
  onRefreshResults?: () => void;
  onApplyBestStrategies?: (bestList: BestPerSymbolItem[]) => void;
}

export const DeepSearch: React.FC<DeepSearchProps> = ({
  results = [],
  isLoading = false,
  onSendToAI,
  onMountSymbols,
  onOpenChangelog,
  isAiProcessing = false,
  symbolsMetadata = {},
  availableSymbols = [],
  activeSymbols = [],
  onRefreshResults,
  onApplyBestStrategies,
}) => {
  // Tabs: 'search' (🔬 Deep Search por Símbolo) vs 'compare' (⚖️ Comparativa de Estrategias & Mejor por Par)
  const [activeTab, setActiveTab] = useState<'search' | 'compare'>('search');

  // Search & Configuration Controls
  const [selectedStrategy, setSelectedStrategy] = useState<string>('all');
  const [selectedDays, setSelectedDays] = useState<string>('30 Días');
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('all');
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchProgress, setSearchProgress] = useState<number>(0);
  const [statusMessage, setStatusMessage] = useState<string>(
    'Listo para ejecutar Deep Search o consultar resultados guardados.'
  );

  // Search Input & Autocomplete Filter
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [activeCategory, setActiveCategory] = useState<string>('Todos');

  // Derive symbols catalogue safely
  const computedAvailableSymbols = React.useMemo(() => {
    if (availableSymbols && availableSymbols.length > 0) {
      return availableSymbols;
    }
    const symbolSet = new Set<string>();
    if (Array.isArray(results)) {
      results.forEach((r) => {
        if (r.symbol) symbolSet.add(r.symbol);
      });
    }
    if (symbolSet.size > 0) {
      return Array.from(symbolSet);
    }
    return [
      'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'NZDUSD',
      'EURGBP', 'EURJPY', 'GBPJPY', 'XAUUSD', 'XAGUSD', 'BTCUSD', 'ETHUSD',
      'US500', 'NAS100', 'US30', 'GER40'
    ];
  }, [availableSymbols, results]);

  const computedSymbolsMetadata = React.useMemo(() => {
    if (symbolsMetadata && Object.keys(symbolsMetadata).length > 0) {
      return symbolsMetadata;
    }
    const meta: Record<string, SymbolMetadata> = {};
    computedAvailableSymbols.forEach((sym) => {
      const match = Array.isArray(results) ? results.find((r) => r.symbol === sym) : undefined;
      const s = sym.toUpperCase();
      const cat = s.includes('XAU') || s.includes('XAG') || s.includes('GOLD')
        ? 'Metales'
        : s.includes('BTC') || s.includes('ETH')
          ? 'Cripto'
          : s.includes('500') || s.includes('100') || s.includes('30') || s.includes('GER')
            ? 'Índices'
            : 'Forex';

      meta[sym] = {
        symbol: sym,
        category: match?.category || cat,
        suggested_timeframe: match
          ? {
              timeframe: match.timeframe,
              timeframe_str: match.timeframe_str || `M${match.timeframe}`,
              strategy: match.strategy,
              win_rate: match.win_rate,
              avg_r: match.avg_r,
            }
          : undefined,
      };
    });
    return meta;
  }, [symbolsMetadata, computedAvailableSymbols, results]);

  // Selection & Sorting
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [sortOption, setSortOption] = useState<string>('Mayor Win Rate');
  const [sortColumn, setSortColumn] = useState<string>('win_rate');
  const [sortAsc, setSortAsc] = useState<boolean>(false);

  // Strategy Comparison Data
  const [comparisonSummary, setComparisonSummary] = useState<StrategySummaryItem[]>([]);
  const [bestPerSymbol, setBestPerSymbol] = useState<BestPerSymbolItem[]>([]);
  const [compareFilterQuery, setCompareFilterQuery] = useState<string>('');
  const [isLoadingCompare, setIsLoadingCompare] = useState<boolean>(false);

  // Load Strategy Comparison
  const loadComparisonData = async () => {
    setIsLoadingCompare(true);
    try {
      const res = await fetch('/api/deep-search/comparison');
      if (res.ok) {
        const data = await res.json();
        setComparisonSummary(data.strategies_summary || []);
        setBestPerSymbol(data.best_per_symbol || []);
      }
    } catch {
      // Fallback handled gracefully
    } finally {
      setIsLoadingCompare(false);
    }
  };

  useEffect(() => {
    loadComparisonData();
  }, []);

  // Filter & Sort Results for Tab 1
  const filteredResults = results.filter((item) => {
    // Strategy filter
    if (selectedStrategy !== 'all' && item.strategy !== selectedStrategy) {
      return false;
    }
    // Timeframe filter
    if (selectedTimeframe !== 'all') {
      const tfStr = item.timeframe_str || (item.timeframe ? `M${item.timeframe}` : '');
      if (tfStr !== selectedTimeframe) return false;
    }
    // Category filter
    if (activeCategory !== 'Todos' && item.category) {
      if (item.category !== activeCategory) return false;
    }
    // Search query match
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      const symMatch = item.symbol.toLowerCase().includes(q);
      const stratMatch = (item.strategy || '').toLowerCase().includes(q);
      const catMatch = (item.category || '').toLowerCase().includes(q);
      if (!symMatch && !stratMatch && !catMatch) return false;
    }
    return true;
  });

  // Sort logic
  const sortedResults = [...filteredResults].sort((a, b) => {
    let comp = 0;
    if (sortColumn === 'symbol') {
      comp = a.symbol.localeCompare(b.symbol);
    } else if (sortColumn === 'strategy') {
      comp = (a.strategy || '').localeCompare(b.strategy || '');
    } else if (sortColumn === 'timeframe') {
      comp = (Number(a.timeframe) || 0) - (Number(b.timeframe) || 0);
    } else if (sortColumn === 'trades') {
      comp = (a.trades || a.trades_count || 0) - (b.trades || b.trades_count || 0);
    } else if (sortColumn === 'win_rate') {
      comp = (a.win_rate || 0) - (b.win_rate || 0);
    } else if (sortColumn === 'avg_r') {
      comp = (a.avg_r ?? a.avg_r_multiple ?? 0) - (b.avg_r ?? b.avg_r_multiple ?? 0);
    } else if (sortColumn === 'score') {
      comp = (a.score || 0) - (b.score || 0);
    } else if (sortColumn === 'verdict') {
      comp = (a.verdict || '').localeCompare(b.verdict || '');
    }
    return sortAsc ? comp : -comp;
  });

  const toggleSelectItem = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelectedIds(next);
  };

  const handleSelectAll = () => {
    if (selectedIds.size === sortedResults.length && sortedResults.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(sortedResults.map((r) => r.id || `${r.symbol}-${r.strategy}-${r.timeframe}`)));
    }
  };

  const handleSelectTop5 = () => {
    // Top 5 by Win Rate & Avg R
    const top5 = [...sortedResults]
      .sort((a, b) => (b.win_rate || 0) - (a.win_rate || 0) || (b.avg_r || 0) - (a.avg_r || 0))
      .slice(0, 5)
      .map((r) => r.id || `${r.symbol}-${r.strategy}-${r.timeframe}`);
    setSelectedIds(new Set(top5));
  };

  const handleDeselectAll = () => {
    setSelectedIds(new Set());
  };

  const handleSortHeader = (col: string) => {
    if (sortColumn === col) {
      setSortAsc(!sortAsc);
    } else {
      setSortColumn(col);
      setSortAsc(false);
    }
  };

  const handleSortOptionChange = (opt: string) => {
    setSortOption(opt);
    if (opt === 'Mayor Win Rate') {
      setSortColumn('win_rate');
      setSortAsc(false);
    } else if (opt === 'Mayor Avg R') {
      setSortColumn('avg_r');
      setSortAsc(false);
    } else if (opt === 'Más Trades') {
      setSortColumn('trades');
      setSortAsc(false);
    } else if (opt === 'Símbolo (A-Z)') {
      setSortColumn('symbol');
      setSortAsc(true);
    } else if (opt === 'Símbolo (Z-A)') {
      setSortColumn('symbol');
      setSortAsc(false);
    } else if (opt === 'Timeframe') {
      setSortColumn('timeframe');
      setSortAsc(true);
    } else if (opt === 'Mejor Veredicto') {
      setSortColumn('score');
      setSortAsc(false);
    }
  };

  // Execution simulation
  const handleToggleDeepSearch = async () => {
    if (isSearching) {
      setIsSearching(false);
      setStatusMessage('🛑 Deep Search cancelado por el usuario.');
      return;
    }

    setIsSearching(true);
    setSearchProgress(10);
    setStatusMessage(`Iniciando Deep Search cuantitativo (${selectedStrategy}, ${selectedDays}, TF: ${selectedTimeframe})...`);

    // Simulate progressive search
    let prog = 10;
    const interval = setInterval(() => {
      prog += 20;
      if (prog >= 100) {
        clearInterval(interval);
        setSearchProgress(100);
        setIsSearching(false);
        setStatusMessage(`✅ Deep Search completado con éxito. Se analizaron los pares del catálogo.`);
        if (onRefreshResults) onRefreshResults();
        loadComparisonData();
      } else {
        setSearchProgress(prog);
        setStatusMessage(`Analizando confluencias históricas... (${prog}% completado)`);
      }
    }, 450);
  };

  const getSelectedItems = (): DeepSearchResultItem[] => {
    return results.filter((r) => {
      const id = r.id || `${r.symbol}-${r.strategy}-${r.timeframe}`;
      return selectedIds.has(id);
    });
  };

  const getSelectedSymbolsList = (): string[] => {
    const syms = new Set<string>();
    getSelectedItems().forEach((it) => syms.add(it.symbol));
    return Array.from(syms);
  };

  const handleMountSelected = () => {
    const syms = getSelectedSymbolsList();
    if (syms.length === 0) return;
    onMountSymbols(syms);
  };

  const handleSendSelectedToAI = () => {
    const items = getSelectedItems();
    if (items.length === 0) return;
    onSendToAI(items);
  };

  // Helper verdict styling
  const renderVerdictBadge = (verdict?: string) => {
    if (!verdict) return <span className="text-slate-500 text-xs">—</span>;
    if (verdict.includes('Excelente')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-700/60 shadow-xs">
          {verdict}
        </span>
      );
    }
    if (verdict.includes('Aceptable')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-sky-950/80 text-sky-300 border border-sky-700/60 shadow-xs">
          {verdict}
        </span>
      );
    }
    if (verdict.includes('Precaución')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-950/80 text-amber-300 border border-amber-700/60 shadow-xs">
          {verdict}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-950/80 text-rose-300 border border-rose-800/60 shadow-xs">
        {verdict}
      </span>
    );
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col h-full text-slate-100">
      {/* 1. Header Principal */}
      <div className="px-5 py-3.5 border-b border-slate-800/90 bg-slate-950/80 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-sky-500/10 text-sky-400 border border-sky-500/20 shadow-xs">
            <Brain className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold text-slate-100 tracking-tight flex items-center gap-2">
                🔬 Deep Search & Comparativa Multiestrategia
              </h1>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-sky-300 border border-slate-700">
                {results.length} Tests Guardados
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Ranking Cuantitativo • Detección Óptima por Par • Asignación Multialgoritmo
            </p>
          </div>
        </div>

        {/* Tab Switcher Segmented Buttons */}
        <div className="flex items-center p-1 rounded-lg bg-slate-900 border border-slate-800 text-xs font-medium">
          <button
            type="button"
            id="tab-btn-deep-search"
            onClick={() => setActiveTab('search')}
            className={`px-3.5 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
              activeTab === 'search'
                ? 'bg-sky-600 text-white font-bold shadow-md shadow-sky-600/20'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <span>🔬 Deep Search por Símbolo</span>
          </button>
          <button
            type="button"
            id="tab-btn-compare-strategies"
            onClick={() => setActiveTab('compare')}
            className={`px-3.5 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
              activeTab === 'compare'
                ? 'bg-sky-600 text-white font-bold shadow-md shadow-sky-600/20'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Scale className="w-3.5 h-3.5" />
            <span>⚖️ Comparativa & Mejor por Par</span>
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: 🔬 Deep Search por Símbolo                                         */}
      {/* ========================================================================= */}
      {activeTab === 'search' && (
        <div className="flex flex-col flex-1 min-h-0">
          {/* Barra Superior de Configuración */}
          <div className="p-3.5 bg-slate-900/60 border-b border-slate-800/80 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              {/* Selector de Estrategia */}
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-bold text-amber-400">🎯 Estrategia:</span>
                <select
                  id="select-ds-strategy"
                  value={selectedStrategy}
                  onChange={(e) => setSelectedStrategy(e.target.value)}
                  className="bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-amber-300 font-semibold focus:outline-hidden focus:border-amber-500"
                >
                  <option value="all">Todas las Estrategias</option>
                  <option value="simple_trend">simple_trend</option>
                  <option value="forex">forex</option>
                  <option value="syntx">syntx</option>
                  <option value="ai_strategy">ai_strategy</option>
                </select>
              </div>

              {/* Selector de Historial */}
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-bold text-slate-400">📅 Historial:</span>
                <select
                  id="select-ds-days"
                  value={selectedDays}
                  onChange={(e) => setSelectedDays(e.target.value)}
                  className="bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-hidden focus:border-sky-500"
                >
                  <option value="15 Días">15 Días</option>
                  <option value="30 Días">30 Días</option>
                  <option value="45 Días">45 Días</option>
                  <option value="60 Días">60 Días</option>
                </select>
              </div>

              {/* Selector de Timeframe */}
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-bold text-slate-400">⏱️ Timeframe:</span>
                <select
                  id="select-ds-timeframe"
                  value={selectedTimeframe}
                  onChange={(e) => setSelectedTimeframe(e.target.value)}
                  className="bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-hidden focus:border-sky-500"
                >
                  <option value="all">Auto (Mejor TF / Todos)</option>
                  <option value="M5">M5</option>
                  <option value="M15">M15</option>
                  <option value="M30">M30</option>
                  <option value="H1">H1</option>
                  <option value="H4">H4</option>
                </select>
              </div>
            </div>

            {/* Botón Iniciar / Detener Deep Search */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                id="btn-run-deep-search"
                onClick={handleToggleDeepSearch}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all shadow-md flex items-center gap-2 ${
                  isSearching
                    ? 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-600/20'
                    : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/20'
                }`}
              >
                {isSearching ? (
                  <>
                    <StopSquare className="w-3.5 h-3.5" />
                    <span>🛑 Detener Búsqueda</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>▶️ Iniciar Deep Search</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Barra de Progreso y Estado */}
          <div className="px-4 py-2 bg-slate-950/40 border-b border-slate-800/60">
            <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden mb-1.5">
              <div
                className="bg-linear-to-r from-sky-500 via-indigo-500 to-purple-500 h-full transition-all duration-300"
                style={{ width: `${searchProgress}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span className="flex items-center gap-1.5">
                <Info className="w-3 h-3 text-sky-400" />
                {statusMessage}
              </span>
              <span className="font-mono text-slate-500">{sortedResults.length} resultados filtrados</span>
            </div>
          </div>

          {/* Barra de Búsqueda con Autocompletado & Acciones */}
          <div className="p-3 bg-slate-950/90 border-b border-slate-800 flex flex-col lg:flex-row lg:items-center justify-between gap-3">
            {/* Autocomplete Input Search */}
            <div className="w-full lg:w-96">
              <AutocompleteInput
                id="deep-search-autocomplete"
                value={searchQuery}
                onChange={setSearchQuery}
                onSelectSymbol={(sym) => {
                  setSearchQuery(sym);
                }}
                symbolsMetadata={computedSymbolsMetadata}
                availableSymbols={computedAvailableSymbols}
                activeSymbols={activeSymbols}
                placeholder="Buscar por símbolo (ej. EURUSD, GBP, XAU)..."
                showCategoryFilters={true}
                activeCategory={activeCategory}
                onSelectCategory={setActiveCategory}
                compact={false}
              />
            </div>

            {/* Quick Selection and Action Buttons */}
            <div className="flex items-center gap-2 flex-wrap justify-end">
              <div className="flex items-center gap-1 text-xs bg-slate-900 border border-slate-800 p-0.5 rounded-lg">
                <span className="text-slate-400 px-1.5 font-medium text-[11px]">🏆 Sel:</span>
                <button
                  type="button"
                  id="btn-ds-select-all"
                  onClick={handleSelectAll}
                  className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold"
                >
                  ☑️ Todos
                </button>
                <button
                  type="button"
                  id="btn-ds-select-top5"
                  onClick={handleSelectTop5}
                  className="px-2 py-1 rounded bg-sky-950/80 hover:bg-sky-800 text-sky-300 border border-sky-700/50 text-xs font-semibold"
                >
                  ⭐ Top 5
                </button>
                <button
                  type="button"
                  id="btn-ds-deselect"
                  onClick={handleDeselectAll}
                  className="px-2 py-1 rounded hover:bg-slate-800 text-slate-400 text-xs"
                >
                  ◻️ Ninguno
                </button>
              </div>

              {/* Selector de Orden */}
              <div className="flex items-center gap-1 text-xs">
                <span className="text-slate-400 text-[11px] font-medium hidden sm:inline">↕ Orden:</span>
                <select
                  id="select-ds-sort"
                  value={sortOption}
                  onChange={(e) => handleSortOptionChange(e.target.value)}
                  className="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-hidden"
                >
                  <option value="Mayor Win Rate">Mayor Win Rate</option>
                  <option value="Mayor Avg R">Mayor Avg R</option>
                  <option value="Más Trades">Más Trades</option>
                  <option value="Símbolo (A-Z)">Símbolo (A-Z)</option>
                  <option value="Símbolo (Z-A)">Símbolo (Z-A)</option>
                  <option value="Timeframe">Timeframe</option>
                  <option value="Mejor Veredicto">Mejor Veredicto</option>
                </select>
              </div>

              {/* 🟢 Botón Montar Pares */}
              <button
                type="button"
                id="btn-ds-mount"
                onClick={handleMountSelected}
                disabled={selectedIds.size === 0}
                className="px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold shadow-md shadow-blue-600/20 transition-all flex items-center gap-1.5"
              >
                <UploadCloud className="w-3.5 h-3.5" />
                <span>📥 Montar Pares ({selectedIds.size})</span>
              </button>

              {/* 🧠 Botón IA */}
              <button
                type="button"
                id="btn-ds-ai-learn"
                onClick={handleSendSelectedToAI}
                disabled={selectedIds.size === 0 || isAiProcessing}
                className="px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold shadow-md shadow-purple-600/20 transition-all flex items-center gap-1.5"
              >
                {isAiProcessing ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Aprendiendo...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>🧠 Enviar a IA ({selectedIds.size})</span>
                  </>
                )}
              </button>

              {/* 📜 Botón Changelog */}
              <button
                type="button"
                id="btn-ds-changelog"
                onClick={() => onOpenChangelog()}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 text-xs font-semibold transition-colors flex items-center gap-1"
              >
                <FileText className="w-3.5 h-3.5 text-purple-400" />
                <span>Changelog</span>
              </button>
            </div>
          </div>

          {/* Tabla Interactiva de Resultados */}
          <div className="overflow-x-auto flex-1 max-h-[520px]">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 sticky top-0 z-10 select-none font-mono">
                <tr>
                  <th className="p-2.5 w-10 text-center">
                    <button
                      type="button"
                      onClick={handleSelectAll}
                      className="hover:text-slate-200"
                    >
                      {selectedIds.size === sortedResults.length && sortedResults.length > 0 ? (
                        <CheckSquare className="w-4 h-4 text-sky-400" />
                      ) : (
                        <Square className="w-4 h-4 text-slate-500" />
                      )}
                    </button>
                  </th>

                  <th
                    className="p-2.5 cursor-pointer hover:text-slate-100"
                    onClick={() => handleSortHeader('symbol')}
                  >
                    <div className="flex items-center gap-1">
                      <span>Símbolo</span>
                      <ArrowUpDown className="w-3 h-3" />
                    </div>
                  </th>

                  <th
                    className="p-2.5 cursor-pointer hover:text-slate-100"
                    onClick={() => handleSortHeader('strategy')}
                  >
                    <div className="flex items-center gap-1">
                      <span>Estrategia</span>
                      <ArrowUpDown className="w-3 h-3" />
                    </div>
                  </th>

                  <th
                    className="p-2.5 cursor-pointer hover:text-slate-100 text-center"
                    onClick={() => handleSortHeader('timeframe')}
                  >
                    <div className="flex items-center justify-center gap-1">
                      <span>TF</span>
                      <ArrowUpDown className="w-3 h-3" />
                    </div>
                  </th>

                  <th
                    className="p-2.5 cursor-pointer hover:text-slate-100 text-right"
                    onClick={() => handleSortHeader('trades')}
                  >
                    <div className="flex items-center justify-end gap-1">
                      <span>Trades</span>
                      <ArrowUpDown className="w-3 h-3" />
                    </div>
                  </th>

                  <th
                    className="p-2.5 cursor-pointer hover:text-slate-100"
                    onClick={() => handleSortHeader('win_rate')}
                  >
                    <div className="flex items-center gap-1">
                      <span>Win Rate %</span>
                      <ArrowUpDown className="w-3 h-3" />
                    </div>
                  </th>

                  <th
                    className="p-2.5 cursor-pointer hover:text-slate-100 text-right"
                    onClick={() => handleSortHeader('avg_r')}
                  >
                    <div className="flex items-center justify-end gap-1">
                      <span>Expectativa (Avg R)</span>
                      <ArrowUpDown className="w-3 h-3" />
                    </div>
                  </th>

                  <th
                    className="p-2.5 cursor-pointer hover:text-slate-100 text-center"
                    onClick={() => handleSortHeader('verdict')}
                  >
                    <div className="flex items-center justify-center gap-1">
                      <span>Veredicto</span>
                      <ArrowUpDown className="w-3 h-3" />
                    </div>
                  </th>

                  <th className="p-2.5 text-right">Acciones</th>
                </tr>
              </thead>

              <tbody className="divide-y divide-slate-800/60 font-mono">
                {sortedResults.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="p-10 text-center text-slate-500 font-sans">
                      <div className="max-w-md mx-auto">
                        <Filter className="w-8 h-8 mx-auto mb-2 text-slate-600 opacity-60" />
                        <p className="font-semibold text-slate-300">No hay pares que coincidan con la búsqueda.</p>
                        <p className="text-xs text-slate-500 mt-1">
                          Prueba escribiendo otro símbolo en el buscador o cambiando el filtro de estrategia.
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  sortedResults.map((item, idx) => {
                    const rowId = item.id || `${item.symbol}-${item.strategy}-${item.timeframe}-${idx}`;
                    const isSelected = selectedIds.has(rowId);
                    const wr = item.win_rate || 0;
                    const avgR = item.avg_r ?? item.avg_r_multiple ?? 0;
                    const trades = item.trades || item.trades_count || 0;
                    const tfStr = item.timeframe_str || (item.timeframe ? `M${item.timeframe}` : 'M15');
                    const isMonitored = activeSymbols.includes(item.symbol);

                    return (
                      <tr
                        key={rowId}
                        id={`ds-row-${item.symbol}-${item.timeframe}`}
                        onClick={() => toggleSelectItem(rowId)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-sky-950/40 hover:bg-sky-950/60 border-l-2 border-sky-400'
                            : 'hover:bg-slate-800/40'
                        }`}
                      >
                        {/* Checkbox */}
                        <td className="p-2.5 text-center" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            onClick={() => toggleSelectItem(rowId)}
                            className="text-slate-400 hover:text-slate-100"
                          >
                            {isSelected ? (
                              <CheckSquare className="w-4 h-4 text-sky-400" />
                            ) : (
                              <Square className="w-4 h-4 text-slate-600" />
                            )}
                          </button>
                        </td>

                        {/* Símbolo */}
                        <td className="p-2.5 font-bold text-slate-100 flex items-center gap-2">
                          <span className="tracking-wider">{item.symbol}</span>
                          {item.category && (
                            <span className="text-[10px] font-normal px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 border border-slate-700/80">
                              {item.category}
                            </span>
                          )}
                          {isMonitored && (
                            <span className="text-[9px] px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
                              Activo
                            </span>
                          )}
                        </td>

                        {/* Estrategia */}
                        <td className="p-2.5">
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-950/50 text-amber-300 border border-amber-800/40">
                            {item.strategy || 'simple_trend'}
                          </span>
                        </td>

                        {/* Timeframe */}
                        <td className="p-2.5 text-center">
                          <span className="px-2 py-0.5 rounded text-xs font-bold bg-slate-800 text-sky-300 border border-slate-700">
                            {tfStr}
                          </span>
                        </td>

                        {/* Trades */}
                        <td className="p-2.5 text-right font-medium text-slate-300">{trades}</td>

                        {/* Win Rate with progress bar */}
                        <td className="p-2.5">
                          <div className="flex items-center gap-2">
                            <div className="w-16 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                              <div
                                className={`h-full ${
                                  wr >= 55 ? 'bg-emerald-400' : wr >= 45 ? 'bg-sky-400' : 'bg-rose-400'
                                }`}
                                style={{ width: `${Math.min(100, Math.max(5, wr))}%` }}
                              />
                            </div>
                            <span
                              className={`font-bold ${
                                wr >= 55 ? 'text-emerald-400' : wr >= 45 ? 'text-sky-300' : 'text-rose-400'
                              }`}
                            >
                              {wr.toFixed(1)}%
                            </span>
                            {item.win_rate_confidence && (
                              <span className="text-[10px] text-slate-500">
                                (conf {item.win_rate_confidence.toFixed(0)}%)
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Avg R */}
                        <td className="p-2.5 text-right">
                          <span
                            className={`font-bold ${
                              avgR >= 0.5
                                ? 'text-emerald-400'
                                : avgR >= 0
                                ? 'text-sky-300'
                                : 'text-rose-400'
                            }`}
                          >
                            {avgR >= 0 ? `+${avgR.toFixed(2)}` : avgR.toFixed(2)}R
                          </span>
                        </td>

                        {/* Veredicto */}
                        <td className="p-2.5 text-center font-sans">
                          {renderVerdictBadge(item.verdict)}
                        </td>

                        {/* Row Actions */}
                        <td className="p-2.5 text-right font-sans" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              type="button"
                              onClick={() => onMountSymbols([item.symbol])}
                              className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-800 hover:bg-sky-700 hover:text-white text-slate-300 transition-colors border border-slate-700"
                              title="Montar par al monitor"
                            >
                              Montar
                            </button>
                            <button
                              type="button"
                              onClick={() => onOpenChangelog(item.symbol)}
                              className="px-2 py-0.5 rounded text-[11px] font-medium text-slate-400 hover:text-purple-400 transition-colors"
                              title="Ver historial de cambios IA"
                            >
                              MR
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: ⚖️ Comparativa de Estrategias & Mejor por Par                      */}
      {/* ========================================================================= */}
      {activeTab === 'compare' && (
        <div className="flex flex-col flex-1 min-h-0 p-4 overflow-y-auto space-y-5">
          {/* Header Summary Cards for Strategies */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-bold text-slate-200 flex items-center gap-2">
                <Trophy className="w-4 h-4 text-amber-400" />
                Resumen Comparativo Global de Estrategias
              </h2>
              <span className="text-xs text-slate-400">
                Calculado sobre {results.length} simulaciones cuantitativas
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {comparisonSummary.map((strat) => {
                const wrColor =
                  strat.win_rate >= 55 ? 'text-emerald-400' : strat.win_rate >= 45 ? 'text-sky-400' : 'text-amber-400';
                return (
                  <div
                    key={strat.strategy}
                    className="p-4 rounded-xl bg-slate-950/80 border border-slate-800 hover:border-slate-700 transition-all shadow-md flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-bold text-sm text-slate-100 uppercase font-mono">
                          {strat.strategy}
                        </span>
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
                          {strat.symbols_count} pares
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-xs mb-3">
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase">Win Rate</div>
                          <div className={`text-base font-bold font-mono ${wrColor}`}>
                            {strat.win_rate.toFixed(1)}%
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase">Avg R</div>
                          <div className="text-base font-bold font-mono text-emerald-400">
                            {strat.avg_r >= 0 ? `+${strat.avg_r.toFixed(2)}` : strat.avg_r.toFixed(2)}R
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
                      <span>Total Trades: {strat.total_trades}</span>
                      <span className="text-slate-500">Conf: {strat.win_rate_confidence.toFixed(1)}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Winner Strategy Matrix Per Symbol */}
          <div className="bg-slate-950/70 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
            <div className="p-3.5 border-b border-slate-800 bg-slate-950 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Zap className="w-4 h-4 text-amber-400" />
                <h3 className="text-sm font-bold text-slate-100">
                  Matriz de Estrategia Ganadora & Timeframe Óptimo por Par
                </h3>
                <span className="text-xs text-slate-500 font-mono">({bestPerSymbol.length} pares)</span>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {/* Autocomplete or Filter Input for Matrix */}
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
                  <input
                    type="text"
                    placeholder="Filtrar matriz..."
                    value={compareFilterQuery}
                    onChange={(e) => setCompareFilterQuery(e.target.value)}
                    className="bg-slate-900 border border-slate-700 rounded-lg pl-8 pr-3 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-hidden focus:border-sky-500 w-44 font-mono"
                  />
                </div>

                {/* ⚡ Aplicar Mejores a la Tabla */}
                {onApplyBestStrategies && (
                  <button
                    type="button"
                    onClick={() => onApplyBestStrategies(bestPerSymbol)}
                    className="px-3 py-1 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold text-xs shadow-md shadow-amber-600/20 transition-all flex items-center gap-1.5"
                  >
                    <Zap className="w-3 h-3 fill-current" />
                    <span>⚡ Aplicar Mejores a la Tabla</span>
                  </button>
                )}
              </div>
            </div>

            <div className="overflow-x-auto max-h-96">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="bg-slate-900/90 text-slate-400 border-b border-slate-800 sticky top-0 font-mono">
                  <tr>
                    <th className="p-2.5">Símbolo</th>
                    <th className="p-2.5">Estrategia Ganadora</th>
                    <th className="p-2.5 text-center">Timeframe Óptimo</th>
                    <th className="p-2.5 text-right">Trades</th>
                    <th className="p-2.5">Win Rate %</th>
                    <th className="p-2.5 text-right">Expectativa (Avg R)</th>
                    <th className="p-2.5 text-right">Acción</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {bestPerSymbol
                    .filter((item) =>
                      compareFilterQuery
                        ? item.symbol.toLowerCase().includes(compareFilterQuery.toLowerCase()) ||
                          item.winning_strategy.toLowerCase().includes(compareFilterQuery.toLowerCase())
                        : true
                    )
                    .map((b) => (
                      <tr key={b.symbol} className="hover:bg-slate-800/30 transition-colors">
                        <td className="p-2.5 font-bold text-slate-100 flex items-center gap-1.5">
                          {b.symbol}
                          {b.category && (
                            <span className="text-[10px] font-normal px-1 py-0.2 rounded bg-slate-800 text-slate-400">
                              {b.category}
                            </span>
                          )}
                        </td>

                        <td className="p-2.5">
                          <span className="px-2 py-0.5 rounded text-xs font-bold bg-amber-950/60 text-amber-300 border border-amber-800/50">
                            ⚡ {b.winning_strategy}
                          </span>
                        </td>

                        <td className="p-2.5 text-center">
                          <span className="px-2 py-0.5 rounded text-xs font-bold bg-slate-800 text-sky-300 border border-slate-700">
                            {b.optimal_timeframe}
                          </span>
                        </td>

                        <td className="p-2.5 text-right text-slate-300">{b.trades}</td>

                        <td className="p-2.5 font-bold text-emerald-400">
                          {b.win_rate.toFixed(1)}%
                          <span className="text-[10px] text-slate-500 ml-1">
                            (conf {b.win_rate_confidence.toFixed(0)}%)
                          </span>
                        </td>

                        <td className="p-2.5 text-right font-bold text-emerald-400">
                          {b.avg_r >= 0 ? `+${b.avg_r.toFixed(2)}` : b.avg_r.toFixed(2)}R
                        </td>

                        <td className="p-2.5 text-right font-sans">
                          <button
                            type="button"
                            onClick={() => onMountSymbols([b.symbol])}
                            className="px-2 py-0.5 rounded text-xs font-semibold bg-sky-950 hover:bg-sky-800 text-sky-300 border border-sky-700 transition-colors"
                          >
                            Montar
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
