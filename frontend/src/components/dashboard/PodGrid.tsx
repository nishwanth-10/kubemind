'use client';
import { ServiceMetrics } from '@/types';
import { AlertTriangle, CheckCircle, XCircle, Cpu, Database, Wifi, RotateCcw, HardDrive, Server } from 'lucide-react';
import { motion } from 'framer-motion';

// ── Color maps (namespace-based for real K8s — dynamic) ─────────────────────
const NS_COLORS: Record<string, string> = {
  'kube-system':  'border-slate-500/30  bg-slate-500/5',
  'monitoring':   'border-sky-500/30    bg-sky-500/5',
  'default':      'border-emerald-500/30 bg-emerald-500/5',
  'ingress':      'border-violet-500/30  bg-violet-500/5',
  'cert-manager': 'border-amber-500/30   bg-amber-500/5',
  'logging':      'border-indigo-500/30  bg-indigo-500/5',
};

const NS_ACCENT: Record<string, string> = {
  'kube-system':  'bg-slate-500',
  'monitoring':   'bg-sky-500',
  'default':      'bg-emerald-500',
  'ingress':      'bg-violet-500',
  'cert-manager': 'bg-amber-500',
  'logging':      'bg-indigo-500',
};

function nsColor(ns: string): string {
  return NS_COLORS[ns] ?? 'border-slate-700/40 bg-slate-800/20';
}
function nsAccent(ns: string): string {
  return NS_ACCENT[ns] ?? 'bg-slate-500';
}

interface Props {
  metrics: ServiceMetrics[];
  onSelect: (svc: string) => void;
  selected: string | null;
}

export default function PodGrid({ metrics, onSelect, selected }: Props) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
      {metrics.map((m, idx) => {
        const isAnomaly  = m.anomaly?.is_anomaly;
        const isSelected = selected === m.service;
        const isCrash    = m.crash_loop || m.status === 'CrashLoopBackOff';
        const isOOM      = m.oom_killed || m.status === 'OOMKilled';

        const cpuPct   = m.cpu_percent ?? 0;
        const memPct   = m.memory_limit_mb > 0
          ? Math.round((m.memory_mb / m.memory_limit_mb) * 100)
          : 0;
        const pvcPct   = m.pvc_usage_percent ?? 0;

        const cpuBar   = cpuPct > 85 ? 'bg-rose-500' : cpuPct > 65 ? 'bg-amber-500' : 'bg-sky-500';
        const memBar   = memPct > 85 ? 'bg-rose-500' : memPct > 70 ? 'bg-amber-500' : 'bg-indigo-500';
        const pvcBar   = pvcPct > 90 ? 'bg-rose-500' : pvcPct > 75 ? 'bg-amber-500' : 'bg-teal-500';

        const domainStyle = nsColor(m.namespace);
        const accentColor = nsAccent(m.namespace);

        return (
          <motion.div
            key={m.service}
            layoutId={m.service}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.02 }}
            onClick={() => onSelect(m.service)}
            className={`relative p-4 rounded-xl border cursor-pointer transition-all duration-200 group
              ${domainStyle}
              ${isSelected ? 'ring-1 ring-sky-500/60 shadow-lg shadow-sky-500/10' : 'hover:border-slate-600'}
              ${isAnomaly  ? 'ring-1 ring-rose-500/40' : ''}
              ${isCrash    ? 'ring-2 ring-rose-500/60' : ''}
            `}
          >
            {/* Fault indicator stripe */}
            {(isCrash || isOOM) && (
              <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-rose-500 via-amber-500 to-rose-500 rounded-t-xl animate-pulse" />
            )}

            {/* Header */}
            <div className="flex items-start justify-between mb-3 gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <div className={`w-1.5 h-6 rounded-full flex-shrink-0 ${accentColor}`} />
                <div className="min-w-0">
                  <p className="text-xs font-bold text-slate-200 truncate">{m.display_name ?? m.service}</p>
                  <p className="text-[9px] text-slate-500 font-mono">{m.namespace}</p>
                </div>
              </div>
              <StatusIcon status={m.status} isAnomaly={!!isAnomaly} isCrash={!!isCrash} isOOM={!!isOOM} />
            </div>

            {/* CPU bar */}
            <div className="mb-2">
              <div className="flex justify-between text-[9px] text-slate-500 mb-1">
                <span className="flex items-center gap-1"><Cpu className="w-2.5 h-2.5" />CPU</span>
                <span className="font-mono font-bold text-slate-300">{cpuPct.toFixed(1)}%</span>
              </div>
              <div className="h-1 w-full bg-slate-800 rounded-full overflow-hidden">
                <motion.div
                  className={`h-full ${cpuBar} rounded-full`}
                  animate={{ width: `${Math.min(cpuPct, 100)}%` }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                />
              </div>
            </div>

            {/* Memory bar */}
            <div className="mb-2">
              <div className="flex justify-between text-[9px] text-slate-500 mb-1">
                <span className="flex items-center gap-1"><Database className="w-2.5 h-2.5" />MEM</span>
                <span className="font-mono font-bold text-slate-300">{m.memory_mb.toFixed(0)} MB</span>
              </div>
              <div className="h-1 w-full bg-slate-800 rounded-full overflow-hidden">
                <motion.div
                  className={`h-full ${memBar} rounded-full`}
                  animate={{ width: `${Math.min(memPct, 100)}%` }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                />
              </div>
            </div>

            {/* PVC bar — only if data available */}
            {pvcPct > 0 && (
              <div className="mb-2">
                <div className="flex justify-between text-[9px] text-slate-500 mb-1">
                  <span className="flex items-center gap-1"><HardDrive className="w-2.5 h-2.5" />PVC</span>
                  <span className="font-mono font-bold text-slate-300">{pvcPct.toFixed(0)}%</span>
                </div>
                <div className="h-1 w-full bg-slate-800 rounded-full overflow-hidden">
                  <motion.div
                    className={`h-full ${pvcBar} rounded-full`}
                    animate={{ width: `${Math.min(pvcPct, 100)}%` }}
                    transition={{ duration: 0.8, ease: 'easeOut' }}
                  />
                </div>
              </div>
            )}

            {/* Bottom stats */}
            <div className="flex items-center justify-between text-[9px] text-slate-500 mt-1">
              <span className="flex items-center gap-1">
                <Wifi className="w-2.5 h-2.5" />
                {(m.network_in_kbps ?? 0).toFixed(0)} KB/s
              </span>
              <span className="flex items-center gap-1">
                <RotateCcw className="w-2.5 h-2.5" />
                {m.restart_count} restart{m.restart_count !== 1 ? 's' : ''}
              </span>
              <span className="flex items-center gap-1 font-mono">
                <Server className="w-2.5 h-2.5" />
                {m.node_name ? m.node_name.split('.')[0] : '—'}
              </span>
            </div>

            {/* Anomaly badge */}
            {isAnomaly && !isCrash && !isOOM && (
              <div className="mt-2 flex items-center gap-1.5 px-2 py-1 bg-rose-500/10 border border-rose-500/20 rounded-lg">
                <AlertTriangle className="w-2.5 h-2.5 text-rose-500 flex-shrink-0" />
                <span className="text-[9px] text-rose-400 font-bold truncate">
                  {m.anomaly?.anomaly_types[0] ?? 'ANOMALY DETECTED'}
                </span>
              </div>
            )}

            {/* CrashLoop badge */}
            {isCrash && (
              <div className="mt-2 flex items-center gap-1.5 px-2 py-1 bg-rose-500/15 border border-rose-500/30 rounded-lg">
                <XCircle className="w-2.5 h-2.5 text-rose-400 flex-shrink-0" />
                <span className="text-[9px] text-rose-300 font-bold">CRASHLOOPBACKOFF</span>
              </div>
            )}

            {/* OOMKilled badge */}
            {isOOM && (
              <div className="mt-1 flex items-center gap-1.5 px-2 py-1 bg-orange-500/15 border border-orange-500/30 rounded-lg">
                <AlertTriangle className="w-2.5 h-2.5 text-orange-400 flex-shrink-0" />
                <span className="text-[9px] text-orange-300 font-bold">OOMKILLED — increase memory limit</span>
              </div>
            )}

            {/* Event warnings */}
            {(m.events ?? []).length > 0 && !isCrash && !isOOM && (
              <div className="mt-1 text-[9px] text-amber-500 font-bold flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                {m.events![0].reason}: {m.events![0].message.slice(0, 40)}…
              </div>
            )}
          </motion.div>
        );
      })}
    </div>
  );
}

function StatusIcon({ status, isAnomaly, isCrash, isOOM }: {
  status: string; isAnomaly: boolean; isCrash: boolean; isOOM: boolean;
}) {
  if (isCrash || status === 'CrashLoopBackOff')
    return <XCircle className="w-4 h-4 text-rose-500 flex-shrink-0" />;
  if (isOOM || status === 'OOMKilled')
    return <AlertTriangle className="w-4 h-4 text-orange-400 flex-shrink-0" />;
  if (status === 'Pending')
    return <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />;
  if (isAnomaly)
    return <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />;
  return <CheckCircle className="w-4 h-4 text-emerald-500 flex-shrink-0" />;
}
