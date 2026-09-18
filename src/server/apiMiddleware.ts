import fs from 'fs';
import path from 'path';
import type { Plugin, ViteDevServer } from 'vite';

const ROOT_DIR = process.cwd();
const CONFIG_FILE = path.join(ROOT_DIR, 'config.json');
const BACKTEST_FILE = path.join(ROOT_DIR, 'backtest_results.json');
const TRADE_MEMORY_FILE = path.join(ROOT_DIR, 'trade_memory.json');

const TIMEFRAME_MAP: Record<number, string> = {
  1: 'M1',
  5: 'M5',
  15: 'M15',
  30: 'M30',
  16385: 'H1',
  16388: 'H4',
  16408: 'D1',
};

const TIMEFRAME_STR_TO_NUM: Record<string, number> = {
  M1: 1,
  M5: 5,
  M15: 15,
  M30: 30,
  H1: 16385,
  H4: 16388,
  D1: 16408,
};

function getSymbolCategory(symbol: string): string {
  const s = symbol.toUpperCase();
  if (s.includes('XAU') || s.includes('XAG') || s.includes('XPT') || s.includes('XPD') || s.includes('GOLD')) {
    return 'Metales';
  }
  if (s.includes('BTC') || s.includes('ETH') || s.includes('LTC') || s.includes('XRP') || s.includes('SOL')) {
    return 'Cripto';
  }
  if (s.includes('SPX') || s.includes('NDX') || s.includes('DJI') || s.includes('GER') || s.includes('JPX') || s.includes('HSI') || s.includes('STX')) {
    return 'Índices';
  }
  if (s.includes('XTI') || s.includes('XBR') || s.includes('OIL') || s.includes('GAS')) {
    return 'Energía';
  }
  if (s.includes('APPLE') || s.includes('MICROSOFT') || s.includes('TESLA') || s.includes('AMAZON') || s.includes('NVIDIA') || s.includes('META') || s.includes('COCA') || s.includes('BOEING')) {
    return 'Acciones';
  }
  return 'Forex';
}

function calculateVerdict(winRate: number, avgR: number, trades: number): string {
  if (trades < 5) return '🔬 Muestra Reducida';
  if (winRate >= 55 && avgR >= 0.4) return '🔥 Excelente';
  if (winRate >= 45 && avgR >= 0.1) return '✅ Aceptable';
  if (winRate >= 35 && avgR >= -0.2) return '⚠️ Precaución';
  return '❌ Rechazado';
}

function calculateScore(winRate: number, avgR: number, trades: number, confidence: number): number {
  const base = (winRate * 0.5) + (Math.max(0, avgR + 1.0) * 20.0) + (confidence * 0.2) + Math.min(trades, 25) * 0.4;
  return Math.round(base * 10) / 10;
}

function getSessionTimes(symbol: string): { startTime: string; endTime: string; isActive: boolean } {
  const s = symbol.toUpperCase();
  let startTime = '00:00';
  let endTime = '23:59';
  if (s.includes('JPY') || s.includes('AUD') || s.includes('NZD') || s.includes('JPX')) {
    startTime = '00:00';
    endTime = '14:00';
  } else if (s.includes('EUR') || s.includes('GBP') || s.includes('GER') || s.includes('CHF')) {
    startTime = '07:00';
    endTime = '18:00';
  } else if (s.includes('USD') || s.includes('CAD') || s.includes('SPX') || s.includes('NDX') || s.includes('DJI')) {
    startTime = '12:00';
    endTime = '22:00';
  }

  // Session activity check (UTC simulated)
  const now = new Date();
  const currentHour = now.getUTCHours();
  const [sh] = startTime.split(':').map(Number);
  const [eh] = endTime.split(':').map(Number);
  const isActive = currentHour >= sh && currentHour <= eh;

  return { startTime, endTime, isActive };
}

export function devApiPlugin(): Plugin {
  return {
    name: 'dev-api-middleware',
    configureServer(server: ViteDevServer) {
      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith('/api/')) {
          return next();
        }

        const parsedUrl = new URL(req.url, 'http://localhost:3000');
        const pathname = parsedUrl.pathname;
        const method = req.method || 'GET';

        const sendJson = (data: any, status = 200) => {
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.statusCode = status;
          res.end(JSON.stringify(data));
        };

        const readBody = (): Promise<any> => {
          return new Promise((resolve) => {
            let body = '';
            req.on('data', (chunk) => {
              body += chunk;
            });
            req.on('end', () => {
              try {
                resolve(body ? JSON.parse(body) : {});
              } catch {
                resolve({});
              }
            });
          });
        };

        try {
          // -------------------------------------------------------------
          // 1. GET /api/config
          // -------------------------------------------------------------
          if (pathname === '/api/config' && method === 'GET') {
            if (fs.existsSync(CONFIG_FILE)) {
              const raw = fs.readFileSync(CONFIG_FILE, 'utf-8');
              const cfg = JSON.parse(raw);
              return sendJson({
                exists: true,
                is_configured: Boolean(cfg.login && cfg.server),
                config: cfg,
              });
            }
            return sendJson({
              exists: false,
              is_configured: false,
              config: {},
            });
          }

          // -------------------------------------------------------------
          // 2. POST /api/config
          // -------------------------------------------------------------
          if (pathname === '/api/config' && method === 'POST') {
            const body = await readBody();
            let currentCfg: any = {};
            if (fs.existsSync(CONFIG_FILE)) {
              try {
                currentCfg = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
              } catch {
                currentCfg = {};
              }
            }
            const updated = { ...currentCfg, ...body };
            fs.writeFileSync(CONFIG_FILE, JSON.stringify(updated, null, 4), 'utf-8');
            return sendJson({
              success: true,
              message: 'Configuración guardada exitosamente.',
              config: updated,
            });
          }

          // -------------------------------------------------------------
          // 3. GET /api/status
          // -------------------------------------------------------------
          if (pathname === '/api/status' && method === 'GET') {
            let cfg: any = {};
            if (fs.existsSync(CONFIG_FILE)) {
              try {
                cfg = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
              } catch {
                cfg = {};
              }
            }
            let tradeCount = 0;
            if (fs.existsSync(TRADE_MEMORY_FILE)) {
              try {
                const tm = JSON.parse(fs.readFileSync(TRADE_MEMORY_FILE, 'utf-8'));
                tradeCount = Object.keys(tm).length;
              } catch {
                tradeCount = 0;
              }
            }
            const activePairs = cfg.active_symbols || cfg.symbols || [
              'AUDJPY_r', 'USDCAD_r', 'GEREUR_r', 'EURJPY_r', 'GBPUSD_r'
            ];

            return sendJson({
              account: {
                connected: true,
                balance: 10450.00,
                equity: 10450.00,
                margin: 0.00,
                freeMargin: 10450.00,
                profit: 450.00,
                currency: 'USD',
                server: cfg.server || 'Weltrade-Demo',
                login: String(cfg.login || '43154893'),
              },
              mt5: {
                connected: true,
                terminal_running: true,
                message: `Terminal MT5 conectada al broker ${cfg.server || 'Weltrade-Demo'}`,
                account: {
                  balance: 10450.00,
                  equity: 10450.00,
                  currency: 'USD',
                  server: cfg.server || 'Weltrade-Demo',
                },
              },
              bot: {
                isRunning: true,
                activePairs,
                currentStrategy: cfg.selected_strategy || 'simple_trend',
                mode: (cfg.server || '').toLowerCase().includes('demo') ? 'DEMO' : 'LIVE',
                uptimeSeconds: 3600,
              },
              trades_count: tradeCount,
            });
          }

          // -------------------------------------------------------------
          // 4. GET /api/mt5/status and POST /api/mt5/launch
          // -------------------------------------------------------------
          if (pathname === '/api/mt5/status' || pathname === '/api/mt5/launch') {
            return sendJson({
              connected: true,
              terminal_running: true,
              message: 'MetaTrader 5 terminal operativa y comunicando con el bot',
              account: {
                balance: 10450.00,
                equity: 10450.00,
                currency: 'USD',
                server: 'Weltrade-Demo',
              },
            });
          }

          // -------------------------------------------------------------
          // 5. GET /api/symbols
          // -------------------------------------------------------------
          if (pathname === '/api/symbols' && method === 'GET') {
            let cfg: any = {};
            if (fs.existsSync(CONFIG_FILE)) {
              try {
                cfg = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
              } catch {
                cfg = {};
              }
            }

            // Load backtest results to compute suggested timeframes and strategies
            let backtestCache: any[] = [];
            if (fs.existsSync(BACKTEST_FILE)) {
              try {
                const raw = JSON.parse(fs.readFileSync(BACKTEST_FILE, 'utf-8'));
                backtestCache = Array.isArray(raw) ? raw : Object.values(raw);
              } catch {
                backtestCache = [];
              }
            }

            const available: string[] = cfg.available_symbols || [
              'AUDUSD_r', 'EURCHF_r', 'EURGBP_r', 'EURJPY_r', 'EURUSD_r',
              'GBPCHF_r', 'GBPJPY_r', 'GBPUSD_r', 'NZDUSD_r', 'USDCAD_r',
              'USDCHF_r', 'USDJPY_r', 'AUDCAD_r', 'AUDCHF_r', 'AUDJPY_r',
              'AUDNZD_r', 'XAUUSD_r', 'BTCUSD_r', 'ETHUSD_r', 'SPXUSD_r'
            ];

            const active: string[] = cfg.active_symbols || cfg.symbols || [
              'AUDJPY_r', 'USDCAD_r', 'GEREUR_r', 'EURJPY_r', 'GBPUSD_r'
            ];

            const symbolMetadata: Record<string, any> = {};

            // Calculate suggestion for each available symbol
            for (const sym of available) {
              const baseSym = sym.replace(/_r$/i, '').toLowerCase();
              const matches = backtestCache.filter((r) => {
                const rSym = String(r.symbol || r.resolved_symbol || '').replace(/_r$/i, '').toLowerCase();
                return rSym === baseSym || rSym.startsWith(baseSym) || baseSym.startsWith(rSym);
              });

              let bestSugg: any = null;
              if (matches.length > 0) {
                // Pick best avg_r with trades >= 1
                const valid = matches.filter((m) => (m.trades || 0) >= 1 && !m.error && !m.cancelled);
                if (valid.length > 0) {
                  valid.sort((a, b) => (b.avg_r || 0) - (a.avg_r || 0));
                  const top = valid[0];
                  bestSugg = {
                    timeframe_str: TIMEFRAME_MAP[top.timeframe] || 'M15',
                    timeframe_val: top.timeframe || 15,
                    avg_r: top.avg_r || 0,
                    win_rate: top.win_rate || 0,
                    win_rate_confidence: top.win_rate_confidence || 0,
                    trades: top.trades || 0,
                    strategy: top.strategy || 'simple_trend',
                  };
                }
              }

              const session = getSessionTimes(sym);
              const category = getSymbolCategory(sym);

              symbolMetadata[sym] = {
                symbol: sym,
                category,
                session,
                suggested_timeframe: bestSugg,
                suggested_strategy: bestSugg ? bestSugg.strategy : 'simple_trend',
                lot: cfg.symbol_lots?.[sym] || 0.01,
                risk_pct: cfg.symbol_risk_pcts?.[sym] || 1.0,
                timeframe: cfg.symbol_timeframes?.[sym] || (bestSugg?.timeframe_str || 'M15'),
                strategy: cfg.symbol_strategies?.[sym] || (bestSugg?.strategy || 'simple_trend'),
                isActive: active.includes(sym),
              };
            }

            return sendJson({
              success: true,
              available_symbols: available,
              active_symbols: active,
              symbols_metadata: symbolMetadata,
              symbol_lots: cfg.symbol_lots || {},
              symbol_risk_pcts: cfg.symbol_risk_pcts || {},
              symbol_timeframes: cfg.symbol_timeframes || {},
              symbol_strategies: cfg.symbol_strategies || {},
              default_strategy: cfg.selected_strategy || 'simple_trend',
            });
          }

          // -------------------------------------------------------------
          // 6. POST /api/symbols/update
          // -------------------------------------------------------------
          if (pathname === '/api/symbols/update' && method === 'POST') {
            const body = await readBody();
            let cfg: any = {};
            if (fs.existsSync(CONFIG_FILE)) {
              try {
                cfg = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
              } catch {
                cfg = {};
              }
            }

            if (body.active_symbols) {
              cfg.active_symbols = body.active_symbols;
              cfg.symbols = body.active_symbols;
            }
            if (body.symbol_lots) {
              cfg.symbol_lots = { ...(cfg.symbol_lots || {}), ...body.symbol_lots };
            }
            if (body.symbol_risk_pcts) {
              cfg.symbol_risk_pcts = { ...(cfg.symbol_risk_pcts || {}), ...body.symbol_risk_pcts };
            }
            if (body.symbol_timeframes) {
              cfg.symbol_timeframes = { ...(cfg.symbol_timeframes || {}), ...body.symbol_timeframes };
            }
            if (body.symbol_strategies) {
              cfg.symbol_strategies = { ...(cfg.symbol_strategies || {}), ...body.symbol_strategies };
            }

            fs.writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 4), 'utf-8');
            return sendJson({ success: true, message: 'Símbolos actualizados correctamente', config: cfg });
          }

          // -------------------------------------------------------------
          // 7. GET /api/deep-search/results
          // -------------------------------------------------------------
          if (pathname === '/api/deep-search/results' && method === 'GET') {
            if (!fs.existsSync(BACKTEST_FILE)) {
              return sendJson({ success: true, count: 0, results: [] });
            }

            const raw = JSON.parse(fs.readFileSync(BACKTEST_FILE, 'utf-8'));
            const list: any[] = Array.isArray(raw) ? raw : Object.values(raw);

            const strategyQuery = parsedUrl.searchParams.get('strategy');
            const searchQuery = parsedUrl.searchParams.get('search')?.trim().toLowerCase();
            const tfQuery = parsedUrl.searchParams.get('timeframe');
            const limit = Number(parsedUrl.searchParams.get('limit') || 500);

            let filtered = list.filter((item) => {
              if (item.cancelled || item.error) return false;
              if (strategyQuery && strategyQuery !== 'all' && item.strategy !== strategyQuery) {
                return false;
              }
              if (searchQuery) {
                const sym = String(item.symbol || '').toLowerCase();
                if (!sym.includes(searchQuery)) return false;
              }
              if (tfQuery && tfQuery !== 'all') {
                const tfNum = TIMEFRAME_STR_TO_NUM[tfQuery] || Number(tfQuery);
                if (item.timeframe !== tfNum) return false;
              }
              return true;
            });

            // Map and augment
            const results = filtered.map((r, idx) => {
              const tfStr = TIMEFRAME_MAP[r.timeframe] || (r.timeframe ? `M${r.timeframe}` : 'M15');
              const wr = Number(r.win_rate || 0);
              const avgR = Number(r.avg_r || 0);
              const trades = Number(r.trades || 0);
              const confidence = Number(r.win_rate_confidence || wr);
              const verdict = calculateVerdict(wr, avgR, trades);
              const score = calculateScore(wr, avgR, trades, confidence);

              return {
                id: `ds-${r.symbol}-${r.strategy}-${r.timeframe}-${idx}`,
                symbol: r.symbol,
                resolved_symbol: r.resolved_symbol || r.symbol,
                strategy: r.strategy || 'simple_trend',
                timeframe: r.timeframe,
                timeframe_str: tfStr,
                bars_analyzed: r.bars_analyzed || 8000,
                trades,
                wins: r.wins || 0,
                losses: r.losses || 0,
                win_rate: wr,
                win_rate_confidence: confidence,
                avg_r: avgR,
                verdict,
                score,
                category: getSymbolCategory(r.symbol),
                updated_at: r.updated_at || Date.now(),
              };
            });

            return sendJson({
              success: true,
              count: results.length,
              results: results.slice(0, limit),
            });
          }

          // -------------------------------------------------------------
          // 8. GET /api/deep-search/comparison
          // -------------------------------------------------------------
          if (pathname === '/api/deep-search/comparison' && method === 'GET') {
            if (!fs.existsSync(BACKTEST_FILE)) {
              return sendJson({ success: true, strategies_summary: [], best_per_symbol: [] });
            }

            const raw = JSON.parse(fs.readFileSync(BACKTEST_FILE, 'utf-8'));
            const list: any[] = Array.isArray(raw) ? raw : Object.values(raw);
            const valid = list.filter((r) => !r.cancelled && !r.error);

            // Group by strategy
            const stratMap: Record<string, any[]> = {};
            const symbolMap: Record<string, any[]> = {};

            for (const item of valid) {
              const strat = item.strategy || 'simple_trend';
              const sym = item.symbol || item.resolved_symbol;
              if (!stratMap[strat]) stratMap[strat] = [];
              stratMap[strat].push(item);

              if (sym) {
                if (!symbolMap[sym]) symbolMap[sym] = [];
                symbolMap[sym].push(item);
              }
            }

            // Summary per strategy
            const strategiesSummary = Object.entries(stratMap).map(([strat, records]) => {
              const totalTrades = records.reduce((acc, r) => acc + (r.trades || 0), 0);
              const totalWins = records.reduce((acc, r) => acc + (r.wins || 0), 0);
              const uniqueSymbols = new Set(records.map((r) => r.symbol)).size;
              const winRate = totalTrades > 0 ? Math.round((totalWins / totalTrades) * 1000) / 10 : 0;
              const avgR = totalTrades > 0
                ? Math.round((records.reduce((acc, r) => acc + ((r.avg_r || 0) * (r.trades || 0)), 0) / totalTrades) * 100) / 100
                : 0;

              return {
                strategy: strat,
                symbols_count: uniqueSymbols,
                total_trades: totalTrades,
                total_wins: totalWins,
                win_rate: winRate,
                win_rate_confidence: Math.max(0, winRate - 4.5),
                avg_r: avgR,
              };
            });

            strategiesSummary.sort((a, b) => b.win_rate - a.win_rate || b.avg_r - a.avg_r);

            // Best per symbol
            const bestPerSymbol = Object.entries(symbolMap).map(([sym, records]) => {
              // find record with highest (avg_r, win_rate)
              const sorted = [...records].sort((a, b) => {
                const scoreA = calculateScore(a.win_rate || 0, a.avg_r || 0, a.trades || 0, a.win_rate_confidence || 0);
                const scoreB = calculateScore(b.win_rate || 0, b.avg_r || 0, b.trades || 0, b.win_rate_confidence || 0);
                return scoreB - scoreA;
              });
              const best = sorted[0];

              return {
                symbol: sym,
                winning_strategy: best.strategy || 'simple_trend',
                optimal_timeframe: TIMEFRAME_MAP[best.timeframe] || 'M15',
                timeframe_val: best.timeframe || 15,
                win_rate: best.win_rate || 0,
                win_rate_confidence: best.win_rate_confidence || 0,
                avg_r: best.avg_r || 0,
                trades: best.trades || 0,
                category: getSymbolCategory(sym),
                tested_strategies_count: new Set(records.map((r) => r.strategy)).size,
              };
            });

            bestPerSymbol.sort((a, b) => b.avg_r - a.avg_r);

            return sendJson({
              success: true,
              strategies_summary: strategiesSummary,
              best_per_symbol: bestPerSymbol,
            });
          }

          // -------------------------------------------------------------
          // 9. POST /api/mount-symbols
          // -------------------------------------------------------------
          if (pathname === '/api/mount-symbols' && method === 'POST') {
            const body = await readBody();
            let cfg: any = {};
            if (fs.existsSync(CONFIG_FILE)) {
              try {
                cfg = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
              } catch {
                cfg = {};
              }
            }
            cfg.active_symbols = body.symbols || [];
            cfg.symbols = body.symbols || [];
            fs.writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 4), 'utf-8');
            return sendJson({ success: true, symbols: cfg.active_symbols });
          }

          // -------------------------------------------------------------
          // 10. POST /api/deep-search/run
          // -------------------------------------------------------------
          if (pathname === '/api/deep-search/run' && method === 'POST') {
            const body = await readBody();
            return sendJson({
              success: true,
              message: `Deep Search completado para estrategia ${body.strategy || 'forex'} (${body.timeframe || 'Auto'}).`,
              progress: 100,
            });
          }

          // -------------------------------------------------------------
          // 11. GET /api/changelog
          // -------------------------------------------------------------
          if (pathname === '/api/changelog' && method === 'GET') {
            const symbol = parsedUrl.searchParams.get('symbol');
            const sampleLogs = [
              {
                id: 'mr-1',
                timestamp: new Date(Date.now() - 3600000).toLocaleString(),
                symbol: 'AUDJPY_r',
                change_type: 'OPTIMIZE_PARAMETERS',
                action: 'Ajuste de Stop Loss dinámico por volatilidad ATR y confirmación M15',
                reason: 'El backtest demostró que SL de 18 pips reduce pérdidas en falsos rompimientos asiáticos.',
                details: { old_sl: 25, new_sl: 18, win_rate_delta: '+4.2%' },
              },
              {
                id: 'mr-2',
                timestamp: new Date(Date.now() - 7200000).toLocaleString(),
                symbol: 'USDCAD_r',
                change_type: 'TIMEFRAME_SELECTION',
                action: 'Cambio de timeframe a M15 con filtro de tendencia EMA 200',
                reason: 'Deep Search detectó mayor expectativa (+1.42R) frente a M5 (-0.12R).',
                details: { timeframe: 'M15', avg_r: '+1.42R' },
              },
              {
                id: 'mr-3',
                timestamp: new Date(Date.now() - 14400000).toLocaleString(),
                symbol: 'EURJPY_r',
                change_type: 'PATTERN_RECOGNITION',
                action: 'Inyección de regla heurística: Descartar entradas si RSI > 72 en Londres',
                reason: 'Evita comprar en techos de liquidez institucional.',
                details: { rsi_max: 72, expected_profit: '+8.6%' },
              },
            ];

            const filtered = symbol
              ? sampleLogs.filter((l) => l.symbol.toLowerCase() === symbol.toLowerCase())
              : sampleLogs;

            return sendJson({ success: true, count: filtered.length, changelog: filtered });
          }

          // -------------------------------------------------------------
          // 12. POST /api/ai/learn
          // -------------------------------------------------------------
          if (pathname === '/api/ai/learn' && method === 'POST') {
            const body = await readBody();
            const items = body.items || [];
            return sendJson({
              success: true,
              count: items.length,
              message: `Aprendizaje IA completado con éxito para ${items.length} pares. Nuevas reglas heurísticas inyectadas al MR Changelog.`,
              results: items.map((it: any) => ({
                symbol: it.symbol,
                strategy: it.strategy,
                rule: `Filtro adaptativo generado para ${it.symbol} en TF ${it.timeframe_str || 'M15'}: Aumentar ratio riesgo/beneficio a 1:2.4`,
              })),
            });
          }

          // Fallback 404 for unknown api
          return sendJson({ error: 'Endpoint no encontrado' }, 404);
        } catch (err: any) {
          return sendJson({ error: err.message || 'Error interno' }, 500);
        }
      });
    },
  };
}
