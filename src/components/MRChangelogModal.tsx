import React, { useState } from 'react';
import { X, FileText, Calendar, Filter, Sparkles, AlertTriangle, ShieldCheck } from 'lucide-react';
import { MRChangelogEntry } from '../types';

interface MRChangelogModalProps {
  isOpen: boolean;
  onClose: () => void;
  entries: MRChangelogEntry[];
  initialSymbol?: string;
}

export const MRChangelogModal: React.FC<MRChangelogModalProps> = ({
  isOpen,
  onClose,
  entries,
  initialSymbol
}) => {
  if (!isOpen) return null;

  const [selectedSymbol, setSelectedSymbol] = useState<string>(initialSymbol || 'ALL');

  const symbols = ['ALL', ...Array.from(new Set(entries.map(e => e.symbol.toUpperCase())))];

  const filteredEntries = selectedSymbol === 'ALL'
    ? entries
    : entries.filter(e => e.symbol.toUpperCase() === selectedSymbol.toUpperCase());

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/90">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                MR Changelog - Registro de Modulación AI Strategy
              </h3>
              <p className="text-xs text-slate-400">
                Historial de adaptaciones dinámicas aprendidas del backtesting y registradas en <code className="text-purple-300">docs/AI_STRATEGY_CHANGELOG.md</code>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Filter Bar */}
        <div className="px-5 py-3 bg-slate-950/60 border-b border-slate-800 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-400" />
            <span className="text-xs font-medium text-slate-300">Filtrar por Par:</span>
            <select
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="text-xs px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 focus:outline-none focus:border-purple-500"
            >
              {symbols.map(s => (
                <option key={s} value={s}>
                  {s === 'ALL' ? 'Todos los Pares' : s}
                </option>
              ))}
            </select>
          </div>

          <div className="text-xs text-purple-300 font-medium">
            Mostrando {filteredEntries.length} Registros MR
          </div>
        </div>

        {/* Entries List */}
        <div className="p-5 overflow-y-auto space-y-4 flex-1">
          {filteredEntries.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <FileText className="w-8 h-8 mx-auto mb-2 text-slate-600" />
              <p className="text-sm">No hay registros de cambios en el MR Changelog para el filtro seleccionado.</p>
              <p className="text-xs mt-1">Usa 'Enviar a IA (Aprendizaje)' en Deep Search para modular parámetros.</p>
            </div>
          ) : (
            filteredEntries.map((entry, idx) => (
              <div
                key={`${entry.mr_id}-${idx}`}
                className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-4 space-y-3 hover:border-slate-700/80 transition-colors"
              >
                {/* Top Badge Info */}
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-purple-950/70 text-purple-300 border border-purple-800/50">
                      {entry.mr_id}
                    </span>
                    <span className="text-sm font-bold text-slate-100">{entry.symbol}</span>
                    <span className="text-xs text-slate-400 px-2 py-0.5 rounded bg-slate-800">
                      {entry.strategy || 'ai_strategy'}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 text-xs text-slate-400">
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5 text-slate-500" />
                      {entry.timestamp}
                    </span>
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      {entry.source}
                    </span>
                  </div>
                </div>

                {/* Summary */}
                {entry.summary && (
                  <p className="text-xs text-slate-300 bg-slate-900/60 p-2.5 rounded-lg border border-slate-800/50">
                    {entry.summary}
                  </p>
                )}

                {/* Parameter Diffs Table */}
                {entry.changes && entry.changes.length > 0 && (
                  <div className="border border-slate-800 rounded-lg overflow-hidden bg-slate-900/40">
                    <div className="px-3 py-1.5 bg-slate-900/80 text-[11px] font-semibold text-amber-400 flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5" />
                      Modulación de Parámetros (Anterior ➔ Nuevo)
                    </div>
                    <table className="w-full text-left text-[11px]">
                      <thead className="bg-slate-950 text-slate-400 border-b border-slate-800">
                        <tr>
                          <th className="py-1.5 px-3">Parámetro</th>
                          <th className="py-1.5 px-3">Anterior</th>
                          <th className="py-1.5 px-3">Nuevo</th>
                          <th className="py-1.5 px-3">Variación</th>
                          <th className="py-1.5 px-3">Justificación Cuantitativa</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/40 text-slate-300">
                        {entry.changes.map((ch, cIdx) => (
                          <tr key={cIdx} className="hover:bg-slate-800/30">
                            <td className="py-1.5 px-3 font-mono text-purple-300">{ch.parameter}</td>
                            <td className="py-1.5 px-3 font-mono text-slate-400">{String(ch.old_value)}</td>
                            <td className="py-1.5 px-3 font-mono text-emerald-400 font-bold">{String(ch.new_value)}</td>
                            <td className="py-1.5 px-3 font-mono text-amber-400">{ch.difference}</td>
                            <td className="py-1.5 px-3 text-slate-400">{ch.description}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Avoid Patterns & Risk Advice */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                  {entry.avoid_patterns && entry.avoid_patterns.length > 0 && (
                    <div className="bg-rose-950/20 border border-rose-900/30 rounded-lg p-2.5">
                      <div className="font-semibold text-rose-400 flex items-center gap-1 mb-1">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        Trampas a Evitar
                      </div>
                      <ul className="list-disc list-inside text-rose-200/80 space-y-0.5">
                        {entry.avoid_patterns.map((p, pIdx) => (
                          <li key={pIdx}>{p}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {entry.risk_advice && (
                    <div className="bg-indigo-950/20 border border-indigo-900/30 rounded-lg p-2.5">
                      <div className="font-semibold text-indigo-400 flex items-center gap-1 mb-1">
                        <ShieldCheck className="w-3.5 h-3.5" />
                        Consejo Defensivo
                      </div>
                      <p className="text-indigo-200/80">{entry.risk_advice}</p>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-3 bg-slate-950/80 border-t border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="text-xs font-semibold px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors"
          >
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
};
