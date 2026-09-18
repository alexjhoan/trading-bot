import React from 'react';
import { ShieldCheck, Activity, Database, Sparkles, Settings, Play, RefreshCw } from 'lucide-react';
import { AccountInfo, BotStatus, MT5StatusInfo } from '../types';

interface HeaderProps {
  account: AccountInfo | null;
  botStatus: BotStatus | null;
  tradesCount: number;
  mt5Status: MT5StatusInfo | null;
  onOpenConfig: () => void;
  onLaunchMT5: () => void;
  isLaunchingMT5: boolean;
  onTestAI?: () => void;
  onStrategyChange?: (strategy: string) => void;
}

export const Header: React.FC<HeaderProps> = ({
  account,
  botStatus,
  tradesCount,
  mt5Status,
  onOpenConfig,
  onLaunchMT5,
  isLaunchingMT5,
  onTestAI,
  onStrategyChange,
}) => {
  const isMT5Connected = account?.connected || mt5Status?.connected;

  return (
    <header className="bg-slate-900/95 border-b border-slate-800 px-6 py-3 backdrop-blur-md sticky top-0 z-30 flex flex-wrap items-center justify-between gap-4">
      {/* Brand & Strategy */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-linear-to-tr from-sky-600 via-indigo-600 to-purple-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
          <Activity className="w-5 h-5 text-white" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-bold text-slate-100 tracking-tight">
              🤖 Quant Trading Bot & Deep Search
            </h1>
            <span className="text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20 font-mono">
              v2.5
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
            <span className="flex items-center gap-1 font-medium text-amber-400">
              <Sparkles className="w-3.5 h-3.5" />
              {botStatus?.currentStrategy || 'simple_trend'}
            </span>
            <span className="text-slate-600">•</span>
            <span className="text-slate-400">{botStatus?.activePairs.length || 0} Pares Activos</span>
            <span className="text-slate-600">•</span>
            <span className="text-slate-400 flex items-center gap-1">
              <Database className="w-3 h-3 text-slate-500" />
              {tradesCount} Trades Registrados
            </span>
            {account?.server && (
              <>
                <span className="text-slate-600">•</span>
                <span className="text-slate-400 font-mono text-[11px]">{account.server}</span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Actions & Account Info Pill */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Test API IA button */}
        {onTestAI && (
          <button
            type="button"
            onClick={onTestAI}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-950/80 hover:bg-emerald-900 border border-emerald-700/60 text-emerald-300 text-xs font-bold transition-all shadow-xs"
            title="Probar conexión con Gemini API"
          >
            <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
            <span>🧠 Test API IA</span>
          </button>
        )}

        {/* Connection status button */}
        <div className="flex items-center gap-2">
          {isMT5Connected ? (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-950/40 border border-emerald-800/50 text-xs font-mono">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="font-semibold text-emerald-400">MT5 Conectado</span>
            </div>
          ) : (
            <button
              onClick={onLaunchMT5}
              disabled={isLaunchingMT5}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-300 text-xs font-medium transition-colors"
              title="Abrir terminal64.exe y conectar a la cuenta"
            >
              {isLaunchingMT5 ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Abriendo MT5...</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5" />
                  <span>Abrir / Conectar MT5</span>
                </>
              )}
            </button>
          )}

          {/* Botón de Configuración (config_window) */}
          <button
            onClick={onOpenConfig}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-semibold transition-colors"
            title="Abrir ventana de configuración (config.json)"
          >
            <Settings className="w-3.5 h-3.5 text-sky-400" />
            <span>Configuración</span>
          </button>
        </div>

        {/* Financial Metrics */}
        <div className="flex items-center gap-4 px-4 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/50 text-xs font-mono">
          <div>
            <div className="text-[10px] text-slate-400 uppercase font-sans font-medium">Balance</div>
            <div className="font-bold text-slate-200">${account?.balance?.toLocaleString() ?? '10,450.00'}</div>
          </div>
          <div className="w-px h-6 bg-slate-700/80" />
          <div>
            <div className="text-[10px] text-slate-400 uppercase font-sans font-medium">Equidad</div>
            <div className="font-bold text-emerald-400">${account?.equity?.toLocaleString() ?? '10,450.00'}</div>
          </div>
          <div className="w-px h-6 bg-slate-700/80" />
          <div>
            <div className="text-[10px] text-slate-400 uppercase font-sans font-medium">Margen Libre</div>
            <div className="font-bold text-slate-200">${account?.freeMargin?.toLocaleString() ?? '10,450.00'}</div>
          </div>
        </div>
      </div>
    </header>
  );
};
