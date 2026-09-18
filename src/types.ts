export interface AccountInfo {
  connected: boolean;
  balance: number;
  equity: number;
  margin: number;
  freeMargin: number;
  profit: number;
  currency: string;
  server: string;
  login: string;
}

export interface BotStatus {
  isRunning: boolean;
  activePairs: string[];
  currentStrategy: string;
  mode: "LIVE" | "DEMO" | "BACKTEST";
  uptimeSeconds: number;
}

export interface DeepSearchResultItem {
  id?: string;
  symbol: string;
  resolved_symbol?: string;
  timeframe: string | number;
  timeframe_str?: string;
  trades_count?: number;
  trades?: number;
  wins?: number;
  losses?: number;
  win_rate: number;
  win_rate_confidence?: number;
  avg_r_multiple?: number;
  avg_r?: number;
  profit_factor?: number;
  expected_value?: number;
  max_drawdown_pct?: number;
  score: number;
  strategy: string;
  verdict?: string;
  category?: string;
  updated_at?: number;
  selected?: boolean;
}

export interface SymbolMetadata {
  symbol: string;
  category: string;
  session: {
    startTime: string;
    endTime: string;
    isActive: boolean;
  };
  suggested_timeframe: {
    timeframe_str: string;
    timeframe_val: number;
    avg_r: number;
    win_rate: number;
    win_rate_confidence: number;
    trades: number;
    strategy: string;
  } | null;
  suggested_strategy: string;
  lot: number;
  risk_pct: number;
  timeframe: string;
  strategy: string;
  isActive: boolean;
}

export interface StrategySummaryItem {
  strategy: string;
  symbols_count: number;
  total_trades: number;
  total_wins: number;
  win_rate: number;
  win_rate_confidence: number;
  avg_r: number;
}

export interface BestPerSymbolItem {
  symbol: string;
  winning_strategy: string;
  optimal_timeframe: string;
  timeframe_val: number;
  win_rate: number;
  win_rate_confidence: number;
  avg_r: number;
  trades: number;
  category: string;
  tested_strategies_count: number;
}

export interface MRChangeItem {
  parameter: string;
  old_value: string | number;
  new_value: string | number;
  difference: string;
  description: string;
}

export interface MRChangelogEntry {
  mr_id: string;
  timestamp: string;
  symbol: string;
  strategy: string;
  source: string;
  summary: string;
  changes: MRChangeItem[];
  avoid_patterns: string[];
  risk_advice: string;
}

export interface SystemLog {
  id: string;
  timestamp: string;
  level: "INFO" | "SUCCESS" | "WARNING" | "ERROR" | "AI";
  message: string;
}

export interface ConfigData {
  login: number;
  password?: string;
  server: string;
  path?: string;
  symbol_suffix?: string;
  magic_number: number;
  max_slippage: number;
  max_reentries: number;
  selected_strategy: string;
  ai_enabled: boolean;
  ai_provider: string;
  ai_api_key?: string;
  ai_model: string;
  ai_base_url?: string;
  ai_thinking_enabled?: boolean;
  ai_thinking_budget: number;
  active_symbols?: string[];
  license_key?: string;
}

export interface MT5StatusInfo {
  connected: boolean;
  terminal_running: boolean;
  platform_supported: boolean;
  message: string;
  account?: AccountInfo;
}
