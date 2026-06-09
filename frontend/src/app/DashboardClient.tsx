'use client';
import { useState, useMemo, useCallback, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Network, LayoutGrid, ShieldAlert, Lightbulb,
  Cpu, Database, Server, Activity, Zap, GitBranch,
  Gauge, TrendingUp, Radio, Terminal, AlertTriangle,
  PanelRightOpen, PanelRightClose, ChevronDown,
  Sparkles, Bot, Box, BarChart3, Hexagon, Monitor, Settings, LogOut,
} from 'lucide-react';

import { useKubeMindWS } from '@/hooks/useWebSocket';
import { ServiceMetrics, Recommendation, FaultType } from '@/types';
import { useAuth } from '@/components/auth/AuthProvider';

import ClusterHeader        from '@/components/dashboard/ClusterHeader';
import PodGrid              from '@/components/dashboard/PodGrid';
import DependencyGraphV2    from '@/components/dashboard/DependencyGraphV2';
import AnomalyTimeline      from '@/components/dashboard/AnomalyTimeline';
import AIAssistant          from '@/components/dashboard/AIAssistant';
import FaultInjector        from '@/components/dashboard/FaultInjector';
import RecommendationsPanel from '@/components/dashboard/RecommendationsPanel';
import NLPInsightsPanel     from '@/components/dashboard/NLPInsightsPanel';
import AISummaryCards       from '@/components/dashboard/AISummaryCards';
import TimelineChart        from '@/components/dashboard/TimelineChart';
import ClusterHealthCard    from '@/components/dashboard/ClusterHealthCard';
import ActiveAnomalies      from '@/components/dashboard/ActiveAnomalies';
import CorrelationInsights  from '@/components/dashboard/CorrelationInsights';

const NAV_ITEMS = [
  { id: 'topology',  label: 'Graph',      icon: Network     },
  { id: 'pods',      label: 'Pods',       icon: Box         },
  { id: 'anomalies', label: 'Anomalies',  icon: ShieldAlert },
  { id: 'recs',      label: 'Recs',       icon: Lightbulb   },
  { id: 'intel',     label: 'Intel',      icon: BarChart3   },
] as const;

type TabId = typeof NAV_ITEMS[number]['id'];

function LiveStatCard({
  label, value, sub, icon, accent, trend, delay = 0,
}: {
  label: string; value: string | number; sub?: string;
  icon: React.ReactNode; accent: string; trend?: string; delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.35, ease: 'easeOut' }}
      className="group relative overflow-hidden rounded-xl"
    >
      <div className={`relative z-10 flex items-center gap-3 px-3 py-2.5 bg-white/[0.03] border border-white/[0.06] rounded-xl backdrop-blur-sm ${accent.replace('border-', 'hover:').replace('/15', '/20')}`}>
        <div className="p-2 rounded-lg bg-black/40 border border-white/[0.06] group-hover:scale-110 transition-transform duration-300">
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] text-slate-500 font-semibold tracking-wide">{label}</p>
          <div className="flex items-baseline gap-2">
            <p className="text-xl font-bold tracking-tight text-slate-100 leading-none mt-0.5 tabular-nums">
              {value}
            </p>
            {trend && (
              <span className={`text-[9px] font-bold ${trend.startsWith('+') ? 'text-rose-400' : trend.startsWith('-') ? 'text-emerald-400' : 'text-slate-500'}`}>
                {trend}
              </span>
            )}
          </div>
          {sub && <p className="text-[9px] text-slate-600 mt-0.5">{sub}</p>}
        </div>
      </div>
      <div className="absolute inset-0 bg-gradient-to-br from-white/[0.02] to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-xl" />
    </motion.div>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const { isAuthenticated, loading: authLoading, logout } = useAuth();
  const { data, status, lastTs, injectFault, clearFault } = useKubeMindWS();
  const [activeTab,    setActiveTab]    = useState<TabId>('topology');
  const [selectedSvc,  setSelectedSvc]  = useState<string | null>(null);
  const [nsFilter,     setNsFilter]     = useState<string>('all');
  const [drawerOpen,   setDrawerOpen]   = useState(true);
  const [faultOpen,    setFaultOpen]    = useState(false);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [authLoading, isAuthenticated, router]);

  if (authLoading) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-black">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          <p className="text-sm text-neutral-500">Loading KubeMind...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) return null;

  const summary                = data?.summary                ?? null;
  const allMetrics             = data?.metrics                ?? [];
  const anomalies              = data?.anomalies              ?? [];
  const rca                    = data?.rca                    ?? [];
  const nlpInsights            = data?.nlp_insights           ?? [];
  const activeFaults           = data?.active_faults          ?? {};
  const topology               = data?.topology               ?? { nodes: [], links: [] };
  const correlationIntelligence = data?.correlation_intelligence;
  const healthScore            = data?.health_score;
  const exhaustionPredictions  = data?.exhaustion_predictions ?? [];

  const allRecs: Recommendation[] = useMemo(
    () => allMetrics.flatMap(m => m.recommendations ?? [])
          .sort((a, b) => {
            const order: Record<string, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };
            return (order[a.priority] ?? 9) - (order[b.priority] ?? 9);
          }),
    [allMetrics],
  );

  const namespaces = useMemo(
    () => ['all', ...Array.from(new Set(allMetrics.map(m => m.namespace)))],
    [allMetrics],
  );
  const filteredMetrics = useMemo(
    () => nsFilter === 'all' ? allMetrics : allMetrics.filter(m => m.namespace === nsFilter),
    [allMetrics, nsFilter],
  );

  const handleInject = useCallback((svc: string, ft: FaultType) => injectFault(svc, ft, 120), [injectFault]);
  const handleClear  = useCallback((svc: string) => clearFault(svc), [clearFault]);

  const anomalyCount = anomalies.length;
  const criticalCount = anomalies.filter(a => a.severity === 'critical').length;

  const renderContent = () => {
    switch (activeTab) {
      case 'topology':
        return (
          <DependencyGraphV2
            nodes={topology.nodes}
            links={topology.links}
            metrics={allMetrics}
            correlationIntelligence={correlationIntelligence}
          />
        );
      case 'pods':
        return <PodGrid metrics={filteredMetrics} onSelect={setSelectedSvc} selected={selectedSvc} />;
      case 'anomalies':
        return <AnomalyTimeline anomalies={anomalies} rca={rca} />;
      case 'recs':
        return <RecommendationsPanel recs={allRecs} />;
      case 'intel':
        return (
          <div className="p-4 space-y-4 overflow-y-auto h-full">
            <AISummaryCards
              metrics={allMetrics} anomalies={anomalies}
              correlationIntelligence={correlationIntelligence}
              healthScore={healthScore} exhaustionPredictions={exhaustionPredictions}
            />
            <TimelineChart
              metrics={allMetrics} anomalies={anomalies}
              exhaustionPredictions={exhaustionPredictions}
              correlationIntelligence={correlationIntelligence}
            />
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="h-screen w-screen overflow-hidden bg-black flex">
      {/* ─── Sidebar ─── */}
      <motion.nav
        initial={{ width: 0, opacity: 0 }}
        animate={{ width: 64, opacity: 1 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="flex-shrink-0 h-full bg-white/[0.02] border-r border-white/[0.06] flex flex-col items-center py-4 gap-1 z-30"
      >
        {/* Logo */}
        <div className="mb-6 mt-1">
          <div className="w-9 h-9 rounded-xl bg-white flex items-center justify-center shadow-lg shadow-white/10">
            <Hexagon className="w-4 h-4 text-black" />
          </div>
        </div>

        {/* Nav Items */}
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => setActiveTab(item.id)}
            className={`relative w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200 group ${
              activeTab === item.id
                ? 'bg-white/15 text-white shadow-sm'
                : 'text-neutral-600 hover:text-neutral-300 hover:bg-white/[0.04]'
            }`}
          >
            <item.icon className="w-4.5 h-4.5" />
            {activeTab === item.id && (
              <motion.div layoutId="nav-indicator" className="absolute -left-3 w-1 h-5 rounded-full bg-white" />
            )}
            <div className="absolute left-full ml-3 px-2 py-1 bg-neutral-900 border border-neutral-800 rounded-lg text-[9px] font-bold text-neutral-300 whitespace-nowrap opacity-0 invisible group-hover:visible group-hover:opacity-100 transition-all duration-200 pointer-events-none z-50">
              {item.label}
            </div>
          </button>
        ))}

        {/* Divider */}
        <div className="w-6 h-px bg-white/[0.06] my-2" />

        {/* Clusters button */}
        <button
          onClick={() => router.push('/clusters')}
          className="relative w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200 group text-slate-600 hover:text-slate-300 hover:bg-white/[0.04]"
        >
          <Settings className="w-4 h-4" />
          <div className="absolute left-full ml-3 px-2 py-1 bg-slate-900 border border-slate-800 rounded-lg text-[9px] font-bold text-slate-300 whitespace-nowrap opacity-0 invisible group-hover:visible group-hover:opacity-100 transition-all duration-200 pointer-events-none z-50">
            Clusters
          </div>
        </button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* WS Status Dot */}
        <div className="relative mb-1">
          <div className={`w-2.5 h-2.5 rounded-full ${
            status === 'open' ? 'bg-emerald-500' : status === 'connecting' ? 'bg-amber-500' : 'bg-rose-500'
          }`} />
          {status === 'open' && (
            <div className="absolute inset-0 rounded-full bg-emerald-500 animate-ping opacity-30" />
          )}
        </div>

        {/* Logout */}
        <button
          onClick={() => { logout(); router.push('/login'); }}
          className="w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200 group text-slate-600 hover:text-rose-400 hover:bg-rose-500/10"
        >
          <LogOut className="w-4 h-4" />
          <div className="absolute left-full ml-3 px-2 py-1 bg-slate-900 border border-slate-800 rounded-lg text-[9px] font-bold text-slate-300 whitespace-nowrap opacity-0 invisible group-hover:visible group-hover:opacity-100 transition-all duration-200 pointer-events-none z-50">
            Logout
          </div>
        </button>
      </motion.nav>

      {/* ─── Main Content ─── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* ─── Top Bar ─── */}
        <motion.header
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="flex-shrink-0 flex items-center gap-3 px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.01]"
        >
          <ClusterHeader summary={summary} wsStatus={status} lastTs={lastTs} />

          {/* Live Stats Strip */}
          <div className="flex items-center gap-2 ml-auto">
            <LiveStatCard
              label="CPU" icon={<Cpu className="w-3.5 h-3.5 text-emerald-400" />}
              value={`${summary?.avg_cpu_percent ?? 0}%`}
              sub={summary?.cluster_health}
              accent="border-emerald-500/10"
              delay={0}
            />
            <LiveStatCard
              label="Memory" icon={<Database className="w-3.5 h-3.5 text-indigo-400" />}
              value={`${Math.round(summary?.avg_memory_mb ?? 0)}`}
              sub="MB avg"
              accent="border-indigo-500/10"
              delay={0.02}
            />
            <LiveStatCard
              label="Services" icon={<Server className="w-3.5 h-3.5 text-sky-400" />}
              value={summary?.total_services ?? 0}
              sub={`${summary?.running_services ?? 0} running`}
              accent="border-sky-500/10"
              delay={0.04}
            />
            <LiveStatCard
              label="Health" icon={<Gauge className="w-3.5 h-3.5 text-emerald-400" />}
              value={healthScore?.score ?? '--'}
              sub={healthScore?.level ?? 'unknown'}
              accent="border-emerald-500/10"
              delay={0.06}
            />
            <LiveStatCard
              label="Anomalies" icon={<AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
              value={anomalyCount}
              sub={`${criticalCount} critical`}
              accent="border-amber-500/10"
              delay={0.08}
              trend={anomalyCount > 0 ? `+${anomalyCount}` : undefined}
            />
            <LiveStatCard
              label="Exhaustion" icon={<TrendingUp className="w-3.5 h-3.5 text-rose-400" />}
              value={exhaustionPredictions.length}
              sub="risks pending"
              accent="border-rose-500/10"
              delay={0.10}
            />
          </div>
        </motion.header>

        {/* ─── Sub Bar: NS Filter + Tab Tabs ─── */}
        <div className="flex-shrink-0 flex items-center gap-2 px-4 py-2 border-b border-white/[0.04] bg-white/[0.01]">
          {/* Namespace pills */}
          <div className="flex items-center gap-1 bg-white/[0.03] rounded-lg p-0.5 border border-white/[0.06]">
            {namespaces.map(ns => (
              <button key={ns} onClick={() => setNsFilter(ns)}
                className={`px-2 py-1 rounded-md text-[9px] font-bold uppercase tracking-wider transition-all duration-200 ${
                  nsFilter === ns
                    ? 'bg-sky-500/20 text-sky-300 shadow-sm'
                    : 'text-slate-600 hover:text-slate-300 hover:bg-white/[0.04]'
                }`}>
                {ns}
              </button>
            ))}
          </div>

          {/* View Tabs */}
          <div className="flex items-center gap-1 bg-white/[0.03] rounded-lg p-0.5 border border-white/[0.06] ml-auto">
            {NAV_ITEMS.map(t => (
              <button key={t.id} onClick={() => setActiveTab(t.id)}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold transition-all duration-200 ${
                  activeTab === t.id
                    ? 'bg-sky-500/12 text-sky-300 shadow-sm'
                    : 'text-slate-600 hover:text-slate-300 hover:bg-white/[0.04]'
                }`}>
                <t.icon className="w-3 h-3" />{t.label}
              </button>
            ))}
          </div>

          {/* Right Drawer Toggle */}
          <button
            onClick={() => setDrawerOpen(o => !o)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-bold text-slate-500 hover:text-slate-300 hover:bg-white/[0.04] border border-white/[0.06] transition-all"
          >
            {drawerOpen ? <PanelRightClose className="w-3 h-3" /> : <PanelRightOpen className="w-3 h-3" />}
            {drawerOpen ? 'Hide' : 'Insights'}
          </button>
        </div>

        {/* ─── Content Area ─── */}
        <div className="flex-1 flex min-h-0">
          {/* Main Panel */}
          <div className="flex-1 min-w-0 relative">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.2 }}
                className={`absolute inset-0 ${
                  activeTab === 'pods' || activeTab === 'recs' || activeTab === 'intel'
                    ? 'overflow-y-auto'
                    : ''
                }`}
              >
                {renderContent()}
              </motion.div>
            </AnimatePresence>

            {/* Bottom bar with fault injector */}
            <div className="absolute bottom-0 left-0 right-0 z-20">
              <motion.div
                animate={{ height: faultOpen ? 'auto' : 0 }}
                className="overflow-hidden border-t border-white/[0.04]"
              >
                <div className="bg-white/[0.02] backdrop-blur-xl px-4 py-3">
                  <FaultInjector
                    metrics={allMetrics} activeFaults={activeFaults}
                    onInject={handleInject} onClear={handleClear}
                  />
                </div>
              </motion.div>
              <button
                onClick={() => setFaultOpen(o => !o)}
                className="w-full flex items-center justify-center gap-2 py-1.5 bg-white/[0.01] border-t border-white/[0.04] text-[9px] font-bold text-slate-600 hover:text-slate-400 hover:bg-white/[0.02] transition-all uppercase tracking-wider"
              >
                <Zap className="w-3 h-3 text-amber-400/60" />
                Fault Injector
                <ChevronDown className={`w-3 h-3 transition-transform ${faultOpen ? 'rotate-180' : ''}`} />
                {Object.keys(activeFaults).length > 0 && (
                  <span className="px-1.5 py-0.5 bg-rose-500/15 text-rose-400 rounded text-[8px]">{Object.keys(activeFaults).length} active</span>
                )}
              </button>
            </div>
          </div>

          {/* ─── Right Drawer ─── */}
          <AnimatePresence>
            {drawerOpen && (
              <motion.aside
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: 320, opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                transition={{ duration: 0.25, ease: 'easeInOut' }}
                className="flex-shrink-0 border-l border-white/[0.06] overflow-hidden bg-white/[0.01]"
              >
                <div className="w-[320px] h-full overflow-y-auto p-3 space-y-3">
                  {healthScore && <ClusterHealthCard healthScore={healthScore} correlationIntelligence={correlationIntelligence} />}
                  <ActiveAnomalies anomalies={anomalies} correlationIntelligence={correlationIntelligence} />
                  <CorrelationInsights correlationIntelligence={correlationIntelligence} />
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] overflow-hidden">
                    <AIAssistant />
                  </div>
                  <NLPInsightsPanel insights={nlpInsights} />

                  {/* Predictive Risk */}
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3 space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="font-semibold text-xs flex items-center gap-2 text-slate-300">
                        <Activity className="w-3.5 h-3.5 text-sky-400" />
                        Predictive Risk
                      </h3>
                      <span className="text-[8px] text-slate-600 uppercase font-bold tracking-wider">30-min</span>
                    </div>
                    <div className="space-y-2 max-h-[260px] overflow-y-auto">
                      {allMetrics
                        .filter(m => m.prediction && m.prediction.risk_level !== 'low')
                        .sort((a, b) => (b.prediction?.failure_probability_30m ?? 0) - (a.prediction?.failure_probability_30m ?? 0))
                        .map(m => {
                          const p = m.prediction!;
                          const pct = Math.round(p.failure_probability_30m * 100);
                          const barColor = pct > 70 ? 'from-rose-500 to-rose-600' : pct > 40 ? 'from-amber-500 to-amber-600' : 'from-sky-500 to-sky-600';
                          return (
                            <motion.div
                                key={m.service}
                              initial={{ opacity: 0, x: -6 }}
                              animate={{ opacity: 1, x: 0 }}
                              className="bg-black/40 border border-white/[0.06] rounded-lg p-2.5 hover:border-white/[0.10] transition-colors"
                            >
                              <div className="flex justify-between items-center mb-1.5">
                                <span className="text-[9px] font-bold text-slate-300 truncate max-w-[160px]">{m.display_name ?? m.service}</span>
                                <span className={`text-[7px] font-bold uppercase px-1.5 py-0.5 rounded border ${
                                  p.risk_level === 'critical' ? 'text-rose-400 border-rose-500/30 bg-rose-500/10'
                                  : p.risk_level === 'high' ? 'text-amber-400 border-amber-500/30 bg-amber-500/10'
                                  : 'text-sky-400 border-sky-500/30 bg-sky-500/10'
                                }`}>{p.risk_level}</span>
                              </div>
                              <div className="h-1 bg-slate-800/80 rounded-full overflow-hidden">
                                <motion.div
                                  className={`h-full rounded-full bg-gradient-to-r ${barColor}`}
                                  initial={{ width: 0 }}
                                  animate={{ width: `${pct}%` }}
                                  transition={{ duration: 0.8, ease: 'easeOut' }}
                                />
                              </div>
                              <div className="flex justify-between mt-1 text-[8px] text-slate-600">
                                <span>{p.top_risk_metric ?? 'multi'}</span>
                                <span className="font-bold text-slate-500">{pct}%</span>
                              </div>
                            </motion.div>
                          );
                        })}
                      {allMetrics.filter(m => m.prediction && m.prediction.risk_level !== 'low').length === 0 && (
                        <div className="flex flex-col items-center justify-center py-6 text-slate-600">
                          <Terminal className="w-5 h-5 text-slate-700 mb-1.5" />
                          <p className="text-[9px]">No elevated risks</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </motion.aside>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* ─── Live Status Floating Badge ─── */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        className="fixed bottom-4 right-4 z-50 flex items-center gap-2 bg-black/80 backdrop-blur-xl border border-white/[0.08] px-3 py-1.5 rounded-full shadow-xl"
      >
        <div className={`w-2 h-2 rounded-full ${
          status === 'open' ? 'bg-emerald-500 animate-pulse' : status === 'connecting' ? 'bg-amber-500 animate-pulse' : 'bg-rose-500'
        }`} />
        <span className="text-[9px] font-bold text-slate-400 tracking-wider uppercase">
          {status === 'open' ? 'Live' : status}
        </span>
        {lastTs && (
          <span className="text-[8px] text-slate-600 font-mono ml-1">
            {new Date(lastTs).toLocaleTimeString()}
          </span>
        )}
      </motion.div>
    </div>
  );
}
