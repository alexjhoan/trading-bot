import React, { useState } from 'react';
import { TrendingUp, TrendingDown, DollarSign, Calendar, Clock } from 'lucide-react';

interface StatsBarProps {
  winsCount?: number;
  winsAmount?: number;
  lossesCount?: number;
  lossesAmount?: number;
  netProfit?: number;
  initialPeriod?: 'Día' | 'Semana';
  initialTimeMode?: 'Hora Broker' | 'Hora Local';
  onFilterChange?: (period: 'Día' | 'Semana', timeMode: 'Hora Broker' | 'Hora Local') => void;
}

export const StatsBar: React.FC<StatsBarProps> = ({
  winsCount = 14,
  winsAmount = 780.50,
  lossesCount = 6,
  lossesAmount = -330.50,
  netProfit = 450.00,
  initialPeriod = 'Día',
  initialTimeMode = 'Hora Broker',
  onFilterChange,
}) => {
  const [period, setPeriod] = useState<'Día' | 'Semana'>(initialPeriod);
  const [timeMode, setTimeMode] = useState<'Hora Broker' | 'Hora Local'>(initialTimeMode);

  const handlePeriodChange = (newPeriod: 'Día' | 'Semana') => {
    setPeriod(newPeriod);
    if (onFilterChange) onFilterChange(newPeriod, timeMode);
  };

  const handleTimeModeChange = (newMode: 'Hora Broker' | 'Hora Local') => {
    setTimeMode(newMode);
    if (onFilterChange) onFilterChange(period, newMode);
  };

  const totalTrades = winsCount + lossesCount;
  const winRate = totalTrades > 0 ? ((winsCount / totalTrades) * 100).toFixed(1) : '0.0';

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-2.5 shadow-md flex flex-wrap items-center justify-between gap-3 text-xs">
      {/* 1. Selector de Filtros (Período & Horario) */}
      <div className="flex items-center gap-3 bg-slate-950 p-1.5 rounded-lg border border-slate-800">
        <div className="flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5 text-slate-400" />
          <div className="flex items-center rounded-md bg-slate-900 p-0.5 border border-slate-800">
            <button
              type="button"
              onClick={() => handlePeriodChange('Día')}
              className={`px-2 py-0.5 rounded text-[11px] font-bold transition-colors ${
                period === 'Día'
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Día
            </button>
            <button
              type="button"
              onClick={() => handlePeriodChange('Semana')}
              className={`px-2 py-0.5 rounded text-[11px] font-bold transition-colors ${
                period === 'Semana'
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Semana
            </button>
          </div>
        </div>

        <div className="flex items-center gap-1.5 border-l border-slate-800 pl-3">
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          <select
            value={timeMode}
            onChange={(e) => handleTimeModeChange(e.target.value as any)}
            className="bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-300 focus:outline-hidden"
          >
            <option value="Hora Broker">Hora Broker</option>
            <option value="Hora Local">Hora Local</option>
          </select>
        </div>
      </div>

      {/* 2. Estadísticas de Rendimiento */}
      <div className="flex items-center gap-4 flex-wrap flex-1 justify-end font-mono">
        {/* Positivas */}
        <div className="flex items-center gap-2 bg-emerald-950/40 border border-emerald-800/40 px-3 py-1.5 rounded-lg">
          <TrendingUp className="w-4 h-4 text-emerald-400" />
          <div>
            <div className="text-[10px] text-emerald-400/80 font-sans uppercase font-bold">
              Positivas ({winsCount})
            </div>
            <div className="text-xs font-bold text-emerald-300">+${winsAmount.toFixed(2)}</div>
          </div>
        </div>

        {/* Negativas */}
        <div className="flex items-center gap-2 bg-rose-950/40 border border-rose-800/40 px-3 py-1.5 rounded-lg">
          <TrendingDown className="w-4 h-4 text-rose-400" />
          <div>
            <div className="text-[10px] text-rose-400/80 font-sans uppercase font-bold">
              Negativas ({lossesCount})
            </div>
            <div className="text-xs font-bold text-rose-300">${lossesAmount.toFixed(2)}</div>
          </div>
        </div>

        {/* Balance Neto */}
        <div
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg border ${
            netProfit >= 0
              ? 'bg-sky-950/40 border-sky-800/50 text-sky-300'
              : 'bg-rose-950/40 border-rose-800/50 text-rose-300'
          }`}
        >
          <DollarSign className="w-4 h-4 text-sky-400" />
          <div>
            <div className="text-[10px] text-slate-400 font-sans uppercase font-bold">
              Neto {period} (WR: {winRate}%)
            </div>
            <div className="text-xs font-bold text-white">
              {netProfit >= 0 ? `+$${netProfit.toFixed(2)}` : `-$${Math.abs(netProfit).toFixed(2)}`}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
