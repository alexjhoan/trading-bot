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
  symbol: string;
  timeframe: string;
  trades_count: number;
  win_rate: number;
  avg_r_multiple: number;
  profit_factor: number;
  expected_value: number;
  max_drawdown_pct: number;
  score: number;
  strategy: string;
  selected?: boolean;
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
