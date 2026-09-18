import React, { useState, useEffect } from "react";
import {
  X,
  Settings,
  ShieldCheck,
  Cpu,
  Key,
  Play,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Globe,
  Bot,
  Zap,
  Check,
  FolderOpen,
} from "lucide-react";
import { ConfigData, MT5StatusInfo } from "../types";

interface ConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialConfig: ConfigData | null;
  onSave: (
    config: ConfigData,
    andConnect: boolean,
  ) => Promise<{ success: boolean; mt5_status?: MT5StatusInfo }>;
  isFirstSetup?: boolean;
}

const PROVIDER_PRESETS: Record<
  string,
  { default_model: string; models: string[]; default_url: string }
> = {
  "Google Gemini": {
    default_model: "gemini-3.6-flash",
    models: ["gemini-3.6-flash"],
    default_url: "https://generativelanguage.googleapis.com",
  },
  OpenAI: {
    default_model: "gpt-4o-mini",
    models: [
      "gpt-4o-mini",
      "gpt-4o",
      "o3-mini",
      "o1-mini",
      "gpt-4-turbo",
      "gpt-3.5-turbo",
    ],
    default_url: "https://api.openai.com/v1",
  },
  "Groq (Ultra Rápido)": {
    default_model: "llama-3.3-70b-versatile",
    models: [
      "llama-3.3-70b-versatile",
      "deepseek-r1-distill-llama-70b",
      "llama-3.1-8b-instant",
      "mixtral-8x7b-32768",
    ],
    default_url: "https://api.groq.com/openai/v1",
  },
  "OpenRouter (Multi-Proveedor)": {
    default_model: "google/gemini-2.5-flash",
    models: [
      "google/gemini-2.5-flash",
      "anthropic/claude-3.5-sonnet",
      "openai/gpt-4o-mini",
      "deepseek/deepseek-chat",
    ],
    default_url: "https://openrouter.ai/api/v1",
  },
  "Ollama / Localhost": {
    default_model: "llama3.2",
    models: ["llama3.2", "mistral", "deepseek-r1", "qwen2.5"],
    default_url: "http://localhost:11434/v1",
  },
};

export const ConfigModal: React.FC<ConfigModalProps> = ({
  isOpen,
  onClose,
  initialConfig,
  onSave,
  isFirstSetup = false,
}) => {
  const [formData, setFormData] = useState<ConfigData>({
    login: 43154893,
    password: "",
    server: "Weltrade-Demo",
    path: "C:/Program Files/MetaTrader 5 - bot/terminal64.exe",
    symbol_suffix: "",
    magic_number: 123456,
    max_slippage: 10,
    max_reentries: 0,
    selected_strategy: "ai_strategy",
    ai_enabled: true,
    ai_provider: "Google Gemini",
    ai_api_key: "",
    ai_model: "gemini-3.6-flash",
    ai_base_url: "https://generativelanguage.googleapis.com",
    ai_thinking_enabled: false,
    ai_thinking_budget: 128,
  });

  const [activeTab, setActiveTab] = useState<"mt5" | "ai">("mt5");
  const [availableModels, setAvailableModels] = useState<string[]>(
    PROVIDER_PRESETS["Google Gemini"].models,
  );

  // Estados de carga e interacción
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isTestingMT5, setIsTestingMT5] = useState<boolean>(false);
  const [isTestingAI, setIsTestingAI] = useState<boolean>(false);
  const [isFetchingModels, setIsFetchingModels] = useState<boolean>(false);
  const [showApiKey, setShowApiKey] = useState<boolean>(false);

  // Mensaje de feedback
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | "info";
    text: string;
    details?: string;
  } | null>(null);

  // Cargar configuración inicial
  useEffect(() => {
    if (initialConfig) {
      const provider = initialConfig.ai_provider || "Google Gemini";
      const preset =
        PROVIDER_PRESETS[provider] || PROVIDER_PRESETS["Google Gemini"];

      setFormData((prev) => ({
        ...prev,
        ...initialConfig,
        ai_provider: provider,
        ai_base_url: initialConfig.ai_base_url || preset.default_url,
        password: initialConfig.password || prev.password,
      }));

      if (preset && preset.models) {
        setAvailableModels(preset.models);
      }
    }
  }, [initialConfig]);

  if (!isOpen) return null;

  const handleChange = (field: keyof ConfigData, value: any) => {
    setFormData((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  // Cambio de proveedor de IA con actualización de preset
  const handleProviderChange = (newProvider: string) => {
    const preset =
      PROVIDER_PRESETS[newProvider] || PROVIDER_PRESETS["Google Gemini"];
    setAvailableModels(preset.models);

    setFormData((prev) => {
      // Si la URL actual es default de algún provider o está vacía, cambiar a la nueva sugerida
      const isDefaultOrEmpty =
        !prev.ai_base_url ||
        Object.values(PROVIDER_PRESETS).some(
          (p) => p.default_url === prev.ai_base_url,
        );

      return {
        ...prev,
        ai_provider: newProvider,
        ai_model: preset.default_model,
        ai_base_url: isDefaultOrEmpty ? preset.default_url : prev.ai_base_url,
      };
    });

    setFeedback({
      type: "info",
      text: `Proveedor cambiado a ${newProvider}. Modelos sugeridos cargados.`,
    });
  };

  // 1. Botón para actualizar las IA (por ejemplo locales como Ollama o remotas de Gemini / OpenAI)
  const handleFetchModels = async () => {
    setIsFetchingModels(true);
    setFeedback({
      type: "info",
      text: `⏳ Consultando modelos disponibles de ${formData.ai_provider}...`,
    });

    try {
      const res = await fetch("/api/ai/fetch-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: formData.ai_provider,
          api_key: formData.ai_api_key,
          base_url: formData.ai_base_url,
        }),
      });

      const data = await res.json();
      if (
        data.success &&
        Array.isArray(data.models) &&
        data.models.length > 0
      ) {
        setAvailableModels(data.models);
        // Si el modelo actual no está en la lista obtenida, seleccionar el primero
        if (!data.models.includes(formData.ai_model)) {
          handleChange("ai_model", data.models[0]);
        }
        setFeedback({
          type: "success",
          text:
            data.message ||
            `✅ ${data.models.length} modelos cargados exitosamente de ${formData.ai_provider}.`,
        });
      } else {
        setFeedback({
          type: "error",
          text:
            data.message ||
            "⚠️ No se obtuvieron modelos. Usando lista predeterminada.",
        });
      }
    } catch (err: any) {
      setFeedback({
        type: "error",
        text: `Error conectando con el servicio de IA: ${err.message || "Fallo de red"}`,
      });
    } finally {
      setIsFetchingModels(false);
    }
  };

  // 2. Botón para probar conexión con MT5
  const handleTestMT5 = async () => {
    if (!formData.login || formData.login <= 0) {
      setFeedback({
        type: "error",
        text: "❌ Ingrese un ID de Cuenta (Login) numérico válido.",
      });
      return;
    }
    if (!formData.password?.trim()) {
      setFeedback({
        type: "error",
        text: "❌ Ingrese la contraseña de su cuenta MT5.",
      });
      return;
    }
    if (!formData.server.trim()) {
      setFeedback({
        type: "error",
        text: "❌ Ingrese el Servidor del Bróker (ej: Weltrade-Demo).",
      });
      return;
    }

    setIsTestingMT5(true);
    setFeedback({
      type: "info",
      text: "⏳ Verificando credenciales y conectando con MetaTrader 5...",
    });

    try {
      const res = await fetch("/api/mt5/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          login: formData.login,
          password: formData.password,
          server: formData.server,
          path: formData.path,
        }),
      });

      const data = await res.json();
      if (data.success) {
        setFeedback({
          type: "success",
          text: data.message || "✅ MT5 Conectado exitosamente.",
          details: data.account
            ? `Balance: $${data.account.balance} | Bróker: ${data.broker}`
            : undefined,
        });
      } else {
        setFeedback({
          type: "error",
          text: data.message || "❌ Fallo en la autenticación de MT5.",
        });
      }
    } catch (err: any) {
      setFeedback({
        type: "error",
        text: `❌ Error al probar conexión con MT5: ${err.message || "Error de conexión"}`,
      });
    } finally {
      setIsTestingMT5(false);
    }
  };

  // 3. Botón para probar conexión con la IA
  const handleTestAI = async () => {
    // Si no es Ollama, requerir API key
    if (
      formData.ai_provider !== "Ollama / Localhost" &&
      !formData.ai_api_key?.trim()
    ) {
      setFeedback({
        type: "error",
        text: `❌ Ingrese una API Key para probar la conexión con ${formData.ai_provider}.`,
      });
      return;
    }

    setIsTestingAI(true);
    setFeedback({
      type: "info",
      text: `⏳ Conectando y enviando prompt de prueba a ${formData.ai_model} (${formData.ai_provider})...`,
    });

    try {
      const res = await fetch("/api/ai/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: formData.ai_provider,
          api_key: formData.ai_api_key,
          model_name: formData.ai_model,
          base_url: formData.ai_base_url,
        }),
      });

      const data = await res.json();
      if (data.success) {
        setFeedback({
          type: "success",
          text:
            data.message ||
            `✅ Conexión con IA establecida con éxito (${formData.ai_model}).`,
        });
      } else {
        setFeedback({
          type: "error",
          text: data.message || "❌ Error al conectar con el proveedor de IA.",
        });
      }
    } catch (err: any) {
      setFeedback({
        type: "error",
        text: `❌ Error al probar IA: ${err.message || "Error de red"}`,
      });
    } finally {
      setIsTestingAI(false);
    }
  };

  // Guardar configuración
  const handleSaveAndExit = async (andConnect: boolean) => {
    if (!formData.login || formData.login <= 0) {
      setFeedback({
        type: "error",
        text: "El ID de Cuenta (Login) es obligatorio.",
      });
      return;
    }
    if (!formData.server.trim()) {
      setFeedback({
        type: "error",
        text: "El Servidor del Bróker es obligatorio.",
      });
      return;
    }

    setIsSaving(true);
    setFeedback({
      type: "info",
      text: andConnect
        ? "Guardando configuración e intentando conectar MT5..."
        : "Guardando configuración...",
    });

    try {
      const result = await onSave(formData, andConnect);
      if (result.success) {
        if (andConnect && result.mt5_status) {
          if (result.mt5_status.connected) {
            setFeedback({
              type: "success",
              text: "✅ MT5 conectado con éxito y configuración guardada.",
            });
          } else {
            setFeedback({
              type: "info",
              text: `Configuración guardada. MT5: ${result.mt5_status.message}`,
            });
          }
        } else {
          setFeedback({
            type: "success",
            text: "✅ Configuración guardada en config.json.",
          });
        }
        setTimeout(() => {
          setIsSaving(false);
          onClose();
        }, 1200);
      } else {
        setFeedback({
          type: "error",
          text: "Ocurrió un problema al guardar la configuración.",
        });
        setIsSaving(false);
      }
    } catch (e: any) {
      setFeedback({ type: "error", text: e.message || "Error al guardar." });
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-md flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden animate-fadeIn">
        {/* Header Modal */}
        <div className="p-4 border-b border-slate-800 bg-slate-900/90 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              <Settings className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                Configuración del Sistema
                {isFirstSetup && (
                  <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                    Inicialización Requerida
                  </span>
                )}
              </h3>
              <p className="text-xs text-slate-400">
                Parámetros de conexión con MetaTrader 5 y motor de IA guardados
                en <code className="text-indigo-300">config.json</code>
              </p>
            </div>
          </div>

          {!isFirstSetup && (
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Banner de primer setup */}
        {isFirstSetup && (
          <div className="bg-amber-950/30 border-b border-amber-900/40 px-5 py-2.5 flex items-center gap-2 text-xs text-amber-200">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            <span>
              <strong>Atención:</strong> No se detectó{" "}
              <code className="text-amber-300">config.json</code>. Complete las
              credenciales de su cuenta de MetaTrader 5 para comenzar.
            </span>
          </div>
        )}

        {/* Tab Navigation */}
        <div className="flex border-b border-slate-800 bg-slate-950/50 px-5">
          <button
            onClick={() => setActiveTab("mt5")}
            className={`py-2.5 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${
              activeTab === "mt5"
                ? "border-indigo-500 text-indigo-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <ShieldCheck className="w-4 h-4" />
            MetaTrader 5 & Cuenta
          </button>
          <button
            onClick={() => setActiveTab("ai")}
            className={`py-2.5 px-4 text-xs font-semibold border-b-2 flex items-center gap-2 transition-colors ${
              activeTab === "ai"
                ? "border-indigo-500 text-indigo-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Cpu className="w-4 h-4" />
            Inteligencia Artificial & Modelos
          </button>
        </div>

        {/* Form Body */}
        <div className="p-5 overflow-y-auto space-y-4 flex-1">
          {/* TAB MT5 */}
          {activeTab === "mt5" && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    ID de Cuenta (Login) *
                  </label>
                  <input
                    type="number"
                    value={formData.login || ""}
                    onChange={(e) =>
                      handleChange("login", parseInt(e.target.value) || 0)
                    }
                    placeholder="43154893"
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Contraseña MT5 *
                  </label>
                  <input
                    type="password"
                    value={formData.password || ""}
                    onChange={(e) => handleChange("password", e.target.value)}
                    placeholder="••••••••"
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Servidor Bróker *
                  </label>
                  <input
                    type="text"
                    value={formData.server}
                    onChange={(e) => handleChange("server", e.target.value)}
                    placeholder="Weltrade-Demo"
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Sufijo de Símbolos (ej: _r o .m)
                  </label>
                  <input
                    type="text"
                    value={formData.symbol_suffix || ""}
                    onChange={(e) =>
                      handleChange("symbol_suffix", e.target.value)
                    }
                    placeholder="_r"
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Ruta terminal64.exe (para abrir MT5 automáticamente)
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={formData.path || ""}
                    onChange={(e) => handleChange("path", e.target.value)}
                    placeholder="C:/Program Files/MetaTrader 5 - bot/terminal64.exe"
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"
                  />
                  <FolderOpen className="w-3.5 h-3.5 text-slate-500 absolute right-3 top-2.5 pointer-events-none" />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Magic Number
                  </label>
                  <input
                    type="number"
                    value={formData.magic_number}
                    onChange={(e) =>
                      handleChange(
                        "magic_number",
                        parseInt(e.target.value) || 0,
                      )
                    }
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Max Slippage (pts)
                  </label>
                  <input
                    type="number"
                    value={formData.max_slippage}
                    onChange={(e) =>
                      handleChange(
                        "max_slippage",
                        parseInt(e.target.value) || 0,
                      )
                    }
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Reentradas Máx. (0-5)
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="5"
                    value={formData.max_reentries}
                    onChange={(e) =>
                      handleChange(
                        "max_reentries",
                        parseInt(e.target.value) || 0,
                      )
                    }
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              {/* Botón de Test MT5 en la sección */}
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleTestMT5}
                  disabled={isTestingMT5}
                  className="w-full py-2 px-4 rounded-xl bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/40 text-blue-300 font-semibold text-xs flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
                >
                  {isTestingMT5 ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Probando conexión con MT5...
                    </>
                  ) : (
                    <>
                      <ShieldCheck className="w-4 h-4 text-blue-400" />
                      🔍 Probar Conexión MT5
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* TAB IA */}
          {activeTab === "ai" && (
            <div className="space-y-4">
              {/* Selector de Proveedor */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1 flex items-center justify-between">
                    <span>Proveedor de IA</span>
                    {formData.ai_provider === "Ollama / Localhost" && (
                      <span className="text-[10px] text-emerald-400 font-normal">
                        ⚡ Local (Sin API Key)
                      </span>
                    )}
                  </label>
                  <select
                    value={formData.ai_provider}
                    onChange={(e) => handleProviderChange(e.target.value)}
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="Google Gemini">
                      Google Gemini (Oficial)
                    </option>
                    <option value="OpenAI">OpenAI (ChatGPT / o3-mini)</option>
                    <option value="Groq (Ultra Rápido)">
                      Groq (Ultra Rápido)
                    </option>
                    <option value="OpenRouter (Multi-Proveedor)">
                      OpenRouter (Multi-Proveedor)
                    </option>
                    <option value="Ollama / Localhost">
                      Ollama / Localhost (Modelos Locales)
                    </option>
                  </select>
                </div>

                {/* Selección y Actualización de Modelos */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs font-medium text-slate-300">
                      Modelo de IA
                    </label>
                    {/* Botón para actualizar las IA (por ejemplo locales como Ollama) */}
                    <button
                      type="button"
                      onClick={handleFetchModels}
                      disabled={isFetchingModels}
                      title="Consultar modelos disponibles en vivo desde la API o servidor Ollama"
                      className="text-[11px] text-indigo-400 hover:text-indigo-300 font-medium flex items-center gap-1 transition-colors disabled:opacity-50"
                    >
                      <RefreshCw
                        className={`w-3 h-3 ${isFetchingModels ? "animate-spin" : ""}`}
                      />
                      Actualizar Modelos
                    </button>
                  </div>

                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <input
                        type="text"
                        list="models-datalist"
                        value={formData.ai_model}
                        onChange={(e) =>
                          handleChange("ai_model", e.target.value)
                        }
                        placeholder="Ej: llama3.2 o gemini-2.5-flash"
                        className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-indigo-500"
                      />
                      <datalist id="models-datalist">
                        {availableModels.map((m) => (
                          <option key={m} value={m} />
                        ))}
                      </datalist>
                    </div>

                    <button
                      type="button"
                      onClick={handleFetchModels}
                      disabled={isFetchingModels}
                      className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-750 border border-slate-700 text-slate-300 hover:text-white transition-colors text-xs flex items-center gap-1.5 shrink-0"
                    >
                      <RefreshCw
                        className={`w-3.5 h-3.5 ${isFetchingModels ? "animate-spin text-indigo-400" : ""}`}
                      />
                      <span className="hidden sm:inline">Refrescar</span>
                    </button>
                  </div>
                  <p className="text-[10px] text-slate-400 mt-1">
                    Puede escribir un modelo personalizado o seleccionar de la
                    lista sugerida / local.
                  </p>
                </div>
              </div>

              {/* Endpoint Base URL (Especialmente para Ollama o Proxies) */}
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1 flex items-center justify-between">
                  <span>URL Base del Proveedor / Endpoint</span>
                  <span className="text-[10px] text-slate-400 font-mono">
                    {formData.ai_provider === "Ollama / Localhost"
                      ? "http://localhost:11434/v1"
                      : "API Endpoint"}
                  </span>
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={formData.ai_base_url || ""}
                    onChange={(e) =>
                      handleChange("ai_base_url", e.target.value)
                    }
                    placeholder="https://generativelanguage.googleapis.com o http://localhost:11434/v1"
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"
                  />
                  <Globe className="w-3.5 h-3.5 text-slate-500 absolute right-3 top-2.5" />
                </div>
              </div>

              {/* API Key */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-medium text-slate-300">
                    API Key del Proveedor
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="text-[11px] text-slate-400 hover:text-slate-200"
                  >
                    {showApiKey ? "Ocultar" : "Mostrar"}
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={formData.ai_api_key || ""}
                    onChange={(e) => handleChange("ai_api_key", e.target.value)}
                    placeholder={
                      formData.ai_provider === "Ollama / Localhost"
                        ? "Opcional para Ollama Local (puede dejarse vacío)"
                        : "AIzaSy... / sk-..."
                    }
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                  <Key className="w-3.5 h-3.5 text-slate-500 absolute right-3 top-2.5" />
                </div>
              </div>

              {/* Estrategia y Thinking */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Estrategia Principal
                  </label>
                  <select
                    value={formData.selected_strategy}
                    onChange={(e) =>
                      handleChange("selected_strategy", e.target.value)
                    }
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="ai_strategy">
                      ai_strategy (Síntesis & Machine Learning)
                    </option>
                    <option value="forex">
                      forex (RSI + MACD + ATR Clásico)
                    </option>
                    <option value="scalping">scalping (Alta Frecuencia)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Thinking Budget (Tokens)
                  </label>
                  <input
                    type="number"
                    value={formData.ai_thinking_budget}
                    onChange={(e) =>
                      handleChange(
                        "ai_thinking_budget",
                        parseInt(e.target.value) || 0,
                      )
                    }
                    className="w-full text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              {/* Botón de Test IA en la sección */}
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleTestAI}
                  disabled={isTestingAI}
                  className="w-full py-2 px-4 rounded-xl bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/40 text-purple-300 font-semibold text-xs flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
                >
                  {isTestingAI ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Conectando y probando {formData.ai_model}...
                    </>
                  ) : (
                    <>
                      <Bot className="w-4 h-4 text-purple-400" />
                      🧠 Probar Conexión IA ({formData.ai_model})
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Feedback message */}
          {feedback && (
            <div
              className={`p-3 rounded-xl text-xs flex flex-col gap-1 transition-all ${
                feedback.type === "success"
                  ? "bg-emerald-950/40 text-emerald-300 border border-emerald-800/50"
                  : feedback.type === "error"
                    ? "bg-rose-950/40 text-rose-300 border border-rose-800/50"
                    : "bg-indigo-950/40 text-indigo-300 border border-indigo-800/50"
              }`}
            >
              <div className="flex items-center gap-2">
                {feedback.type === "success" ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : feedback.type === "error" ? (
                  <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                ) : (
                  <RefreshCw className="w-4 h-4 text-indigo-400 shrink-0 animate-spin" />
                )}
                <span className="font-medium">{feedback.text}</span>
              </div>
              {feedback.details && (
                <div className="text-[11px] text-slate-300 pl-6 font-mono">
                  {feedback.details}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer Actions: Botones de Prueba Rápida y Guardado */}
        <div className="p-4 bg-slate-950/90 border-t border-slate-800 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          {/* Botones de Pruebas Rápidas (MT5 y IA) */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={handleTestMT5}
              disabled={isTestingMT5 || isSaving}
              title="Verificar conexión directa con MetaTrader 5"
              className="text-xs font-semibold px-3 py-2 rounded-lg bg-blue-900/30 hover:bg-blue-800/40 border border-blue-700/50 text-blue-300 flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              {isTestingMT5 ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <ShieldCheck className="w-3.5 h-3.5 text-blue-400" />
              )}
              Probar MT5
            </button>

            <button
              type="button"
              onClick={handleTestAI}
              disabled={isTestingAI || isSaving}
              title="Enviar prompt de verificación al modelo de IA"
              className="text-xs font-semibold px-3 py-2 rounded-lg bg-purple-900/30 hover:bg-purple-800/40 border border-purple-700/50 text-purple-300 flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              {isTestingAI ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Bot className="w-3.5 h-3.5 text-purple-400" />
              )}
              Probar IA
            </button>
          </div>

          {/* Botones Guardar */}
          <div className="flex items-center gap-2 justify-end">
            {!isFirstSetup && (
              <button
                onClick={onClose}
                disabled={isSaving}
                className="text-xs font-semibold px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
              >
                Cancelar
              </button>
            )}

            <button
              onClick={() => handleSaveAndExit(false)}
              disabled={isSaving}
              className="text-xs font-semibold px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700 transition-colors"
            >
              Guardar
            </button>

            <button
              onClick={() => handleSaveAndExit(true)}
              disabled={isSaving}
              className="text-xs font-semibold px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white shadow-md shadow-indigo-600/20 flex items-center gap-1.5 transition-all"
            >
              {isSaving ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  Guardando...
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5" />
                  Guardar y Abrir MT5
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
