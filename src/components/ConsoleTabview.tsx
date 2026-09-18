import React, { useState, useRef, useEffect } from 'react';
import {
  Terminal,
  Trash2,
  Filter,
  ArrowDownCircle,
  Copy,
  Check,
  Shield,
  Clock,
  AlertTriangle,
  XCircle,
  Circle,
  Sparkles
} from 'lucide-react';
import { SystemLog } from '../types';

interface ConsoleTabviewProps {
  activeSymbols: string[];
  logs: SystemLog[];
  onClearLogs?: () => void;
  symbolStatusMap?: Record<string, 'INACTIVE' | 'WAITING' | 'OPEN_ORDER' | 'WARNING' | 'ERROR'>;
}

const TAB_STATUS_CONFIG: Record<
  string,
  { icon: string; label: string; tooltip: string; color: string }
> = {
  INACTIVE: {
    icon: '⚪',
    label: 'Inactivo',
    tooltip: 'Bot inactivo / No está analizando este par actualmente',
    color: 'text-slate-400',
  },
  WAITING: {
    icon: '🟢',
    label: 'Activo / Esperando',
    tooltip: 'Bot activo y analizando el mercado en espera de confluencias',
    color: 'text-emerald-400',
  },
  OPEN_ORDER: {
    icon: '🛡️',
    label: 'Operación Activa',
    tooltip: 'Hay una orden abierta en este par; gestionando SL/TP',
    color: 'text-sky-400',
  },
  WARNING: {
    icon: '⚠️',
    label: 'Atención / Alerta',
    tooltip: 'Alerta / Fuera de horario de alta liquidez o spread alto',
    color: 'text-amber-400',
  },
  ERROR: {
    icon: '❌',
    label: 'Error',
    tooltip: 'Error en ejecución o conexión en este par',
    color: 'text-rose-400',
  },
};

export const ConsoleTabview: React.FC<ConsoleTabviewProps> = ({
  activeSymbols,
  logs,
  onClearLogs,
  symbolStatusMap = {},
}) => {
  const [currentTab, setCurrentTab] = useState<string>('🌐 General');
  const [logFilter, setLogFilter] = useState<string>('ALL');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const logContainerRef = useRef<HTMLDivElement>(null);

  // Tabs list: '🌐 General' + each active symbol
  const tabs = ['🌐 General', ...activeSymbols];

  // Auto scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll, currentTab]);

  // Filter logs by active tab and log level
  const filteredLogs = logs.filter((log) => {
    // Level filter
    if (logFilter !== 'ALL' && log.level !== logFilter) {
      return false;
    }
    // Tab filter
    if (currentTab === '🌐 General') {
      return true;
    }
    // Filter by symbol name in message
    const cleanSym = currentTab.replace(/^[^\w]+/, '').trim();
    return log.message.toLowerCase().includes(cleanSym.toLowerCase());
  });

  const handleCopyLogs = () => {
    const text = filteredLogs.map((l) => `[${l.timestamp}] [${l.level}] ${l.message}`).join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getStatusForSymbol = (sym: string) => {
    return symbolStatusMap[sym] || 'WAITING';
  };

  const currentTabStatus = currentTab !== '🌐 General' ? getStatusForSymbol(currentTab) : null;
  const statusInfo = currentTabStatus ? TAB_STATUS_CONFIG[currentTabStatus] : null;

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col h-full text-slate-100">
      {/* 1. Multiline Dynamic Tab Bar (Wrap) */}
      <div className="p-2.5 bg-slate-950 border-b border-slate-800">
        <div className="flex flex-wrap items-center gap-1.5 max-h-32 overflow-y-auto pr-1">
          {tabs.map((tab) => {
            const isTabActive = currentTab === tab;
            let badge = '🌐';
            let statusText = 'General';

            if (tab !== '🌐 General') {
              const st = getStatusForSymbol(tab);
              const conf = TAB_STATUS_CONFIG[st] || TAB_STATUS_CONFIG.WAITING;
              badge = conf.icon;
              statusText = conf.label;
            }

            return (
              <button
                key={tab}
                type="button"
                id={`tab-console-${tab}`}
                onClick={() => setCurrentTab(tab)}
                title={`${tab} - Estado: ${statusText}`}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all flex items-center gap-1.5 border ${
                  isTabActive
                    ? 'bg-sky-600 text-white border-sky-500 shadow-md shadow-sky-600/20 font-bold'
                    : 'bg-slate-900/80 text-slate-300 border-slate-800 hover:bg-slate-800 hover:text-slate-100'
                }`}
              >
                <span className="text-xs">{badge}</span>
                <span>{tab}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 2. Sub-Header: Active Tab Status & Log Controls */}
      <div className="px-4 py-2 bg-slate-900/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-sky-400" />
          <span className="font-bold text-slate-200 font-mono">{currentTab}</span>

          {statusInfo && (
            <span
              className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-800 border border-slate-700 ${statusInfo.color}`}
              title={statusInfo.tooltip}
            >
              <span>{statusInfo.icon}</span>
              <span>{statusInfo.label}</span>
            </span>
          )}

          <span className="text-slate-500 text-[11px] font-mono">
            ({filteredLogs.length} líneas)
          </span>
        </div>

        {/* Right Controls */}
        <div className="flex items-center gap-2">
          {/* Level Filter */}
          <div className="flex items-center gap-1">
            <Filter className="w-3 h-3 text-slate-500" />
            <select
              value={logFilter}
              onChange={(e) => setLogFilter(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded px-2 py-0.5 text-xs text-slate-300 focus:outline-hidden"
            >
              <option value="ALL">Todos los Niveles</option>
              <option value="INFO">INFO</option>
              <option value="SUCCESS">SUCCESS</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
              <option value="AI">AI</option>
            </select>
          </div>

          {/* Auto scroll toggle */}
          <button
            type="button"
            onClick={() => setAutoScroll(!autoScroll)}
            className={`px-2 py-0.5 rounded text-[11px] font-medium border flex items-center gap-1 ${
              autoScroll
                ? 'bg-sky-950 text-sky-300 border-sky-700'
                : 'bg-slate-800 text-slate-400 border-slate-700'
            }`}
          >
            <ArrowDownCircle className="w-3 h-3" />
            <span>Auto-scroll</span>
          </button>

          {/* Copy logs */}
          <button
            type="button"
            onClick={handleCopyLogs}
            className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            title="Copiar logs al portapapeles"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>

          {/* Clear logs */}
          {onClearLogs && (
            <button
              type="button"
              onClick={onClearLogs}
              className="p-1 rounded text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-colors"
              title="Limpiar logs"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* 3. Log Output Box */}
      <div
        ref={logContainerRef}
        className="flex-1 p-3 bg-slate-950/90 font-mono text-xs overflow-y-auto space-y-1 select-text max-h-[440px]"
      >
        {filteredLogs.length === 0 ? (
          <div className="text-slate-600 text-center py-12">
            No hay registros para este par en el filtro actual.
          </div>
        ) : (
          filteredLogs.map((log) => {
            let levelColor = 'text-slate-400';
            let badgeBg = 'bg-slate-800 text-slate-300';

            if (log.level === 'SUCCESS') {
              levelColor = 'text-emerald-300';
              badgeBg = 'bg-emerald-950 text-emerald-400 border border-emerald-800';
            } else if (log.level === 'WARNING') {
              levelColor = 'text-amber-300';
              badgeBg = 'bg-amber-950 text-amber-400 border border-amber-800';
            } else if (log.level === 'ERROR') {
              levelColor = 'text-rose-300';
              badgeBg = 'bg-rose-950 text-rose-400 border border-rose-800';
            } else if (log.level === 'AI') {
              levelColor = 'text-purple-300';
              badgeBg = 'bg-purple-950 text-purple-300 border border-purple-800';
            }

            return (
              <div
                key={log.id}
                className="flex items-start gap-2 hover:bg-slate-900/50 px-1 py-0.5 rounded leading-relaxed"
              >
                <span className="text-slate-500 shrink-0 text-[11px]">{log.timestamp}</span>
                <span
                  className={`text-[10px] font-bold px-1.5 rounded uppercase shrink-0 ${badgeBg}`}
                >
                  {log.level}
                </span>
                <span className={`break-words flex-1 ${levelColor}`}>{log.message}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
