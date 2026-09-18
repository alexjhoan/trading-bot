import React, { useState, useEffect, useRef } from "react";
import { Header } from "./components/Header";
import { DeepSearch } from "./components/DeepSearch";
import { MRChangelogModal } from "./components/MRChangelogModal";
import { ConfigModal } from "./components/ConfigModal";
import {
  AccountInfo,
  BotStatus,
  DeepSearchResultItem,
  MRChangelogEntry,
  SystemLog,
  ConfigData,
  MT5StatusInfo,
} from "./types";
import { Terminal, Sparkles, AlertCircle } from "lucide-react";

export function App() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null);
  const [tradesCount, setTradesCount] = useState<number>(0);
  const [deepSearchResults, setDeepSearchResults] = useState<
    DeepSearchResultItem[]
  >([]);
  const [changelogEntries, setChangelogEntries] = useState<MRChangelogEntry[]>(
    [],
  );
  const [logs, setLogs] = useState<SystemLog[]>([]);

  // MT5 y Configuración
  const [configData, setConfigData] = useState<ConfigData | null>(null);
  const [mt5Status, setMt5Status] = useState<MT5StatusInfo | null>(null);
  const [isConfigModalOpen, setIsConfigModalOpen] = useState<boolean>(false);
  const [isFirstSetup, setIsFirstSetup] = useState<boolean>(false);
  const [isLaunchingMT5, setIsLaunchingMT5] = useState<boolean>(false);

  // Modales y Tabs
  const [isChangelogOpen, setIsChangelogOpen] = useState<boolean>(false);
  const [filterSymbolForChangelog, setFilterSymbolForChangelog] = useState<
    string | undefined
  >(undefined);
  const [isAiProcessing, setIsAiProcessing] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<"deepsearch" | "terminal">(
    "deepsearch",
  );

  const logsEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const wsReconnectTimeoutRef = useRef<any>(null);

  const addLog = (level: SystemLog["level"], message: string) => {
    const newLog: SystemLog = {
      id: `log-${Date.now()}-${Math.random()}`,
      timestamp: new Date().toLocaleTimeString(),
      level,
      message,
    };
    setLogs((prev) => [...prev.slice(-100), newLog]);
  };

  // -----------------------------------------------------------------
  // 1. WebSocket Resiliente sin errores no controlados en consola
  // -----------------------------------------------------------------
  const setupWebSocket = () => {
    // Si ya existe conexión abierta o conectándose, evitar duplicar
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    try {
      const isLocal =
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1";
      // En entorno local conectamos directamente a ws://127.0.0.1:8000/ws para evitar overhead y ECONNABORTED del proxy Vite
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = isLocal
        ? `ws://${window.location.hostname}:8000/ws`
        : `${protocol}//${window.location.host}/ws`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        // Conexión exitosa
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "SYSTEM_LOG" && msg.log) {
            setLogs((prev) => [...prev.slice(-100), msg.log]);
          }
        } catch {
          // Ignorar mensajes mal formateados
        }
      };

      ws.onerror = () => {
        // Error silencioso, manejado en onclose
      };

      ws.onclose = () => {
        wsRef.current = null;
        // Reintentar de forma suave después de 5 segundos
        clearTimeout(wsReconnectTimeoutRef.current);
        wsReconnectTimeoutRef.current = setTimeout(() => {
          setupWebSocket();
        }, 5000);
      };
    } catch {
      // Capturar cualquier error síncrono al instanciar
    }
  };

  // -----------------------------------------------------------------
  // 2. Comprobar config.json y estado de MT5 antes de iniciar
  // -----------------------------------------------------------------
  const checkConfigAndMT5 = async () => {
    try {
      addLog(
        "INFO",
        "Verificando archivo config.json y credenciales de usuario...",
      );
      const resConfig = await fetch("/api/config");
      if (resConfig.ok) {
        const configJson = await resConfig.json();
        setConfigData(configJson.config);

        // Si config.json no existe o no tiene login/servidor configurado, desplegar modal obligatorio
        if (!configJson.exists || !configJson.is_configured) {
          setIsFirstSetup(true);
          setIsConfigModalOpen(true);
          addLog(
            "WARNING",
            "No se detectó configuración completa de cuenta. Abriendo ventana de configuración.",
          );
          verifyAndLaunchMT5();
          return;
        } else {
          setIsFirstSetup(false);
          addLog(
            "SUCCESS",
            `Configuración cargada (Cuenta: ${configJson.config.login}, Servidor: ${configJson.config.server}).`,
          );

          // Verificar y abrir MT5
          await verifyAndLaunchMT5();
        }
      }
    } catch {
      // Si FastAPI local aún no responde
      addLog("WARNING", "Esperando conexión con el servidor Python local...");
    }
  };

  // -----------------------------------------------------------------
  // 3. Verificación y Apertura de MetaTrader 5
  // -----------------------------------------------------------------
  const verifyAndLaunchMT5 = async () => {
    setIsLaunchingMT5(true);
    addLog("INFO", "Verificando estado de MetaTrader 5 (MT5)...");

    try {
      const res = await fetch("/api/mt5/status");
      if (res.ok) {
        const data: MT5StatusInfo = await res.json();
        setMt5Status(data);

        if (data.connected) {
          addLog(
            "SUCCESS",
            `✅ ${data.message} Balance: $${data.account?.balance ?? 0}`,
          );
          if (data.account) {
            setAccount(data.account);
          }
        } else {
          // Si no está conectado, intentar abrir/conectar automáticamente
          addLog(
            "WARNING",
            `MT5 no conectado (${data.message}). Intentando arrancar terminal64.exe...`,
          );
          const launchRes = await fetch("/api/mt5/launch", { method: "POST" });
          if (launchRes.ok) {
            const launchData: MT5StatusInfo = await launchRes.json();
            setMt5Status(launchData);
            if (launchData.connected) {
              addLog(
                "SUCCESS",
                `🚀 MT5 iniciado y conectado exitosamente: ${launchData.message}`,
              );
              if (launchData.account) {
                setAccount(launchData.account);
              }
            } else {
              addLog("WARNING", `Aviso MT5: ${launchData.message}`);
            }
          }
        }
      }
    } catch (e: any) {
      addLog("ERROR", `Error al comunicar con MT5: ${e.message}`);
    } finally {
      setIsLaunchingMT5(false);
    }
  };

  // -----------------------------------------------------------------
  // 4. Carga de datos generales
  // -----------------------------------------------------------------
  const loadInitialData = async () => {
    try {
      const resStatus = await fetch("/api/status");
      if (resStatus.ok) {
        const data = await resStatus.json();
        setAccount(data.account);
        setBotStatus(data.bot);
        setTradesCount(data.trades_count || 0);
        if (data.mt5) {
          setMt5Status(data.mt5);
        }
      }
    } catch {
      // Fallback
    }

    try {
      const resDS = await fetch("/api/deep-search/results");
      if (resDS.ok) {
        const data = await resDS.json();
        setDeepSearchResults(data.results || []);
      }
    } catch {
      // Fallback
    }

    try {
      const resCL = await fetch("/api/changelog");
      if (resCL.ok) {
        const data = await resCL.json();
        setChangelogEntries(data.changelog || []);
      }
    } catch {
      // Fallback
    }
  };

  useEffect(() => {
    // 1. Iniciar chequeo de configuración y MT5
    checkConfigAndMT5();

    // 2. Cargar datos del bot
    loadInitialData();

    // 3. Conectar WebSocket de forma segura
    setupWebSocket();

    return () => {
      clearTimeout(wsReconnectTimeoutRef.current);
      if (wsRef.current) {
        const ws = wsRef.current;
        wsRef.current = null;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        try {
          if (
            ws.readyState === WebSocket.OPEN ||
            ws.readyState === WebSocket.CONNECTING
          ) {
            ws.close();
          }
        } catch {
          // ignore
        }
      }
    };
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // -----------------------------------------------------------------
  // 5. Guardar Configuración (desde ConfigModal)
  // -----------------------------------------------------------------
  const handleSaveConfig = async (
    newConfig: ConfigData,
    andConnect: boolean,
  ) => {
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...newConfig,
          connect_mt5: andConnect,
        }),
      });

      if (!res.ok) {
        throw new Error("Error al guardar configuración en servidor");
      }

      const resData = await res.json();
      setConfigData(newConfig);
      setIsFirstSetup(false);
      addLog(
        "SUCCESS",
        "✅ Configuración guardada correctamente en config.json.",
      );

      if (resData.mt5_status) {
        setMt5Status(resData.mt5_status);
        if (resData.mt5_status.connected && resData.mt5_status.account) {
          setAccount(resData.mt5_status.account);
          addLog("SUCCESS", "✅ Sesión MetaTrader 5 sincronizada y conectada.");
        }
      }

      // Recargar status general
      await loadInitialData();
      return { success: true, mt5_status: resData.mt5_status };
    } catch (err: any) {
      addLog("ERROR", `Error guardando configuración: ${err.message}`);
      return { success: false };
    }
  };

  // Enviar a IA para aprendizaje
  const handleSendToAI = async (selectedItems: DeepSearchResultItem[]) => {
    if (selectedItems.length === 0) return;
    setIsAiProcessing(true);
    addLog(
      "AI",
      `🧠 Enviando ${selectedItems.length} pares al motor de aprendizaje IA & Síntesis Cuantitativa...`,
    );

    try {
      const res = await fetch("/api/ai/learn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: selectedItems,
          default_strategy: botStatus?.currentStrategy || "ai_strategy",
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Error en aprendizaje");
      }

      const data = await res.json();
      addLog(
        "SUCCESS",
        `✅ Aprendizaje completado para ${data.count} pares. Parámetros modulados y registrados en MR Changelog.`,
      );

      const resCL = await fetch("/api/changelog");
      if (resCL.ok) {
        const clData = await resCL.json();
        setChangelogEntries(clData.changelog || []);
      }
      setIsChangelogOpen(true);
    } catch (e: any) {
      addLog("ERROR", `❌ Error ejecutando aprendizaje IA: ${e.message}`);
    } finally {
      setIsAiProcessing(false);
    }
  };

  // Montar símbolos
  const handleMountSymbols = async (symbols: string[]) => {
    addLog(
      "INFO",
      `Montando ${symbols.length} pares seleccionados en configuración activa...`,
    );
    try {
      const res = await fetch("/api/mount-symbols", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols }),
      });
      if (res.ok) {
        addLog(
          "SUCCESS",
          `✅ Pares montados exitosamente: ${symbols.join(", ")}`,
        );
        if (botStatus) {
          setBotStatus({ ...botStatus, activePairs: symbols });
        }
      }
    } catch (e: any) {
      addLog("ERROR", `Error al montar símbolos: ${e.message}`);
    }
  };

  const handleOpenChangelog = (symbol?: string) => {
    setFilterSymbolForChangelog(symbol);
    setIsChangelogOpen(true);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-purple-500/30 selection:text-purple-200">
      {/* 1. Header Global con Métricas y Botón de Configuración / MT5 */}
      <Header
        account={account}
        botStatus={botStatus}
        tradesCount={tradesCount}
        mt5Status={mt5Status}
        onOpenConfig={() => setIsConfigModalOpen(true)}
        onLaunchMT5={verifyAndLaunchMT5}
        isLaunchingMT5={isLaunchingMT5}
      />

      {/* 2. Main Content Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 md:p-6 space-y-4">
        {/* Banner si MT5 no está conectado */}
        {mt5Status && !mt5Status.connected && (
          <div className="bg-amber-950/20 border border-amber-800/40 rounded-xl p-3 flex items-center justify-between gap-3 text-xs text-amber-200 animate-fadeIn">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                <strong>Estado MetaTrader 5:</strong> {mt5Status.message}
              </span>
            </div>
            <button
              onClick={verifyAndLaunchMT5}
              disabled={isLaunchingMT5}
              className="px-3 py-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 font-semibold rounded-lg border border-amber-500/30 transition-colors shrink-0"
            >
              {isLaunchingMT5 ? "Iniciando..." : "Reintentar Conexión"}
            </button>
          </div>
        )}

        {/* Navigation Tabs */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveTab("deepsearch")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === "deepsearch"
                  ? "bg-purple-600 text-white shadow-lg shadow-purple-600/20"
                  : "bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800"
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              Deep Search & IA
            </button>
            <button
              onClick={() => setActiveTab("terminal")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === "terminal"
                  ? "bg-purple-600 text-white shadow-lg shadow-purple-600/20"
                  : "bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800"
              }`}
            >
              <Terminal className="w-3.5 h-3.5" />
              Consola del Bot ({logs.length})
            </button>
          </div>

          <div className="text-xs text-slate-500 font-mono flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            Backend FastAPI + MT5 Core
          </div>
        </div>

        {/* Tab 1: Deep Search */}
        {activeTab === "deepsearch" && (
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
        {activeTab === "terminal" && (
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
                  log.level === "SUCCESS"
                    ? "text-emerald-400"
                    : log.level === "ERROR"
                      ? "text-rose-400"
                      : log.level === "AI"
                        ? "text-purple-400 font-semibold"
                        : log.level === "WARNING"
                          ? "text-amber-400"
                          : "text-slate-300";

                return (
                  <div
                    key={log.id}
                    className="leading-relaxed flex items-start gap-2"
                  >
                    <span className="text-slate-600 select-none">
                      [{log.timestamp}]
                    </span>
                    <span
                      className={`px-1.5 py-0.2 rounded text-[10px] font-bold bg-slate-800 select-none ${color}`}
                    >
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

      {/* Modal de Configuración (ConfigWindow) */}
      <ConfigModal
        isOpen={isConfigModalOpen}
        onClose={() => {
          if (!isFirstSetup) {
            setIsConfigModalOpen(false);
          }
        }}
        initialConfig={configData}
        onSave={handleSaveConfig}
        isFirstSetup={isFirstSetup}
      />
    </div>
  );
}

export default App;
