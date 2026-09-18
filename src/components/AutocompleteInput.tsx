import React, { useState, useRef, useEffect } from 'react';
import { Search, X, Sparkles, Clock, CheckCircle2, ChevronRight } from 'lucide-react';
import { SymbolMetadata } from '../types';

interface AutocompleteInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  onSelectSymbol: (symbol: string, meta?: SymbolMetadata) => void;
  symbolsMetadata?: Record<string, SymbolMetadata>;
  availableSymbols?: string[];
  placeholder?: string;
  className?: string;
  showCategoryFilters?: boolean;
  activeCategory?: string;
  onSelectCategory?: (category: string) => void;
  excludeActive?: boolean;
  activeSymbols?: string[];
  autoFocus?: boolean;
  compact?: boolean;
}

const CATEGORIES = ['Todos', 'Forex', 'Metales', 'Índices', 'Cripto', 'Acciones'];

export const AutocompleteInput: React.FC<AutocompleteInputProps> = ({
  id = 'autocomplete-symbol-input',
  value = '',
  onChange,
  onSelectSymbol,
  symbolsMetadata = {},
  availableSymbols = [],
  placeholder = 'Buscar o añadir par (ej. EURUSD, XAU, BTC, SPX)...',
  className = '',
  showCategoryFilters = false,
  activeCategory = 'Todos',
  onSelectCategory,
  excludeActive = false,
  activeSymbols = [],
  autoFocus = false,
  compact = false,
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const safeSymbols = Array.isArray(availableSymbols) ? availableSymbols : [];
  const safeMeta = symbolsMetadata || {};
  const safeActive = Array.isArray(activeSymbols) ? activeSymbols : [];

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const query = (value || '').trim().toLowerCase();

  // Filter symbols based on query, category, and exclusion
  const filteredSymbols = safeSymbols.filter((sym) => {
    if (!sym) return false;
    const meta = safeMeta[sym];
    if (activeCategory && activeCategory !== 'Todos') {
      if (meta?.category && meta.category !== activeCategory) return false;
    }
    if (excludeActive && safeActive.includes(sym)) {
      return false;
    }
    if (!query) return true;
    return sym.toLowerCase().includes(query);
  });

  // Limit suggestions list for fast, snappy rendering (top 8)
  const suggestions = query ? filteredSymbols.slice(0, 8) : filteredSymbols.slice(0, 6);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!isOpen) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setIsOpen(true);
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
        const chosen = suggestions[selectedIndex];
        onSelectSymbol(chosen, safeMeta[chosen]);
        setIsOpen(false);
      } else if (suggestions.length > 0) {
        const chosen = suggestions[0];
        onSelectSymbol(chosen, safeMeta[chosen]);
        setIsOpen(false);
      }
    } else if (e.key === 'Escape') {
      setIsOpen(false);
    }
  };

  const handleSelect = (sym: string) => {
    onSelectSymbol(sym, safeMeta[sym]);
    setIsOpen(false);
    inputRef.current?.blur();
  };

  const clearInput = (e: React.MouseEvent) => {
    e.stopPropagation();
    onChange('');
    setIsOpen(false);
    inputRef.current?.focus();
  };

  const highlightMatch = (text: string, match: string) => {
    if (!match) return <span>{text}</span>;
    const idx = text.toLowerCase().indexOf(match.toLowerCase());
    if (idx === -1) return <span>{text}</span>;
    return (
      <span>
        {text.substring(0, idx)}
        <span className="text-sky-400 font-extrabold bg-sky-950/60 px-0.5 rounded">
          {text.substring(idx, idx + match.length)}
        </span>
        {text.substring(idx + match.length)}
      </span>
    );
  };

  return (
    <div ref={containerRef} className={`relative flex flex-col gap-1.5 ${className}`}>
      {/* Category filters if enabled */}
      {showCategoryFilters && onSelectCategory && (
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
          {CATEGORIES.map((cat) => {
            const isCatActive = activeCategory === cat;
            return (
              <button
                key={cat}
                type="button"
                id={`cat-filter-${cat.toLowerCase()}`}
                onClick={() => onSelectCategory(cat)}
                className={`px-2.5 py-1 rounded-full whitespace-nowrap transition-all font-medium border ${
                  isCatActive
                    ? 'bg-sky-500/20 text-sky-300 border-sky-500/40 shadow-xs'
                    : 'bg-slate-900/60 text-slate-400 border-slate-800 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                {cat}
              </button>
            );
          })}
        </div>
      )}

      {/* Main input wrapper */}
      <div className="relative flex items-center">
        <div className="absolute left-3 text-slate-400 pointer-events-none flex items-center">
          <Search className={compact ? 'w-3.5 h-3.5' : 'w-4 h-4'} />
        </div>

        <input
          ref={inputRef}
          id={id}
          type="text"
          value={value}
          autoFocus={autoFocus}
          onChange={(e) => {
            onChange(e.target.value);
            setIsOpen(true);
            setSelectedIndex(-1);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          className={`w-full bg-slate-950/90 text-slate-100 placeholder-slate-500 border border-slate-700/80 rounded-lg pl-9 pr-8 focus:outline-hidden focus:border-sky-500 focus:ring-1 focus:ring-sky-500/50 transition-all font-mono ${
            compact ? 'py-1.5 text-xs' : 'py-2 text-sm'
          }`}
        />

        {value && (
          <button
            type="button"
            onClick={clearInput}
            aria-label="Limpiar búsqueda"
            className="absolute right-2.5 text-slate-400 hover:text-slate-200 transition-colors p-0.5"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Autocomplete suggestions dropdown */}
      {isOpen && (
        <div className="absolute top-full left-0 right-0 mt-1 z-50 bg-slate-900/98 backdrop-blur-md border border-slate-700 rounded-xl shadow-2xl max-h-80 overflow-y-auto divide-y divide-slate-800/80">
          <div className="px-3 py-1.5 bg-slate-950/60 flex items-center justify-between text-[10px] text-slate-400 font-mono">
            <span>
              {query
                ? `${filteredSymbols.length} pares encontrados para "${query}"`
                : `Sugerencias rápidas (${safeSymbols.length} pares disponibles)`}
            </span>
            <span className="hidden sm:inline">Usa ↑ ↓ y Enter para seleccionar</span>
          </div>

          {suggestions.length === 0 ? (
            <div className="p-4 text-center text-xs text-slate-400">
              No se encontraron pares para &quot;<span className="text-slate-200">{value}</span>&quot;
            </div>
          ) : (
            suggestions.map((sym, idx) => {
              const isSelected = idx === selectedIndex;
              const meta = safeMeta[sym];
              const isAlreadyActive = safeActive.includes(sym);
              const sugg = meta?.suggested_timeframe;
              const session = meta?.session;

              return (
                <div
                  key={sym}
                  id={`autocomplete-item-${sym}`}
                  onClick={() => handleSelect(sym)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`px-3 py-2.5 cursor-pointer flex items-center justify-between transition-colors ${
                    isSelected ? 'bg-sky-950/70 border-l-4 border-sky-400 pl-2' : 'hover:bg-slate-800/60'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="flex flex-col">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-slate-100 font-mono tracking-wide">
                          {highlightMatch(sym, query)}
                        </span>
                        {meta?.category && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                            {meta.category}
                          </span>
                        )}
                        {isAlreadyActive && (
                          <span className="flex items-center gap-1 text-[10px] text-emerald-400 bg-emerald-950/50 border border-emerald-800/50 px-1.5 py-0.2 rounded">
                            <CheckCircle2 className="w-2.5 h-2.5" /> En Monitor
                          </span>
                        )}
                      </div>

                      {/* Details row: Session hours + Deep Search suggestion */}
                      <div className="flex items-center gap-3 mt-1 text-[11px] text-slate-400 flex-wrap">
                        {session && (
                          <span
                            className={`flex items-center gap-1 font-mono ${
                              session.isActive ? 'text-emerald-400' : 'text-amber-400/80'
                            }`}
                          >
                            <Clock className="w-3 h-3" />
                            {session.startTime}-{session.endTime}
                            <span className="text-[9px] opacity-75">
                              ({session.isActive ? 'Abierto' : 'Inactivo'})
                            </span>
                          </span>
                        )}

                        {sugg ? (
                          <span className="flex items-center gap-1 text-purple-300 bg-purple-950/40 border border-purple-800/40 px-1.5 py-0.5 rounded text-[10px] font-medium">
                            <Sparkles className="w-2.5 h-2.5 text-purple-400" />
                            Sug: {sugg.timeframe_str} ({sugg.avg_r >= 0 ? `+${sugg.avg_r.toFixed(1)}` : sugg.avg_r.toFixed(1)}R) • {sugg.win_rate.toFixed(0)}% WR
                          </span>
                        ) : (
                          <span className="text-slate-500 text-[10px]">🔬 Sin prueba reciente</span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 ml-3">
                    <button
                      type="button"
                      className="text-xs px-2.5 py-1 rounded bg-sky-600/30 hover:bg-sky-600 text-sky-300 hover:text-white transition-colors border border-sky-500/40 flex items-center gap-1 font-medium"
                    >
                      <span>Seleccionar</span>
                      <ChevronRight className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
};
