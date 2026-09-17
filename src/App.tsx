import React, { useState, useEffect, useRef } from 'react';
import { Header } from './components/Header';
import { DeepSearch } from './components/DeepSearch';
import { MRChangelogModal } from './components/MRChangelogModal';
import { AccountInfo, BotStatus, DeepSearchResultItem, MRChangelogEntry, SystemLog } from './types';
import { Play, Square, Terminal, Shield, Sparkles, RefreshCw } from 'lucide-react';

export function App() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null);
  const [tradesCount, setTradesCount] = useState<number>(0);
  const [deepSearchResults, setDeepSearchResults] = useState<DeepSearchResultItem[]>([]);
  const [changelogEntries, setChangelogEntries] = useState<MRChangelogEntry[]>([]);
  const [logs, setLogs] = useState<SystemLog[]>([]);
  
  const [isChangelogOpen, setIsChangelogOpen] = useState<boolean>(false);
  const [filterSymbolForChangelog, setFilterSymbolForChangelog] = useState<string | undefined>(undefined);
  const [isAiProcessing, setIsAiProcessing] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'deepsearch' | 'terminal'>('deepsearch');

  const logsEndRef = useRef<HTMLDivElement>(null);

  const addLog = (level: SystemLog['level'], message: string) => {
    const newLog: SystemLog = {
      id: `log-${Date.now()}-${Math.random()}`,
      timestamp: new Date().toLocaleTimeString(),
      level,
      message,
    };
    setLogs((prev) => [...prev.slice(-100), newLog]);
  };

  // Cargar estado inicial y resultados de backtest
  const loadInitialData = async () => {
    try {
      // 1. Estado de bot y cuenta
      const resStatus = await fetch('/api/status');
      if (resStatus.ok) {
        const data = await resStatus.json();
        setAccount(data.account);
        setBotStatus(data.bot);
        setTradesCount(data.trades_count || 0);
      }
    } catch (e) {
      // Si FastAPI local no está corriendo, usar fallback simulado para UI
      setAccount({
        connected: false,
        balance: 10000.0,
        equity: 10000.0,
        margin: 0.0,
        freeMargin: 10000.0,
        profit: 0.0,
        currency: 'USD',
        server: 'MetaQuotes-Demo',
        login: '12345678',
      });
      setBotStatus({
        isRunning: false,
        activePairs: ['EURUSD', 'GBPUSD', 'USDCAD', 'USDJPY', 'AUDUSD'],
        currentStrategy: 'ai_strategy',
        mode: 'DEMO',
        uptimeSeconds: 0,
      });
    }

    // 2. Resultados de Deep Search
    try {
      const resDS = await fetch('/api/deep-search/results');
      if (resDS.ok) {
        const data = await resDS.json();
        setDeepSearchResults(data.results || []);
      }
    } catch (e) {
      // Fallback
    }

    // 3. Changelog
    try {
      const resCL = await fetch('/api/changelog');
      if (resCL.ok) {
        const data = await resCL.json();
        setChangelogEntries(data.changelog || []);
      }
    } catch (e) {
      // Fallback
    }
  };

  useEffect(() => {
    loadInitialData();
    addLog('INFO', 'Interfaz React conectada al subsistema de control.');

    // Conectar WebSocket si está disponible
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(wsUrl);
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'SYSTEM_LOG' && msg.log) {
            setLogs((prev) => [...prev.slice(-100), msg.log]);
          }
        } catch (err) {
          // ignore
        }
      };
    } catch (e) {
      // ignore
    }

    return () => {
      if (ws) ws.close();
    };
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // Enviar a IA para aprendizaje
  const handleSendToAI = async (selectedItems: DeepSearchResultItem[]) => {
    if (selectedItems.length === 0) return;
    setIsAiProcessing(true);
    addLog('AI', `🧠 Enviando ${selectedItems.length} pares al motor de aprendizaje IA & Síntesis Cuantitativa...`);

    try {
      const res = await fetch('/api/ai/learn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: selectedItems,
          default_strategy: botStatus?.currentStrategy || 'ai_strategy',
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Error en aprendizaje');
      }

      const data = await res.json();
      addLog('SUCCESS', `✅ Aprendizaje completado para ${data.count} pares. Parámetros modulados y registrados en MR Changelog.`);

      // Recargar changelog y abrir modal
      const resCL = await fetch('/api/changelog');
      if (resCL.ok) {
        const clData = await resCL.json();
        setChangelogEntries(clData.changelog || []);
      }
      setIsChangelogOpen(true);
    } catch (e: any) {
      addLog('ERROR', `❌ Error ejecutando aprendizaje IA: ${e.message}`);
    } finally {
      setIsAiProcessing(false);
    }
  };

  // Montar símbolos
  const handleMountSymbols = async (symbols: string[]) => {
    addLog('INFO', `Montando ${symbols.length} pares seleccionados en configuración activa...`);
    try {
      const res = await fetch('/api/mount-symbols', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols }),
      });
      if (res.ok) {
        addLog('SUCCESS', `✅ Pares montados exitosamente: ${symbols.join(', ')}`);
        if (botStatus) {
          setBotStatus({ ...botStatus, activePairs: symbols });
        }
      }
    } catch (e: any) {
      addLog('ERROR', `Error al montar símbolos: ${e.message}`);
    }
  };

  const handleOpenChangelog = (symbol?: string) => {
    setFilterSymbolForChangelog(symbol);
    setIsChangelogOpen(true);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-purple-500/30 selection:text-purple-200">
      {/* 1. Header Global con Métricas */}
      <Header account={account} botStatus={botStatus} tradesCount={tradesCount} />

      {/* 2. Main Content Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 md:p-6 space-y-4">
        {/* Navigation Tabs */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveTab('deepsearch')}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === 'deepsearch'
                  ? 'bg-purple-600 text-white shadow-lg shadow-purple-600/20'
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              Deep Search & IA
            </button>
            <button
              onClick={() => setActiveTab('terminal')}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === 'terminal'
                  ? 'bg-purple-600 text-white shadow-lg shadow-purple-600/20'
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              <Terminal className="w-3.5 h-3.5" />
              Consola del Bot ({logs.length})
            </button>
          </div>

          <div className="text-xs text-slate-500 font-mono flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-indigo-500 animate-ping" />
            Vite + React SPA Engine
          </div>
        </div>

        {/* Tab 1: Deep Search */}
        {activeTab === 'deepsearch' && (
          <div className="animate-fadeIn">
            <DeepSearch
              results={deepSearchResults}
              isLoading={false}
              onSendToAI={handleSendToAI}
              onMountSymbols={handleMountSymbols}
              onOpenChangelog={handleOpenChangelog}
              isAiProcessing={isAiProcessing}
            />
          </div>
        )}

        {/* Tab 2: Terminal Logs */}
        {activeTab === 'terminal' && (
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-xl flex flex-col h-[500px] animate-fadeIn">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
              <div className="flex items-center gap-2 text-xs text-slate-300 font-semibold">
                <Terminal className="w-4 h-4 text-purple-400" />
                Terminal de Eventos y Ejecución en Vivo
              </div>
              <button
                onClick={() => setLogs([])}
                className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors"
              >
                Limpiar Terminal
              </button>
            </div>

            <div className="flex-1 overflow-y-auto font-mono text-xs space-y-1.5 pr-2">
              {logs.map((log) => {
                const color =
                  log.level === 'SUCCESS'
                    ? 'text-emerald-400'
                    : log.level === 'ERROR'
                    ? 'text-rose-400'
                    : log.level === 'AI'
                    ? 'text-purple-400 font-semibold'
                    : log.level === 'WARNING'
                    ? 'text-amber-400'
                    : 'text-slate-300';

                return (
                  <div key={log.id} className="leading-relaxed flex items-start gap-2">
                    <span className="text-slate-600 select-none">[{log.timestamp}]</span>
                    <span className={`px-1.5 py-0.2 rounded text-[10px] font-bold bg-slate-800 select-none ${color}`}>
                      {log.level}
                    </span>
                    <span className={color}>{log.message}</span>
                  </div>
                );
              })}
              <div ref={logsEndRef} />
            </div>
          </div>
        )}
      </main>

      {/* Modal de MR Changelog */}
      <MRChangelogModal
        isOpen={isChangelogOpen}
        onClose={() => setIsChangelogOpen(false)}
        entries={changelogEntries}
        initialSymbol={filterSymbolForChangelog}
      />
    </div>
  );
}

export default App;
