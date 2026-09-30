import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  AlertTriangle, RefreshCw, ExternalLink, GitPullRequest, FileText,
  ChevronRight, ChevronDown, Info, Loader, Tag, User, X, Clock, CheckCircle,
  BarChart3, Building2, Layers, Search, Zap, TrendingUp, AreaChart, LineChart,
  Grid3X3, Lightbulb, Calendar, Activity, Filter, LayoutDashboard, List, 
  BrainCircuit, Target
} from 'lucide-react';
import { DEFAULT_RELEASE } from '../../config';
import api from '../../services/api';
import '../../styles/escalations.css';

const PRIORITY_COLORS = {
  blocker: '#dc2626', critical: '#dc2626', highest: '#dc2626',
  high: '#ea580c', major: '#ea580c',
  medium: '#ca8a04', normal: '#ca8a04',
  low: '#16a34a', minor: '#16a34a', trivial: '#16a34a', lowest: '#16a34a',
};

const PRIORITY_ORDER = ['blocker', 'critical', 'highest', 'high', 'major', 'medium', 'normal', 'minor', 'low', 'trivial', 'lowest'];

const SEVERITY_TIERS = [
  { keys: ['blocker', 'critical', 'highest'], label: 'Critical', cls: 'esc-sev-critical' },
  { keys: ['high', 'major'], label: 'High', cls: 'esc-sev-high' },
  { keys: ['medium', 'normal'], label: 'Medium', cls: 'esc-sev-medium' },
  { keys: ['low', 'minor', 'trivial', 'lowest'], label: 'Low', cls: 'esc-sev-low' },
];

const RESOLVED_STATUSES = ['resolved', 'fixed', 'done', 'verified', 'closed', 'pending close'];

const isResolved = (status) => RESOLVED_STATUSES.includes((status || '').toLowerCase());

const avatarColor = (name) => {
  const colors = ['#6366f1','#2563eb','#059669','#ea580c','#8b5cf6','#0d9488','#dc2626','#ca8a04'];
  let hash = 0;
  for (let i = 0; i < (name || '').length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
};

const initials = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  return parts.length >= 2 ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase() : name.substring(0, 2).toUpperCase();
};

const calcResolutionDays = (created, resolved) => {
  if (!created || !resolved) return null;
  try {
    const diff = new Date(resolved) - new Date(created);
    return Math.max(0, +(diff / 86400000).toFixed(1));
  } catch { return null; }
};

const resolvedClass = (days) => {
  if (days === null || days === undefined) return '';
  if (days <= 3) return 'fast';
  if (days <= 7) return 'mid';
  return 'slow';
};

const DONUT_COLORS = ['#dc2626','#ea580c','#f59e0b','#84cc16','#22c55e','#14b8a6','#3b82f6','#6366f1','#8b5cf6','#a855f7','#06b6d4','#eab308'];

/* ===== INSIGHT CARD COMPONENT ===== */
const InsightCard = ({ type, value, tickets, onClose, aiImpactedFeatures }) => {
  // Filter tickets for this customer or component
  const filteredTickets = useMemo(() => {
    if (!value || !tickets) return [];
    if (type === 'customer') {
      return tickets.filter(t => (t.customer || 'Unknown') === value);
    }
    if (type === 'component') {
      return tickets.filter(t => (t.sub_component || 'Unknown') === value);
    }
    return [];
  }, [type, value, tickets]);

  // Compute impacted areas (pain points) from ticket sub_components
  const impactedAreas = useMemo(() => {
    const counts = {};
    filteredTickets.forEach(t => {
      if (type === 'customer') {
        const comp = t.sub_component || 'Unknown';
        counts[comp] = (counts[comp] || 0) + 1;
      } else if (type === 'component') {
        const cust = t.customer || 'Unknown';
        counts[cust] = (counts[cust] || 0) + 1;
      }
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [type, filteredTickets]);

  // Priority breakdown
  const priorityBreakdown = useMemo(() => {
    const counts = { critical: 0, high: 0, medium: 0, low: 0 };
    filteredTickets.forEach(t => {
      const p = (t.priority || '').toLowerCase();
      if (['blocker', 'critical', 'highest'].includes(p)) counts.critical++;
      else if (['high', 'major'].includes(p)) counts.high++;
      else if (['medium', 'normal'].includes(p)) counts.medium++;
      else counts.low++;
    });
    return counts;
  }, [filteredTickets]);

  // Resolution metrics
  const resolutionMetrics = useMemo(() => {
    const resolved = filteredTickets.filter(t => isResolved(t.status));
    if (resolved.length === 0) return { avg: null, fast: 0, slow: 0, total: 0 };
    
    let total = 0;
    let fast = 0;
    let slow = 0;
    resolved.forEach(t => {
      const days = calcResolutionDays(t.created, t.resolution_date);
      if (days !== null) {
        total += days;
        if (days <= 3) fast++;
        else if (days > 7) slow++;
      }
    });
    return {
      avg: (total / resolved.length).toFixed(1),
      fast,
      slow,
      total: resolved.length
    };
  }, [filteredTickets]);

  // Top assignees
  const topAssignees = useMemo(() => {
    const counts = {};
    filteredTickets.forEach(t => {
      const assignee = t.assignee || 'Unassigned';
      counts[assignee] = (counts[assignee] || 0) + 1;
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
  }, [filteredTickets]);

  // Early return after all hooks
  if (!value || !tickets) return null;

  const totalEscalations = filteredTickets.length;
  const criticalCount = priorityBreakdown.critical + priorityBreakdown.high;

  return (
    <div className="esc-insight-card">
      <div className="esc-insight-header">
        <div className="esc-insight-title">
          {type === 'customer' ? <Building2 size={16} /> : <Layers size={16} />}
          <span>{value}</span>
        </div>
        <button className="esc-insight-close" onClick={onClose}>
          <X size={14} />
        </button>
      </div>

      <div className="esc-insight-body">
        {/* Summary Stats */}
        <div className="esc-insight-stats">
          <div className="esc-insight-stat">
            <div className="stat-value">{totalEscalations}</div>
            <div className="stat-label">Escalations</div>
          </div>
          <div className="esc-insight-stat critical">
            <div className="stat-value">{criticalCount}</div>
            <div className="stat-label">Critical/High</div>
          </div>
          <div className="esc-insight-stat">
            <div className="stat-value">{resolutionMetrics.avg || '—'}<span className="stat-unit">d</span></div>
            <div className="stat-label">Avg Resolution</div>
          </div>
        </div>

        {/* Impacted Areas / Pain Points */}
        <div className="esc-insight-section">
          <div className="esc-insight-section-title">
            <AlertTriangle size={12} />
            {type === 'customer' ? 'Pain Points (Components)' : 'Affected Customers'}
          </div>
          <div className="esc-insight-pain-points">
            {impactedAreas.length === 0 ? (
              <span className="esc-insight-empty">No data</span>
            ) : impactedAreas.map(([name, count], i) => {
              const pct = Math.round((count / totalEscalations) * 100);
              const colors = type === 'customer' 
                ? ['#dc2626', '#ea580c', '#f59e0b', '#84cc16', '#22c55e']
                : ['#059669', '#0d9488', '#14b8a6', '#2dd4bf', '#5eead4'];
              return (
                <div key={name} className="esc-pain-point">
                  <div className="pain-point-header">
                    <span className="pain-point-name">{name}</span>
                    <span className="pain-point-count">{count}</span>
                  </div>
                  <div className="pain-point-bar-wrap">
                    <div 
                      className="pain-point-bar" 
                      style={{ 
                        width: `${pct}%`, 
                        background: colors[i % colors.length] 
                      }} 
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* AI-Analyzed Impacted Features (for customers only) */}
        {type === 'customer' && aiImpactedFeatures && aiImpactedFeatures.length > 0 && (
          <div className="esc-insight-section">
            <div className="esc-insight-section-title" style={{ color: '#7c3aed' }}>
              <Zap size={12} />
              AI-Analyzed Features
            </div>
            <div className="esc-insight-ai-features">
              {aiImpactedFeatures.map((feature, i) => {
                const maxCount = aiImpactedFeatures[0]?.count || 1;
                const pct = Math.round((feature.count / maxCount) * 100);
                const colors = ['#7c3aed', '#8b5cf6', '#a78bfa', '#c4b5fd', '#ddd6fe'];
                return (
                  <div key={feature.name} className="esc-ai-feature">
                    <div className="ai-feature-header">
                      <span className="ai-feature-name">{feature.name}</span>
                      <span className="ai-feature-count">{feature.count}</span>
                    </div>
                    <div className="ai-feature-bar-wrap">
                      <div 
                        className="ai-feature-bar" 
                        style={{ 
                          width: `${pct}%`, 
                          background: colors[i % colors.length] 
                        }} 
                      />
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6, fontStyle: 'italic' }}>
              Features identified by AI analysis of PRs
            </div>
          </div>
        )}

        {/* Priority Distribution */}
        <div className="esc-insight-section">
          <div className="esc-insight-section-title">
            <BarChart3 size={12} />
            Priority Distribution
          </div>
          <div className="esc-insight-priority-row">
            {priorityBreakdown.critical > 0 && (
              <span className="priority-pill critical">
                Critical: {priorityBreakdown.critical}
              </span>
            )}
            {priorityBreakdown.high > 0 && (
              <span className="priority-pill high">
                High: {priorityBreakdown.high}
              </span>
            )}
            {priorityBreakdown.medium > 0 && (
              <span className="priority-pill medium">
                Medium: {priorityBreakdown.medium}
              </span>
            )}
            {priorityBreakdown.low > 0 && (
              <span className="priority-pill low">
                Low: {priorityBreakdown.low}
              </span>
            )}
          </div>
        </div>

        {/* Resolution Speed */}
        {resolutionMetrics.total > 0 && (
          <div className="esc-insight-section">
            <div className="esc-insight-section-title">
              <Clock size={12} />
              Resolution Speed
            </div>
            <div className="esc-insight-resolution">
              <div className="resolution-stat fast">
                <CheckCircle size={12} />
                <span>{resolutionMetrics.fast} fast</span>
                <span className="resolution-hint">≤3 days</span>
              </div>
              <div className="resolution-stat slow">
                <AlertTriangle size={12} />
                <span>{resolutionMetrics.slow} slow</span>
                <span className="resolution-hint">&gt;7 days</span>
              </div>
            </div>
          </div>
        )}

        {/* Top Assignees */}
        {topAssignees.length > 0 && (
          <div className="esc-insight-section">
            <div className="esc-insight-section-title">
              <User size={12} />
              Top Assignees
            </div>
            <div className="esc-insight-assignees">
              {topAssignees.map(([name, count]) => (
                <div key={name} className="esc-insight-assignee">
                  <div className="assignee-avatar" style={{ background: avatarColor(name) }}>
                    {initials(name)}
                  </div>
                  <span className="assignee-name">{name}</span>
                  <span className="assignee-count">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const createSlicePath = (startPct, endPct, r = 80, cx = 85, cy = 85) => {
  if (endPct - startPct >= 1) {
    return `M ${cx} ${cy} m -${r},0 a ${r},${r} 0 1,1 ${r*2},0 a ${r},${r} 0 1,1 -${r*2},0`;
  }
  const s = startPct * 2 * Math.PI - Math.PI / 2;
  const e = endPct * 2 * Math.PI - Math.PI / 2;
  const x1 = cx + r * Math.cos(s), y1 = cy + r * Math.sin(s);
  const x2 = cx + r * Math.cos(e), y2 = cy + r * Math.sin(e);
  return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${endPct - startPct > 0.5 ? 1 : 0} 1 ${x2} ${y2} Z`;
};


/* ===== DONUT CHART ===== */
const ReleaseDonut = ({ releases }) => {
  const [hovered, setHovered] = useState(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  if (!releases?.length) return <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>No release data</div>;

  const total = releases.reduce((s, r) => s + (r.ticket_count || 0), 0);
  if (total === 0) return null;

  let cum = 0;
  const slices = releases.map((r, i) => {
    const pct = (r.ticket_count || 0) / total;
    const start = cum;
    cum += pct;
    return { ...r, label: r.id || r.release_id, pct, start, end: cum, color: DONUT_COLORS[i % DONUT_COLORS.length] };
  });

  const hoveredSlice = slices.find(s => s.label === hovered);

  const handleMouseMove = (e, s) => {
    const rect = e.currentTarget.closest('svg').getBoundingClientRect();
    setTooltipPos({ x: e.clientX - rect.left + 10, y: e.clientY - rect.top - 10 });
    setHovered(s.label);
  };

  return (
    <div className="esc-donut-area">
      <div className="esc-donut-wrap">
        <svg viewBox="0 0 170 170" style={{ width: '100%', height: '100%' }}>
          {slices.map((s) => (
            <path key={s.label} d={createSlicePath(s.start, s.end)} fill={s.color} stroke="var(--bg-card)" strokeWidth="2"
              style={{ cursor: 'pointer', opacity: hovered === s.label ? 1 : 0.75, transition: 'opacity 0.15s, transform 0.15s', transformOrigin: 'center', transform: hovered === s.label ? 'scale(1.04)' : 'scale(1)' }}
              onMouseMove={(e) => handleMouseMove(e, s)} onMouseLeave={() => setHovered(null)} />
          ))}
          <circle cx="85" cy="85" r="42" fill="var(--bg-card)" />
        </svg>
        <div className="esc-donut-center">
          <div className="val">{total}</div>
          <div className="lbl">Total</div>
        </div>
        {hoveredSlice && (
          <div style={{
            position: 'absolute', left: tooltipPos.x, top: tooltipPos.y,
            transform: 'translate(-50%, -100%)', background: 'var(--bg-primary)',
            border: '1px solid var(--border-color)', borderRadius: 8,
            padding: '10px 14px', boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            pointerEvents: 'none', zIndex: 50, minWidth: 130,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <div style={{ width: 10, height: 10, borderRadius: 3, background: hoveredSlice.color }} />
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-dark)' }}>{hoveredSlice.label}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, gap: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>Escalations</span>
              <span style={{ fontWeight: 600, color: 'var(--text-dark)' }}>{hoveredSlice.ticket_count}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, gap: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>Percentage</span>
              <span style={{ fontWeight: 600, color: 'var(--text-dark)' }}>{(hoveredSlice.pct * 100).toFixed(1)}%</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, gap: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>Resolved</span>
              <span style={{ fontWeight: 600, color: '#16a34a' }}>{hoveredSlice.resolved_count || 0}</span>
            </div>
          </div>
        )}
      </div>
      <div className="esc-legend">
        {slices.map((s) => (
          <div key={s.label} className="esc-legend-item" onMouseEnter={() => setHovered(s.label)} onMouseLeave={() => setHovered(null)}
            style={{ background: hovered === s.label ? 'var(--bg-tertiary)' : undefined }}>
            <div className="esc-legend-dot" style={{ background: s.color }} />
            <span className="esc-legend-label">{s.label}</span>
            <div className="esc-legend-bar-wrap"><div className="esc-legend-bar" style={{ width: `${(s.pct / (slices[0]?.pct || 1)) * 100}%`, background: s.color }} /></div>
            <span className="esc-legend-count">{s.ticket_count}</span>
          </div>
        ))}
      </div>
    </div>
  );
};


/* ===== MTTR GAUGE ===== */
const MttrGauge = ({ mttr }) => {
  if (!mttr || mttr.sample_size === 0) return <div style={{ padding: 20, fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>No resolution data</div>;
  const { avg_days, median_days, min_days, max_days, sample_size } = mttr;
  const range = (max_days || 1) - (min_days || 0);
  const markerPct = range > 0 ? Math.min(95, Math.max(5, ((avg_days - min_days) / range) * 100)) : 50;
  const dashOffset = 283 - (283 * Math.min(markerPct, 100) / 100);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="esc-mttr-gauge-wrap">
        <div className="esc-mttr-gauge">
          <svg viewBox="0 0 200 110">
            <path d="M 10 100 A 90 90 0 0 1 190 100" fill="none" stroke="var(--border-light)" strokeWidth="14" strokeLinecap="round"/>
            <path d="M 10 100 A 90 90 0 0 1 190 100" fill="none" stroke="url(#mttrG)" strokeWidth="14" strokeLinecap="round"
              strokeDasharray="283" strokeDashoffset={dashOffset}/>
            <defs><linearGradient id="mttrG" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#16a34a"/><stop offset="50%" stopColor="#f59e0b"/><stop offset="100%" stopColor="#dc2626"/>
            </linearGradient></defs>
          </svg>
          <div className="esc-mttr-gauge-label">
            <div className="val">{avg_days ?? '—'}</div>
            <div className="unit">avg days</div>
          </div>
        </div>
      </div>
      <div className="esc-mttr-stats">
        <div className="esc-mttr-mini"><div className="mm-label">Median</div><div className="mm-value">{median_days ?? '—'}<span className="mm-unit">d</span></div></div>
        <div className="esc-mttr-mini"><div className="mm-label" style={{ color: '#16a34a' }}>Fastest</div><div className="mm-value" style={{ color: '#16a34a' }}>{min_days ?? '—'}<span className="mm-unit">d</span></div></div>
        <div className="esc-mttr-mini"><div className="mm-label" style={{ color: '#dc2626' }}>Slowest</div><div className="mm-value" style={{ color: '#dc2626' }}>{max_days ?? '—'}<span className="mm-unit">d</span></div></div>
        <div className="esc-mttr-mini"><div className="mm-label">Sample</div><div className="mm-value">{sample_size}<span className="mm-unit"> tickets</span></div></div>
      </div>
      <div>
        <div className="esc-range-bar"><div className="esc-range-marker" style={{ left: `${markerPct}%` }} /></div>
        <div className="esc-range-labels"><span>{min_days ?? 0}d</span><span>▲ {avg_days}d avg</span><span>{max_days ?? 0}d</span></div>
      </div>
    </div>
  );
};


/* ===== RESOLUTION DISTRIBUTION ===== */
const ResolutionDistribution = ({ tickets }) => {
  const buckets = useMemo(() => {
    const b = [
      { label: 'Under 1 day', max: 1, count: 0, color: '#16a34a', emoji: '🟢' },
      { label: '1 – 3 days', max: 3, count: 0, color: '#22c55e', emoji: '🟡' },
      { label: '3 – 7 days', max: 7, count: 0, color: '#f59e0b', emoji: '🟠' },
      { label: '1 – 2 weeks', max: 14, count: 0, color: '#ea580c', emoji: '🔴' },
      { label: 'Over 2 weeks', max: Infinity, count: 0, color: '#dc2626', emoji: '⛔' },
    ];
    (tickets || []).forEach(t => {
      if (!isResolved(t.status)) return;
      const days = calcResolutionDays(t.created, t.resolutiondate || t.resolution_date);
      if (days === null) return;
      for (const bucket of b) { if (days < bucket.max || bucket.max === Infinity) { bucket.count++; break; } }
    });
    return b;
  }, [tickets]);

  const total = buckets.reduce((s, b) => s + b.count, 0);
  if (total === 0) return <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', padding: 20 }}>No resolution data yet</div>;

  const fastCount = buckets[0].count + buckets[1].count;
  const fastPct = Math.round((fastCount / total) * 100);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Stacked horizontal bar */}
      <div style={{ display: 'flex', height: 24, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border-light)' }}>
        {buckets.map((b, i) => b.count > 0 && (
          <div key={i} title={`${b.label}: ${b.count} tickets (${Math.round((b.count / total) * 100)}%)`}
            style={{ width: `${(b.count / total) * 100}%`, background: b.color, transition: 'width 0.3s', minWidth: b.count > 0 ? 4 : 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: '#fff',
            }}>
            {(b.count / total) >= 0.08 && b.count}
          </div>
        ))}
      </div>

      {/* Row-by-row breakdown */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {buckets.map((b, i) => {
          const pct = Math.round((b.count / total) * 100);
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0' }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: b.color, flexShrink: 0 }} />
              <span style={{ fontSize: 12, color: 'var(--text-secondary)', flex: 1 }}>{b.label}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-dark)', width: 26, textAlign: 'right' }}>{b.count}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 32, textAlign: 'right' }}>{pct}%</span>
            </div>
          );
        })}
      </div>

      {/* Summary insight */}
      <div className="esc-insight-box">
        <div className="ib-label">Summary</div>
        <div className="ib-text">
          <strong style={{ color: '#16a34a' }}>{fastPct}%</strong> of escalations resolved within 3 days
          {buckets[4].count > 0 && <> · <strong style={{ color: '#dc2626' }}>{buckets[4].count}</strong> took over 2 weeks</>}
        </div>
      </div>
    </div>
  );
};


/* ===== FEATURE-TO-CUSTOMER MATRIX ===== */
const FeatureCustomerMatrix = ({ tickets, summary }) => {
  const [hoveredCell, setHoveredCell] = useState(null);
  const [selectedFeature, setSelectedFeature] = useState(null);
  const [selectedCustomer, setSelectedCustomer] = useState(null);

  const matrixData = useMemo(() => {
    if (!tickets?.length) return { features: [], customers: [], matrix: {}, maxCount: 0 };

    const featureCounts = {};
    const customerCounts = {};
    const matrix = {};

    tickets.forEach(t => {
      const feature = t.sub_component || 'Unknown';
      const customer = t.customer || 'Unknown';

      featureCounts[feature] = (featureCounts[feature] || 0) + 1;
      customerCounts[customer] = (customerCounts[customer] || 0) + 1;

      const key = `${feature}::${customer}`;
      if (!matrix[key]) {
        matrix[key] = { count: 0, tickets: [], priorities: {} };
      }
      matrix[key].count++;
      matrix[key].tickets.push(t);
      const p = (t.priority || 'unknown').toLowerCase();
      matrix[key].priorities[p] = (matrix[key].priorities[p] || 0) + 1;
    });

    const features = Object.entries(featureCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([name]) => name);

    const customers = Object.entries(customerCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name]) => name);

    const maxCount = Math.max(...Object.values(matrix).map(m => m.count), 1);

    return { features, customers, matrix, maxCount };
  }, [tickets]);

  const { features, customers, matrix, maxCount } = matrixData;

  if (features.length === 0 || customers.length === 0) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        No data available for matrix view
      </div>
    );
  }

  const getCell = (feature, customer) => matrix[`${feature}::${customer}`] || null;

  const getCellColor = (count) => {
    if (!count) return 'transparent';
    const intensity = Math.min(count / maxCount, 1);
    const alpha = 0.15 + intensity * 0.7;
    return `rgba(99, 102, 241, ${alpha})`;
  };

  const hasCritical = (cell) => {
    if (!cell) return false;
    return (cell.priorities.blocker || 0) + (cell.priorities.critical || 0) + (cell.priorities.highest || 0) > 0;
  };

  return (
    <div className="esc-matrix-container">
      <div className="esc-matrix-scroll">
        <table className="esc-matrix-table">
          <thead>
            <tr>
              <th className="esc-matrix-corner">
                <Grid3X3 size={14} />
              </th>
              {customers.map(customer => (
                <th 
                  key={customer} 
                  className={`esc-matrix-header ${selectedCustomer === customer ? 'selected' : ''}`}
                  onClick={() => setSelectedCustomer(selectedCustomer === customer ? null : customer)}
                  title={customer}
                >
                  <span>{customer}</span>
                </th>
              ))}
              <th className="esc-matrix-total-header">Total</th>
            </tr>
          </thead>
          <tbody>
            {features.map(feature => {
              const featureTotal = customers.reduce((sum, c) => sum + (getCell(feature, c)?.count || 0), 0);
              return (
                <tr key={feature}>
                  <td 
                    className={`esc-matrix-row-header ${selectedFeature === feature ? 'selected' : ''}`}
                    onClick={() => setSelectedFeature(selectedFeature === feature ? null : feature)}
                    title={feature}
                  >
                    <span>{feature.length > 20 ? feature.slice(0, 20) + '...' : feature}</span>
                  </td>
                  {customers.map(customer => {
                    const cell = getCell(feature, customer);
                    const isHovered = hoveredCell === `${feature}::${customer}`;
                    const isHighlighted = selectedFeature === feature || selectedCustomer === customer;
                    return (
                      <td 
                        key={customer}
                        className={`esc-matrix-cell ${isHighlighted ? 'highlighted' : ''} ${hasCritical(cell) ? 'has-critical' : ''}`}
                        style={{ background: getCellColor(cell?.count) }}
                        onMouseEnter={() => setHoveredCell(`${feature}::${customer}`)}
                        onMouseLeave={() => setHoveredCell(null)}
                      >
                        {cell && (
                          <span className="esc-matrix-count">{cell.count}</span>
                        )}
                        {isHovered && cell && (
                          <div className="esc-matrix-tooltip">
                            <div className="tooltip-header">
                              <strong>{feature}</strong>
                              <span>×</span>
                              <strong>{customer}</strong>
                            </div>
                            <div className="tooltip-stat">{cell.count} escalation{cell.count > 1 ? 's' : ''}</div>
                            {hasCritical(cell) && (
                              <div className="tooltip-critical">
                                <AlertTriangle size={10} /> {(cell.priorities.blocker || 0) + (cell.priorities.critical || 0) + (cell.priorities.highest || 0)} Critical
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                    );
                  })}
                  <td className="esc-matrix-total">{featureTotal}</td>
                </tr>
              );
            })}
            <tr className="esc-matrix-total-row">
              <td className="esc-matrix-row-header">Total</td>
              {customers.map(customer => {
                const customerTotal = features.reduce((sum, f) => sum + (getCell(f, customer)?.count || 0), 0);
                return <td key={customer} className="esc-matrix-total">{customerTotal}</td>;
              })}
              <td className="esc-matrix-grand-total">
                {Object.values(matrix).reduce((sum, m) => sum + m.count, 0)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="esc-matrix-legend">
        <span><span className="legend-dot low" /> Low</span>
        <span><span className="legend-dot med" /> Medium</span>
        <span><span className="legend-dot high" /> High</span>
        <span><span className="legend-dot critical" style={{ border: '2px solid #dc2626' }} /> Has Critical</span>
      </div>
    </div>
  );
};


/* ===== ESCALATION PATTERNS DETECTION ===== */
const EscalationPatterns = ({ tickets, summary }) => {
  const [aiSummaries, setAiSummaries] = useState({});
  const [loadingSummary, setLoadingSummary] = useState({});

  const patterns = useMemo(() => {
    if (!tickets?.length) return [];

    const combos = {};

    tickets.forEach(t => {
      const feature = t.sub_component;
      const customer = t.customer;
      
      // Skip if customer or feature is missing/unknown - these don't form meaningful patterns
      if (!customer || customer === 'Unknown' || customer.trim() === '') return;
      if (!feature || feature === 'Unknown' || feature.trim() === '') return;
      
      const key = `${customer}::${feature}`;
      const month = t.created ? new Date(t.created).toISOString().slice(0, 7) : 'unknown';

      if (!combos[key]) {
        combos[key] = {
          customer,
          feature,
          count: 0,
          tickets: [],
          ticketKeys: [],
          priorities: { critical: 0, high: 0, other: 0 },
          months: new Set(),
          avgResolution: 0,
          totalResolutionDays: 0,
          resolvedCount: 0
        };
      }

      combos[key].count++;
      combos[key].tickets.push(t);
      combos[key].ticketKeys.push(t.key);
      combos[key].months.add(month);

      const p = (t.priority || '').toLowerCase();
      if (['blocker', 'critical', 'highest'].includes(p)) {
        combos[key].priorities.critical++;
      } else if (['high', 'major'].includes(p)) {
        combos[key].priorities.high++;
      } else {
        combos[key].priorities.other++;
      }

      if (t.resolution_date && t.created) {
        const days = (new Date(t.resolution_date) - new Date(t.created)) / 86400000;
        if (days > 0) {
          combos[key].totalResolutionDays += days;
          combos[key].resolvedCount++;
        }
      }
    });

    return Object.values(combos)
      .filter(c => c.count >= 2) // Only patterns with 2+ occurrences
      .map(c => ({
        ...c,
        patternKey: `${c.customer}::${c.feature}`,
        monthsCount: c.months.size,
        avgResolution: c.resolvedCount > 0 ? (c.totalResolutionDays / c.resolvedCount).toFixed(1) : null,
        isRecurring: c.months.size >= 2, // Spans multiple months
        riskScore: c.count * (c.priorities.critical * 3 + c.priorities.high * 2 + c.priorities.other) / 10
      }))
      .sort((a, b) => b.riskScore - a.riskScore)
      .slice(0, 8);
  }, [tickets]);

  const fetchAiSummary = useCallback(async (pattern) => {
    const key = pattern.patternKey;
    if (aiSummaries[key] || loadingSummary[key]) return;

    setLoadingSummary(prev => ({ ...prev, [key]: true }));
    try {
      const result = await api.summarizeEscalationPattern(
        pattern.customer,
        pattern.feature,
        pattern.ticketKeys
      );
      setAiSummaries(prev => ({
        ...prev,
        [key]: result.ai_summary || { fallback: result.fallback_summary || result.error }
      }));
    } catch (err) {
      console.error('Error fetching AI summary:', err);
      setAiSummaries(prev => ({
        ...prev,
        [key]: { fallback: 'Unable to generate AI summary' }
      }));
    } finally {
      setLoadingSummary(prev => ({ ...prev, [key]: false }));
    }
  }, [aiSummaries, loadingSummary]);

  if (patterns.length === 0) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        <Info size={16} style={{ marginBottom: 8, opacity: 0.5 }} />
        <div>No recurring patterns detected</div>
        <div style={{ fontSize: 11, marginTop: 4 }}>
          Patterns require 2+ escalations for the same customer + component combination
        </div>
      </div>
    );
  }

  return (
    <div className="esc-patterns-container">
        {patterns.map((pattern, idx) => {
          const summaryData = aiSummaries[pattern.patternKey];
          const isLoading = loadingSummary[pattern.patternKey];
          
          return (
            <div key={idx} className={`esc-pattern-card ${pattern.isRecurring ? 'recurring' : ''}`}>
              <div className="esc-pattern-header">
                <div className="esc-pattern-badge" title={`${pattern.count} escalations for this customer + component`}>
                  {pattern.count}x
                </div>
                <div className="esc-pattern-info">
                  <div className="esc-pattern-customer">
                    <Building2 size={12} /> {pattern.customer}
                  </div>
                  <div className="esc-pattern-feature">
                    <Layers size={12} /> {pattern.feature}
                  </div>
                </div>
                {pattern.isRecurring && (
                  <div className="esc-pattern-recurring" title={`Issues occurred across ${pattern.monthsCount} different months`}>
                    <Activity size={12} /> {pattern.monthsCount} months
                  </div>
                )}
              </div>
              <div className="esc-pattern-stats">
                {pattern.priorities.critical > 0 && (
                  <span className="pattern-stat critical">
                    <AlertTriangle size={10} /> {pattern.priorities.critical} Critical
                  </span>
                )}
                {pattern.priorities.high > 0 && (
                  <span className="pattern-stat high">
                    {pattern.priorities.high} High
                  </span>
                )}
                {pattern.avgResolution && (
                  <span className="pattern-stat">
                    <Clock size={10} /> {pattern.avgResolution}d avg resolution
                  </span>
                )}
              </div>
              
              {/* AI Summary Section */}
              {pattern.riskScore > 2 && (
                <div className="esc-pattern-ai-section">
                  {!summaryData && !isLoading && (
                    <button 
                      className="esc-pattern-ai-btn"
                      onClick={() => fetchAiSummary(pattern)}
                    >
                      <BrainCircuit size={12} />
                      <span>Analyze with AI</span>
                    </button>
                  )}
                  
                  {isLoading && (
                    <div className="esc-pattern-ai-loading">
                      <Loader size={12} className="spinning" />
                      <span>Analyzing {pattern.count} tickets...</span>
                    </div>
                  )}
                  
                  {summaryData && !summaryData.fallback && (
                    <div className="esc-pattern-ai-result">
                      <div className="esc-pattern-ai-header">
                        <BrainCircuit size={12} />
                        <span>AI Analysis</span>
                        {summaryData.confidence && (
                          <span className={`confidence-badge ${summaryData.confidence}`}>
                            {summaryData.confidence}
                          </span>
                        )}
                      </div>
                      {summaryData.root_cause && (
                        <div className="esc-pattern-ai-insight">
                          <strong>Root Cause:</strong> {summaryData.root_cause}
                        </div>
                      )}
                      {summaryData.common_themes?.length > 0 && (
                        <div className="esc-pattern-ai-themes">
                          {summaryData.common_themes.map((theme, i) => (
                            <span key={i} className="theme-tag">{theme}</span>
                          ))}
                        </div>
                      )}
                      {summaryData.recommendation && (
                        <div className="esc-pattern-ai-recommendation">
                          <Lightbulb size={11} />
                          <span>{summaryData.recommendation}</span>
                        </div>
                      )}
                    </div>
                  )}
                  
                  {summaryData?.fallback && (
                    <div className="esc-pattern-alert">
                      <Lightbulb size={12} />
                      <span>{summaryData.fallback}</span>
                    </div>
                  )}
                </div>
              )}
              
              {/* Fallback for low risk patterns */}
              {pattern.riskScore <= 2 && (
                <div className="esc-pattern-alert muted">
                  <Info size={12} />
                  <span>
                    {pattern.isRecurring 
                      ? `Pattern spans ${pattern.monthsCount} months`
                      : `${pattern.count} related escalations`
                    }
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
  );
};


/* ===== FEATURE TIMELINE ===== */
const FeatureTimeline = ({ tickets }) => {
  const [selectedFeature, setSelectedFeature] = useState(null);

  const timelineData = useMemo(() => {
    if (!tickets?.length) return { features: [], monthlyData: {}, months: [] };

    const featureCounts = {};
    const monthlyData = {};
    const allMonths = new Set();

    tickets.forEach(t => {
      const feature = t.sub_component || 'Unknown';
      const month = t.created ? new Date(t.created).toISOString().slice(0, 7) : null;
      if (!month) return;

      featureCounts[feature] = (featureCounts[feature] || 0) + 1;
      allMonths.add(month);

      if (!monthlyData[feature]) {
        monthlyData[feature] = {};
      }
      if (!monthlyData[feature][month]) {
        monthlyData[feature][month] = { count: 0, critical: 0, ticketKeys: [] };
      }
      monthlyData[feature][month].count++;
      if (t.key) {
        monthlyData[feature][month].ticketKeys.push(t.key);
      }
      
      const p = (t.priority || '').toLowerCase();
      if (['blocker', 'critical', 'highest'].includes(p)) {
        monthlyData[feature][month].critical++;
      }
    });

    const features = Object.entries(featureCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, count]) => ({
        name,
        count,
        firstSeen: Object.keys(monthlyData[name] || {}).sort()[0],
        trend: calculateTrend(monthlyData[name] || {}),
        lastSeen: Object.keys(monthlyData[name] || {}).sort().slice(-1)[0],
        criticalCount: Object.values(monthlyData[name] || {}).reduce((sum, m) => sum + (m.critical || 0), 0)
      }));

    const months = Array.from(allMonths).sort();

    return { features, monthlyData, months };
  }, [tickets]);

  const { features, monthlyData, months } = timelineData;

  const formatMonth = (m) => {
    if (!m) return 'N/A';
    const [year, month] = m.split('-');
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${monthNames[parseInt(month) - 1]} ${year.slice(2)}`;
  };

  const getTrendDescription = (trend) => {
    if (!trend || trend.isNew) {
      return 'New — not enough history to calculate trend (need 3+ months of data)';
    }
    if (trend.noChange) {
      return 'No escalations in comparison period';
    }
    if (trend.percent === 0) {
      return `Stable — avg ${trend.olderAvg} → ${trend.recentAvg} per month (no change)`;
    }
    if (trend.percent > 0) {
      return `Increasing — avg ${trend.olderAvg} → ${trend.recentAvg} per month (+${trend.percent}%)`;
    }
    return `Improving — avg ${trend.olderAvg} → ${trend.recentAvg} per month (${trend.percent}%)`;
  };

  if (features.length === 0) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        No timeline data available
      </div>
    );
  }

  return (
    <div className="esc-timeline-container">
      {/* Description */}
      <div className="esc-timeline-description">
        <Info size={14} />
        <div>
          <strong>How to read:</strong> Each row shows a component's escalation history. 
          <span className="esc-tl-legend">
            <span className="legend-item"><span className="legend-bar normal"></span> Escalations per month</span>
            <span className="legend-item"><span className="legend-bar critical"></span> Includes critical issues</span>
            <span className="legend-item trend-worse"><TrendingUp size={10} style={{ transform: 'rotate(180deg)', color: '#dc2626' }} /> Getting worse</span>
            <span className="legend-item trend-better"><TrendingUp size={10} style={{ color: '#16a34a' }} /> Improving</span>
          </span>
        </div>
      </div>

      {/* Column Headers */}
      <div className="esc-timeline-header">
        <span className="th-component">Component</span>
        <span className="th-total" title="Total escalations for this component">Total</span>
        <span className="th-period" title="When escalations first and last appeared">Period</span>
        <span className="th-trend" title="Trend comparing recent 2 months vs previous 2 months">Trend</span>
        <span className="th-chart" title="Last 6 months escalation count (red = has critical)">Last 6 Months</span>
      </div>

      <div className="esc-timeline-features">
        {features.map(feature => (
          <div 
            key={feature.name}
            className={`esc-timeline-feature ${selectedFeature === feature.name ? 'selected' : ''}`}
            onClick={() => setSelectedFeature(selectedFeature === feature.name ? null : feature.name)}
            title="Click to see detailed monthly breakdown"
          >
            {/* Component Name */}
            <div className="feature-info">
              <span className="feature-name" title={feature.name}>
                <Layers size={12} />
                {feature.name.length > 20 ? feature.name.slice(0, 20) + '...' : feature.name}
              </span>
            </div>

            {/* Total Count */}
            <div className="feature-total">
              <span className="feature-count" title={`${feature.count} total escalations`}>{feature.count}</span>
              {feature.criticalCount > 0 && (
                <span className="critical-indicator" title={`${feature.criticalCount} were critical/blocker`}>
                  <AlertTriangle size={10} /> {feature.criticalCount}
                </span>
              )}
            </div>

            {/* Period */}
            <div className="feature-period" title={`First seen: ${formatMonth(feature.firstSeen)}, Last seen: ${formatMonth(feature.lastSeen)}`}>
              <span className="period-range">
                {formatMonth(feature.firstSeen)} → {formatMonth(feature.lastSeen)}
              </span>
            </div>

            {/* Trend: positive % = more escalations (bad), negative % = fewer escalations (good) */}
            <div className="feature-trend-cell" title={getTrendDescription(feature.trend)}>
              {feature.trend?.isNew ? (
                <span className="trend new">
                  <Zap size={10} />
                  <span className="trend-label">New</span>
                </span>
              ) : feature.trend?.percent === 0 || feature.trend?.percent === null ? (
                <span className="trend stable">
                  <span className="trend-icon">—</span>
                  <span className="trend-label">Stable</span>
                </span>
              ) : feature.trend?.percent > 0 ? (
                <span className="trend worse">
                  <TrendingUp size={12} style={{ transform: 'rotate(180deg)' }} />
                  <span className="trend-value">+{feature.trend.percent}%</span>
                </span>
              ) : (
                <span className="trend better">
                  <TrendingUp size={12} />
                  <span className="trend-value">{feature.trend.percent}%</span>
                </span>
              )}
            </div>

            {/* Sparkline */}
            <div className="feature-sparkline">
              {months.slice(-6).map(month => {
                const data = monthlyData[feature.name]?.[month];
                const maxInFeature = Math.max(...months.slice(-6).map(m => monthlyData[feature.name]?.[m]?.count || 0), 1);
                const height = data ? (data.count / maxInFeature) * 100 : 0;
                return (
                  <div 
                    key={month} 
                    className="sparkline-bar-wrap" 
                    title={`${formatMonth(month)}: ${data?.count || 0} escalation${(data?.count || 0) !== 1 ? 's' : ''}${data?.critical ? ` (${data.critical} critical)` : ''}`}
                  >
                    <div 
                      className={`sparkline-bar ${data?.critical ? 'has-critical' : ''}`}
                      style={{ height: `${Math.max(height, data?.count ? 15 : 4)}%` }}
                    />
                    <span className="sparkline-month">{formatMonth(month).split(' ')[0][0]}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Expanded Detail View */}
      {selectedFeature && (
        <div className="esc-timeline-detail">
          <div className="detail-header">
            <Layers size={14} />
            <span>{selectedFeature}</span>
            <span className="detail-hint">Monthly escalation breakdown</span>
            <button className="detail-close" onClick={(e) => { e.stopPropagation(); setSelectedFeature(null); }}>
              <X size={14} />
            </button>
          </div>
          <div className="detail-chart">
            {months.map(month => {
              const data = monthlyData[selectedFeature]?.[month];
              const maxCount = Math.max(...months.map(m => monthlyData[selectedFeature]?.[m]?.count || 0), 1);
              const height = data ? (data.count / maxCount) * 100 : 0;
              const ticketKeys = data?.ticketKeys || [];
              const jiraUrl = ticketKeys.length > 0 
                ? `https://your-org.atlassian.net/issues/?jql=${encodeURIComponent(`key IN (${ticketKeys.join(',')})`)}`
                : null;
              return (
                <div 
                  key={month} 
                  className="chart-bar-wrap" 
                  title={`${formatMonth(month)}: ${data?.count || 0} escalation${(data?.count || 0) !== 1 ? 's' : ''}${data?.critical ? ` (${data.critical} critical)` : ''}${ticketKeys.length > 0 ? ' — Click to open in JIRA' : ''}`}
                >
                  <div 
                    className={`chart-bar ${data?.critical ? 'has-critical' : ''}`}
                    style={{ height: `${Math.max(height, 2)}%` }}
                  >
                    {data?.count > 0 && (
                      jiraUrl ? (
                        <a 
                          href={jiraUrl} 
                          target="_blank" 
                          rel="noopener noreferrer" 
                          className="bar-label bar-label-clickable"
                          onClick={(e) => e.stopPropagation()}
                          title={`Click to view ${data.count} ticket(s) in JIRA`}
                        >
                          {data.count} <ExternalLink size={8} style={{ marginLeft: 2, verticalAlign: 'middle' }} />
                        </a>
                      ) : (
                        <span className="bar-label">{data.count}</span>
                      )
                    )}
                  </div>
                  <span className="bar-month">{formatMonth(month)}</span>
                </div>
              );
            })}
          </div>
          <div className="detail-summary">
            <span><strong>Total:</strong> {features.find(f => f.name === selectedFeature)?.count || 0} escalations</span>
            <span><strong>Critical:</strong> {features.find(f => f.name === selectedFeature)?.criticalCount || 0}</span>
            <span><strong>Trend:</strong> {getTrendDescription(features.find(f => f.name === selectedFeature)?.trend)}</span>
          </div>
        </div>
      )}
    </div>
  );
};

const calculateTrend = (monthlyData) => {
  const months = Object.keys(monthlyData).sort();
  
  // Not enough data to calculate trend
  if (months.length < 3) {
    return { percent: null, isNew: true, recentAvg: null, olderAvg: null };
  }
  
  const recent = months.slice(-2);
  const older = months.slice(-4, -2);
  
  // Not enough older data to compare
  if (older.length === 0) {
    return { percent: null, isNew: true, recentAvg: null, olderAvg: null };
  }
  
  const recentAvg = recent.reduce((sum, m) => sum + (monthlyData[m]?.count || 0), 0) / recent.length;
  const olderAvg = older.reduce((sum, m) => sum + (monthlyData[m]?.count || 0), 0) / older.length;
  
  // Avoid division by zero
  if (olderAvg === 0) {
    return { percent: null, isNew: false, recentAvg, olderAvg, noChange: recentAvg === 0 };
  }
  
  const percent = Math.round(((recentAvg - olderAvg) / olderAvg) * 100);
  return { percent, isNew: false, recentAvg: recentAvg.toFixed(1), olderAvg: olderAvg.toFixed(1) };
};


/* ===== CORRELATION INSIGHTS ===== */
const CorrelationInsights = ({ tickets, summary }) => {
  const insights = useMemo(() => {
    if (!tickets?.length) return [];

    const featureStats = {};
    const customerStats = {};
    const assigneeStats = {};
    const overallStats = { totalResolution: 0, resolvedCount: 0 };

    tickets.forEach(t => {
      const feature = t.sub_component || 'Unknown';
      const customer = t.customer || 'Unknown';
      const assignee = t.assignee || 'Unassigned';
      const days = t.resolution_date && t.created 
        ? (new Date(t.resolution_date) - new Date(t.created)) / 86400000 
        : null;

      [
        [featureStats, feature],
        [customerStats, customer],
        [assigneeStats, assignee]
      ].forEach(([stats, key]) => {
        if (!stats[key]) {
          stats[key] = { total: 0, resolved: 0, totalDays: 0, critical: 0, withPrs: 0 };
        }
        stats[key].total++;
        if (days !== null && days > 0) {
          stats[key].resolved++;
          stats[key].totalDays += days;
          overallStats.totalResolution += days;
          overallStats.resolvedCount++;
        }
        const p = (t.priority || '').toLowerCase();
        if (['blocker', 'critical', 'highest'].includes(p)) {
          stats[key].critical++;
        }
      });
    });

    const overallAvgDays = overallStats.resolvedCount > 0 
      ? overallStats.totalResolution / overallStats.resolvedCount 
      : 0;

    const results = [];

    Object.entries(featureStats).forEach(([feature, stats]) => {
      if (stats.resolved < 3) return;
      const avgDays = stats.totalDays / stats.resolved;
      const diff = ((avgDays - overallAvgDays) / overallAvgDays) * 100;
      
      if (Math.abs(diff) > 30) {
        results.push({
          type: 'resolution_time',
          entity: feature,
          entityType: 'feature',
          icon: Layers,
          avgDays: avgDays.toFixed(1),
          diff: diff.toFixed(0),
          sample: stats.resolved,
          isSlower: diff > 0,
          insight: diff > 0 
            ? `${feature} takes ${Math.abs(diff.toFixed(0))}% longer to resolve than average`
            : `${feature} resolves ${Math.abs(diff.toFixed(0))}% faster than average`
        });
      }
      
      const criticalRate = (stats.critical / stats.total) * 100;
      if (criticalRate > 40 && stats.critical >= 3) {
        results.push({
          type: 'critical_rate',
          entity: feature,
          entityType: 'feature',
          icon: AlertTriangle,
          rate: criticalRate.toFixed(0),
          count: stats.critical,
          total: stats.total,
          insight: `${feature} has ${criticalRate.toFixed(0)}% critical escalation rate (${stats.critical}/${stats.total})`
        });
      }
    });

    Object.entries(customerStats).forEach(([customer, stats]) => {
      if (stats.resolved < 3) return;
      const avgDays = stats.totalDays / stats.resolved;
      const diff = ((avgDays - overallAvgDays) / overallAvgDays) * 100;
      
      if (diff > 50) {
        results.push({
          type: 'customer_slow',
          entity: customer,
          entityType: 'customer',
          icon: Building2,
          avgDays: avgDays.toFixed(1),
          diff: diff.toFixed(0),
          sample: stats.resolved,
          insight: `${customer} escalations take ${diff.toFixed(0)}% longer to resolve (${avgDays.toFixed(1)}d avg)`
        });
      }
    });

    const topAssignees = Object.entries(assigneeStats)
      .filter(([_, s]) => s.resolved >= 5)
      .sort((a, b) => (a[1].totalDays / a[1].resolved) - (b[1].totalDays / b[1].resolved))
      .slice(0, 1);

    if (topAssignees.length > 0) {
      const [assignee, stats] = topAssignees[0];
      const avgDays = stats.totalDays / stats.resolved;
      const diff = ((overallAvgDays - avgDays) / overallAvgDays) * 100;
      if (diff > 20) {
        results.push({
          type: 'fast_resolver',
          entity: assignee,
          entityType: 'assignee',
          icon: User,
          avgDays: avgDays.toFixed(1),
          diff: diff.toFixed(0),
          sample: stats.resolved,
          insight: `${assignee} resolves escalations ${diff.toFixed(0)}% faster than average (${avgDays.toFixed(1)}d)`
        });
      }
    }

    return results.slice(0, 6);
  }, [tickets]);

  if (insights.length === 0) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        Not enough data to generate correlation insights (need more resolved escalations)
      </div>
    );
  }

  return (
    <div className="esc-correlations-container">
      {insights.map((insight, idx) => {
        const Icon = insight.icon;
        return (
          <div key={idx} className={`esc-correlation-card ${insight.type}`}>
            <div className="correlation-icon">
              <Icon size={16} />
            </div>
            <div className="correlation-content">
              <div className="correlation-entity">
                <span className={`entity-type ${insight.entityType}`}>{insight.entityType}</span>
                <span className="entity-name">{insight.entity}</span>
              </div>
              <div className="correlation-insight">{insight.insight}</div>
              <div className="correlation-meta">
                {insight.avgDays && <span><Clock size={10} /> {insight.avgDays}d avg</span>}
                {insight.sample && <span>Based on {insight.sample} resolved</span>}
                {insight.rate && <span className="rate-badge">{insight.rate}% critical</span>}
              </div>
            </div>
            {insight.isSlower !== undefined && (
              <div className={`correlation-indicator ${insight.isSlower ? 'slow' : 'fast'}`}>
                <TrendingUp size={14} style={{ transform: insight.isSlower ? 'rotate(45deg)' : 'rotate(-45deg)' }} />
                {Math.abs(insight.diff)}%
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};


/* ===== ESCALATION TREND CHART ===== */
const TREND_COLORS = [
  '#6366f1', '#8b5cf6', '#a855f7', '#d946ef', '#ec4899',
  '#f43f5e', '#f97316', '#eab308', '#84cc16', '#22c55e',
  '#14b8a6', '#06b6d4', '#3b82f6', '#2563eb'
];

const EscalationTrendChart = ({ data, loading }) => {
  const [viewMode, setViewMode] = useState('area');
  const [hoveredMonth, setHoveredMonth] = useState(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 220, gap: 8, color: 'var(--text-muted)' }}>
        <Loader size={16} className="spinning" /> Loading trend data...
      </div>
    );
  }

  if (!data || !data.months?.length) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 220, color: 'var(--text-muted)', fontSize: 13 }}>
        No trend data available
      </div>
    );
  }

  const { months, components, series, totals } = data;
  const maxTotal = Math.max(...totals, 1);
  const chartHeight = 200;
  const chartWidth = 800;
  const padding = { top: 15, right: 15, bottom: 30, left: 10 };

  const getComponentColor = (idx) => TREND_COLORS[idx % TREND_COLORS.length];

  const renderAreaChart = () => {
    const xStep = (chartWidth - padding.left - padding.right) / Math.max(months.length - 1, 1);
    const yScale = (v) => chartHeight - padding.bottom - ((v / maxTotal) * (chartHeight - padding.top - padding.bottom));

    const componentData = components.map((comp, compIdx) => {
      const values = series[comp] || [];
      return { name: comp, values, color: getComponentColor(compIdx) };
    });

    const cumulativeValues = months.map((_, monthIdx) => {
      let cumulative = 0;
      return componentData.map(comp => {
        const start = cumulative;
        cumulative += comp.values[monthIdx] || 0;
        return { start, end: cumulative };
      });
    });

    return (
      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} style={{ width: '100%', height: '100%', display: 'block' }} preserveAspectRatio="xMidYMid meet">
        <defs>
          {componentData.map((comp, idx) => (
            <linearGradient key={comp.name} id={`grad-${idx}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={comp.color} stopOpacity="0.7" />
              <stop offset="100%" stopColor={comp.color} stopOpacity="0.1" />
            </linearGradient>
          ))}
        </defs>

        {componentData.map((comp, compIdx) => {
          const points = months.map((_, monthIdx) => {
            const x = padding.left + monthIdx * xStep;
            const cumData = cumulativeValues[monthIdx][compIdx];
            return { x, yTop: yScale(cumData.end), yBottom: yScale(cumData.start) };
          });

          const areaPath = `
            M ${points[0].x} ${points[0].yTop}
            ${points.slice(1).map(p => `L ${p.x} ${p.yTop}`).join(' ')}
            L ${points[points.length - 1].x} ${points[points.length - 1].yBottom}
            ${points.slice(0, -1).reverse().map(p => `L ${p.x} ${p.yBottom}`).join(' ')}
            Z
          `;

          return (
            <path
              key={comp.name}
              d={areaPath}
              fill={`url(#grad-${compIdx})`}
              stroke={comp.color}
              strokeWidth="1.5"
              opacity={hoveredMonth !== null ? 0.6 : 0.85}
            />
          );
        }).reverse()}

        {months.map((month, idx) => {
          const x = padding.left + idx * xStep;
          return (
            <g key={idx}>
              <line x1={x} y1={chartHeight - padding.bottom} x2={x} y2={chartHeight - padding.bottom + 5} stroke="var(--border-color)" strokeWidth="1" />
              {(idx % Math.ceil(months.length / 6) === 0 || idx === months.length - 1) && (
                <text x={x} y={chartHeight - padding.bottom + 20} textAnchor="middle" fontSize="11" fill="var(--text-muted)">
                  {month.split(' ')[0]}
                </text>
              )}
              <rect
                x={x - xStep / 2}
                y={padding.top}
                width={xStep}
                height={chartHeight - padding.top - padding.bottom}
                fill="transparent"
                style={{ cursor: 'pointer' }}
                onMouseEnter={(e) => {
                  const rect = e.currentTarget.closest('svg').getBoundingClientRect();
                  setTooltipPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
                  setHoveredMonth(idx);
                }}
                onMouseMove={(e) => {
                  const rect = e.currentTarget.closest('svg').getBoundingClientRect();
                  setTooltipPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
                }}
                onMouseLeave={() => setHoveredMonth(null)}
              />
            </g>
          );
        })}

        <line x1={padding.left} y1={chartHeight - padding.bottom} x2={chartWidth - padding.right} y2={chartHeight - padding.bottom} stroke="var(--border-color)" strokeWidth="1" />
      </svg>
    );
  };

  const renderLineChart = () => {
    const xStep = (chartWidth - padding.left - padding.right) / Math.max(months.length - 1, 1);
    const yScale = (v) => chartHeight - padding.bottom - ((v / maxTotal) * (chartHeight - padding.top - padding.bottom));

    return (
      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} style={{ width: '100%', height: '100%', display: 'block' }} preserveAspectRatio="xMidYMid meet">
        {components.map((comp, compIdx) => {
          const values = series[comp] || [];
          const color = getComponentColor(compIdx);
          const pathD = values.map((v, i) => {
            const x = padding.left + i * xStep;
            const y = yScale(v);
            return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
          }).join(' ');

          return (
            <g key={comp}>
              <path d={pathD} fill="none" stroke={color} strokeWidth="2" opacity={hoveredMonth !== null ? 0.4 : 0.9} />
              {values.map((v, i) => (
                <circle
                  key={i}
                  cx={padding.left + i * xStep}
                  cy={yScale(v)}
                  r="4"
                  fill={color}
                  opacity={hoveredMonth === i ? 1 : 0.7}
                />
              ))}
            </g>
          );
        })}

        {months.map((month, idx) => {
          const x = padding.left + idx * xStep;
          return (
            <g key={idx}>
              {(idx % Math.ceil(months.length / 6) === 0 || idx === months.length - 1) && (
                <text x={x} y={chartHeight - padding.bottom + 20} textAnchor="middle" fontSize="11" fill="var(--text-muted)">
                  {month.split(' ')[0]}
                </text>
              )}
              <rect
                x={x - xStep / 2}
                y={padding.top}
                width={xStep}
                height={chartHeight - padding.top - padding.bottom}
                fill="transparent"
                style={{ cursor: 'pointer' }}
                onMouseEnter={(e) => {
                  const rect = e.currentTarget.closest('svg').getBoundingClientRect();
                  setTooltipPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
                  setHoveredMonth(idx);
                }}
                onMouseMove={(e) => {
                  const rect = e.currentTarget.closest('svg').getBoundingClientRect();
                  setTooltipPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
                }}
                onMouseLeave={() => setHoveredMonth(null)}
              />
            </g>
          );
        })}

        <line x1={padding.left} y1={chartHeight - padding.bottom} x2={chartWidth - padding.right} y2={chartHeight - padding.bottom} stroke="var(--border-color)" strokeWidth="1" />
      </svg>
    );
  };

  const hoveredData = hoveredMonth !== null ? {
    month: months[hoveredMonth],
    total: totals[hoveredMonth],
    breakdown: components.map((comp, idx) => ({
      name: comp,
      count: series[comp]?.[hoveredMonth] || 0,
      color: getComponentColor(idx)
    })).filter(b => b.count > 0).sort((a, b) => b.count - a.count)
  } : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 4 }}>
        <button
          onClick={() => setViewMode('area')}
          style={{
            padding: '4px 10px',
            fontSize: 11,
            borderRadius: 6,
            border: '1px solid var(--border-color)',
            background: viewMode === 'area' ? 'var(--accent-primary)' : 'var(--bg-secondary)',
            color: viewMode === 'area' ? '#fff' : 'var(--text-secondary)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            transition: 'all 0.15s'
          }}
        >
          <AreaChart size={12} /> Stacked
        </button>
        <button
          onClick={() => setViewMode('line')}
          style={{
            padding: '4px 10px',
            fontSize: 11,
            borderRadius: 6,
            border: '1px solid var(--border-color)',
            background: viewMode === 'line' ? 'var(--accent-primary)' : 'var(--bg-secondary)',
            color: viewMode === 'line' ? '#fff' : 'var(--text-secondary)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            transition: 'all 0.15s'
          }}
        >
          <LineChart size={12} /> Lines
        </button>
      </div>

      <div style={{ position: 'relative', height: 220 }}>
        {viewMode === 'area' ? renderAreaChart() : renderLineChart()}

        {hoveredData && (
          <div style={{
            position: 'absolute',
            left: Math.min(tooltipPos.x + 10, 280),
            top: Math.max(10, tooltipPos.y - 10),
            background: 'var(--bg-primary)',
            border: '1px solid var(--border-color)',
            borderRadius: 8,
            padding: '10px 14px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            pointerEvents: 'none',
            zIndex: 50,
            minWidth: 160,
            maxWidth: 220
          }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-dark)', marginBottom: 6 }}>
              {hoveredData.month}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 8, paddingBottom: 6, borderBottom: '1px solid var(--border-light)' }}>
              <span style={{ color: 'var(--text-muted)' }}>Total Escalations</span>
              <span style={{ fontWeight: 700, color: 'var(--text-dark)' }}>{hoveredData.total}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 150, overflowY: 'auto' }}>
              {hoveredData.breakdown.slice(0, 6).map((b, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2, background: b.color, flexShrink: 0 }} />
                  <span style={{ flex: 1, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.name}</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-dark)' }}>{b.count}</span>
                </div>
              ))}
              {hoveredData.breakdown.length > 6 && (
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textAlign: 'center' }}>
                  +{hoveredData.breakdown.length - 6} more
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', paddingTop: 8, borderTop: '1px solid var(--border-light)' }}>
        {components.slice(0, 10).map((comp, idx) => (
          <div key={comp} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--text-secondary)' }}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: getComponentColor(idx) }} />
            <span style={{ maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{comp}</span>
          </div>
        ))}
        {components.length > 10 && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>+{components.length - 10} more</span>
        )}
      </div>
    </div>
  );
};


/* ===== SIDE PANEL ===== */
const TicketSidePanel = ({ ticketKey, details, loading, onClose }) => {
  const [impactData, setImpactData] = useState(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [impactError, setImpactError] = useState(null);
  const [expandedSections, setExpandedSections] = useState({
    must_run: true,
    should_run: true,
    manual_qa: false,
    test_gaps: true,
  });

  // Reset impact data when ticket changes
  useEffect(() => {
    setImpactData(null);
    setImpactError(null);
  }, [ticketKey]);

  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  // Run deep AI analysis on all PRs for this ticket
  const runDeepAnalysis = async () => {
    if (!ticketKey || impactLoading) return;
    setImpactLoading(true);
    setImpactError(null);
    try {
      const result = await api.analyzeTicketWithAgents(ticketKey);
      const analysisData = result.analysis || result;
      if (result.status === 'no_prs') {
        setImpactError(result.message || 'No PRs found for this ticket');
        setImpactData(null);
        return;
      }
      // Merge impacted_features from root level into analysisData
      // (backend returns impacted_features at root level, not inside analysis)
      const mergedData = {
        ...analysisData,
        impacted_features: result.impacted_features || analysisData.impacted_features || [],
        pr_summary: result.pr_details?.[0] || analysisData.pr_summary,
      };
      setImpactData(mergedData);
    } catch (err) {
      setImpactError(err.message || 'Failed to analyze impact');
    } finally {
      setImpactLoading(false);
    }
  };

  // Analyze a single PR with the agent system
  const analyzePr = async (pr) => {
    if (!pr || impactLoading) return;
    setImpactLoading(true);
    setImpactError(null);
    try {
      const result = await api.analyzePrWithAgents(pr.owner, pr.repo, pr.pr_number, ticketKey);
      const analysisData = result.analysis || result;
      // Merge impacted_features from root level into analysisData
      const mergedData = {
        ...analysisData,
        impacted_features: result.impacted_features || analysisData.impacted_features || [],
        pr_summary: result.pr_summary || analysisData.pr_summary,
      };
      setImpactData(mergedData);
    } catch (err) {
      setImpactError(err.message || 'Failed to analyze PR');
    } finally {
      setImpactLoading(false);
    }
  };

  if (!ticketKey) return null;

  const resolutionDays = details ? calcResolutionDays(details.created, details.resolution_date || details.resolutiondate) : null;

  return (
    <>
      <div className="esc-panel-backdrop" onClick={onClose} />
      <div className="esc-panel-overlay">
        <div className="esc-panel-header">
          <h3><span style={{ color: '#6366f1', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{ticketKey}</span></h3>
          <button className="esc-panel-close" onClick={onClose}><X size={16} /></button>
        </div>

        <div className="esc-panel-actions">
          {details?.url && <a href={details.url} target="_blank" rel="noopener noreferrer" className="esc-panel-btn primary" style={{ textDecoration: 'none' }}><ExternalLink size={12} /> View in Jira</a>}
          <button className="esc-panel-btn" onClick={() => navigator.clipboard.writeText(details?.url || ticketKey)}><FileText size={12} /> Copy Link</button>
        </div>

        <div className="esc-panel-body">
          {loading && <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 20, justifyContent: 'center', color: 'var(--text-muted)' }}><Loader size={14} className="spinning" /> Loading...</div>}

          {details?.error && <div style={{ padding: 16, color: '#dc2626', fontSize: 13 }}>Failed to load: {details.error}</div>}

          {details && !details.error && !loading && (() => {
            const linkedAssignees = [...new Set(
              (details.linked_issues || []).map(li => li.assignee).filter(Boolean)
            )];
            return (
              <>
                {/* ========== AI IMPACT ANALYSIS - HERO SECTION ========== */}
                <div className="esc-ai-hero">
                  <div className="esc-ai-hero-header">
                    <div className="esc-ai-hero-title">
                      <div className="esc-ai-icon">
                        <Zap size={18} />
                      </div>
                      <div>
                        <h4>AI Test Impact Analysis</h4>
                        <p>Get AI-powered test recommendations based on PR changes</p>
                      </div>
                    </div>
                    {impactData && (
                      <button
                        onClick={() => { setImpactData(null); setImpactError(null); }}
                        className="esc-ai-reset-btn"
                        title="Clear analysis"
                      >
                        <X size={14} />
                      </button>
                    )}
                  </div>

                  {/* Analysis CTA when no data */}
                  {!impactData && !impactLoading && !impactError && (
                    <div className="esc-ai-cta">
                      {details.total_prs > 0 ? (
                        <>
                          <div className="esc-ai-cta-info">
                            <GitPullRequest size={16} />
                            <span><strong>{details.total_prs}</strong> PR{details.total_prs > 1 ? 's' : ''} linked to this escalation</span>
                          </div>
                          <button
                            onClick={runDeepAnalysis}
                            className="esc-ai-btn primary"
                          >
                            <Zap size={14} /> Run AI Analysis
                          </button>
                          <div className="esc-ai-cta-hint">
                            Analyzes PR changes, fetches code context, and matches test cases from TestRail
                          </div>
                        </>
                      ) : (
                        <div className="esc-ai-empty">
                          <Info size={16} />
                          <span>No PRs linked to this ticket. Link PRs to enable impact analysis.</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Loading state */}
                  {impactLoading && (
                    <div className="esc-ai-loading">
                      <div className="esc-ai-loading-animation">
                        <Loader size={24} className="spinning" />
                      </div>
                      <div className="esc-ai-loading-text">
                        <strong>Running AI Analysis...</strong>
                        <span>Analyzing PR changes, fetching code context, and matching test cases</span>
                      </div>
                      <div className="esc-ai-loading-steps">
                        <div className="step active"><CheckCircle size={12} /> Fetching PR details</div>
                        <div className="step active"><Loader size={12} className="spinning" /> Analyzing code changes</div>
                        <div className="step"><Clock size={12} /> Matching test cases</div>
                      </div>
                    </div>
                  )}

                  {/* Error state */}
                  {impactError && (
                    <div className="esc-ai-error">
                      <AlertTriangle size={16} />
                      <span>{impactError}</span>
                      <button onClick={() => { setImpactError(null); }} className="esc-ai-btn secondary small">
                        Dismiss
                      </button>
                    </div>
                  )}

                  {/* Analysis Results */}
                  {impactData && (
                    <div className="esc-ai-advanced-results">
                      {/* Impacted Features - Prominent Display */}
                      {impactData.impacted_features?.length > 0 && (
                        <div className="esc-impacted-features-section">
                          <div className="esc-impacted-features-header">
                            <Zap size={14} />
                            <span>Impacted Features</span>
                            <span className="esc-impacted-count">{impactData.impacted_features.length}</span>
                          </div>
                          <div className="esc-impacted-features-list">
                            {impactData.impacted_features.map((feature, i) => (
                              <span key={i} className="esc-impacted-feature-tag">
                                {feature}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Quick Stats */}
                      <div className="esc-ai-stats">
                        {impactData.must_run?.length > 0 && (
                          <div className="esc-ai-stat must-run">
                            <div className="stat-value">{impactData.must_run.length}</div>
                            <div className="stat-label">Must Run</div>
                          </div>
                        )}
                        {impactData.should_run?.length > 0 && (
                          <div className="esc-ai-stat should-run">
                            <div className="stat-value">{impactData.should_run.length}</div>
                            <div className="stat-label">Should Run</div>
                          </div>
                        )}
                        {impactData.manual_qa_scenarios?.length > 0 && (
                          <div className="esc-ai-stat manual-qa">
                            <div className="stat-value">{impactData.manual_qa_scenarios.length}</div>
                            <div className="stat-label">Manual QA</div>
                          </div>
                        )}
                        {impactData.test_gaps?.length > 0 && (
                          <div className="esc-ai-stat test-gap">
                            <div className="stat-value">{impactData.test_gaps.length}</div>
                            <div className="stat-label">Test Gaps</div>
                          </div>
                        )}
                      </div>

                      {/* PR Summary */}
                      {impactData.pr_summary && (
                        <div className="esc-impact-section">
                          <div className="esc-impact-header">
                            <GitPullRequest size={14} />
                            <span>PR Summary</span>
                          </div>
                          <div className="esc-pr-summary-card">
                            <div className="pr-title">{impactData.pr_summary.title}</div>
                            <div className="pr-stats">
                              <span>by {impactData.pr_summary.author}</span>
                              <span className="stat-pill add">+{impactData.pr_summary.total_additions || 0}</span>
                              <span className="stat-pill del">-{impactData.pr_summary.total_deletions || 0}</span>
                              <span>{impactData.pr_summary.files_changed || 0} files</span>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* JIRA Context Used */}
                      {impactData.jira_context_used && (
                        <div className="esc-impact-section">
                          <div className="esc-impact-header">
                            <FileText size={14} />
                            <span>JIRA Context</span>
                          </div>
                          <div className="esc-jira-context">
                            {impactData.jira_context_used.customer_scenario && (
                              <div className="jira-scenario">
                                <strong>Customer Scenario:</strong> {impactData.jira_context_used.customer_scenario}
                              </div>
                            )}
                            {impactData.jira_context_used.components?.length > 0 && (
                              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
                                {impactData.jira_context_used.components.map((c, i) => (
                                  <span key={i} className="esc-badge" style={{ background: '#f0f0ff', color: '#6366f1' }}>{c}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* MUST RUN Tests */}
                      {impactData.must_run?.length > 0 && (
                        <div className="esc-impact-section highlight-must">
                          <div 
                            className="esc-impact-header clickable" 
                            onClick={() => toggleSection('must_run')}
                          >
                            <div className="esc-impact-badge must-run">{impactData.must_run.length}</div>
                            <span>MUST RUN Tests</span>
                            <ChevronRight size={14} className={expandedSections.must_run ? 'rotated' : ''} style={{ marginLeft: 'auto' }} />
                          </div>
                          {expandedSections.must_run && (
                            <div className="esc-test-list">
                              {impactData.must_run.map((test, i) => (
                                <div key={i} className="esc-test-item must-run">
                                  <div className="test-header">
                                    <span className="test-id">{test.case_id}</span>
                                    <span className="test-run">{test.run_name}</span>
                                  </div>
                                  <div className="test-title">{test.title}</div>
                                  <div className="test-reason">{test.reason}</div>
                                  {test.testrail_url && (
                                    <a href={test.testrail_url} target="_blank" rel="noopener noreferrer" className="test-link">
                                      <ExternalLink size={10} /> TestRail
                                    </a>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* SHOULD RUN Tests */}
                      {impactData.should_run?.length > 0 && (
                        <div className="esc-impact-section">
                          <div 
                            className="esc-impact-header clickable" 
                            onClick={() => toggleSection('should_run')}
                          >
                            <div className="esc-impact-badge should-run">{impactData.should_run.length}</div>
                            <span>SHOULD RUN Tests</span>
                            <ChevronRight size={14} className={expandedSections.should_run ? 'rotated' : ''} style={{ marginLeft: 'auto' }} />
                          </div>
                          {expandedSections.should_run && (
                            <div className="esc-test-list">
                              {impactData.should_run.map((test, i) => (
                                <div key={i} className="esc-test-item should-run">
                                  <div className="test-header">
                                    <span className="test-id">{test.case_id}</span>
                                    <span className="test-run">{test.run_name}</span>
                                  </div>
                                  <div className="test-title">{test.title}</div>
                                  <div className="test-reason">{test.reason}</div>
                                  {test.testrail_url && (
                                    <a href={test.testrail_url} target="_blank" rel="noopener noreferrer" className="test-link">
                                      <ExternalLink size={10} /> TestRail
                                    </a>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Manual QA Scenarios */}
                      {impactData.manual_qa_scenarios?.length > 0 && (
                        <div className="esc-impact-section">
                          <div 
                            className="esc-impact-header clickable" 
                            onClick={() => toggleSection('manual_qa')}
                          >
                            <div className="esc-impact-badge manual-qa">{impactData.manual_qa_scenarios.length}</div>
                            <span>Manual QA Scenarios</span>
                            <ChevronRight size={14} className={expandedSections.manual_qa ? 'rotated' : ''} style={{ marginLeft: 'auto' }} />
                          </div>
                          {expandedSections.manual_qa && (
                            <div className="esc-manual-qa-list">
                              {impactData.manual_qa_scenarios.map((scenario, i) => (
                                <div key={i} className="esc-manual-qa-item">
                                  <div className="scenario-title">{scenario.scenario}</div>
                                  {scenario.steps && (
                                    <div className="scenario-steps">
                                      <strong>Steps:</strong>
                                      <pre>{scenario.steps}</pre>
                                    </div>
                                  )}
                                  {scenario.verify && (
                                    <div className="scenario-verify">
                                      <strong>Verify:</strong> {scenario.verify}
                                    </div>
                                  )}
                                  <div className="scenario-reason">{scenario.reason}</div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Test Gaps */}
                      {impactData.test_gaps?.length > 0 && (
                        <div className="esc-impact-section highlight-gap">
                          <div 
                            className="esc-impact-header clickable" 
                            onClick={() => toggleSection('test_gaps')}
                          >
                            <div className="esc-impact-badge test-gap">{impactData.test_gaps.length}</div>
                            <span>Test Coverage Gaps</span>
                            <ChevronRight size={14} className={expandedSections.test_gaps ? 'rotated' : ''} style={{ marginLeft: 'auto' }} />
                          </div>
                          {expandedSections.test_gaps && (
                            <div className="esc-test-gaps-list">
                              {impactData.test_gaps.map((gap, i) => (
                                <div key={i} className="esc-test-gap-item">
                                  <div className="gap-area">{gap.area}</div>
                                  {gap.file && <div className="gap-file"><code>{gap.file}</code></div>}
                                  <div className="gap-issue">{gap.issue}</div>
                                  {gap.suggestion && (
                                    <div className="gap-suggestion">
                                      <strong>Suggestion:</strong> {gap.suggestion}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Empty state */}
                      {!impactData.must_run?.length && !impactData.should_run?.length && 
                       !impactData.manual_qa_scenarios?.length && !impactData.test_gaps?.length && (
                        <div className="esc-ai-empty">
                          No specific test recommendations generated
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* ========== TICKET INFO SECTION ========== */}
                {resolutionDays !== null && (
                  <div className="esc-resolution-box">
                    <div className="esc-resolution-icon"><CheckCircle size={16} style={{ color: '#16a34a' }} /></div>
                    <div className="esc-resolution-text">
                      Resolved in <strong>{resolutionDays}d</strong>
                      {details.resolution_date && <><br /><span style={{ fontSize: 11, opacity: 0.8 }}>{new Date(details.created).toLocaleDateString()} → {new Date(details.resolution_date).toLocaleDateString()}</span></>}
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
                  {details.priority && <span className="esc-badge" style={{ background: `${PRIORITY_COLORS[(details.priority || '').toLowerCase()] || '#6b7280'}15`, color: PRIORITY_COLORS[(details.priority || '').toLowerCase()] || '#6b7280' }}>{details.priority}</span>}
                  {details.customer && <span className="esc-badge" style={{ background: '#fff7ed', color: '#ea580c' }}>{details.customer}</span>}
                  {details.sub_component && <span className="esc-badge" style={{ background: '#eff6ff', color: '#2563eb' }}>{details.sub_component}</span>}
                  {details.fix_version_str && <span className="esc-badge" style={{ background: '#f0f0ff', color: '#6366f1' }}>{details.fix_version_str}</span>}
                </div>

                {/* Linked Pull Requests - Moved up */}
                <div className="esc-panel-section-title"><GitPullRequest size={12} /> Linked Pull Requests ({details.total_prs || 0})</div>
                {(details.pull_requests || []).length === 0
                  ? <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>No PRs linked</div>
                  : details.pull_requests.map((pr, i) => (
                    <div key={i} className="esc-panel-pr">
                      <div className="esc-panel-pr-title">
                        <a href={pr.url} target="_blank" rel="noopener noreferrer">{pr.name || `${pr.owner}/${pr.repo}#${pr.pr_number}`}</a>
                      </div>
                      <div className="esc-panel-pr-stats">
                        {pr.status && <span className="esc-badge" style={{ background: pr.status === 'MERGED' ? '#f3e8ff' : '#f0fdf4', color: pr.status === 'MERGED' ? '#7c3aed' : '#16a34a', fontSize: 10, padding: '1px 6px' }}>{pr.status}</span>}
                        {pr.owner && pr.repo && pr.pr_number && (
                          <button 
                            onClick={() => analyzePr(pr)}
                            className="esc-pr-analyze-btn"
                            disabled={impactLoading}
                            title="Analyze this PR for test recommendations"
                          >
                            <Zap size={10} /> Analyze
                          </button>
                        )}
                      </div>
                    </div>
                  ))
                }

                {/* People */}
                <div className="esc-panel-section-title"><User size={12} /> People</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 16px', padding: '8px 12px', background: 'var(--bg-subtle)', borderRadius: 8, border: '1px solid var(--border-light)', marginBottom: 4, fontSize: 12 }}>
                  {details.reporter && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>Reporter</span>
                      <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{details.reporter}</span>
                    </div>
                  )}
                  {details.assignee && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>Assignee</span>
                      <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{details.assignee}</span>
                    </div>
                  )}
                  {(details.all_qas && details.all_qas.length > 0 ? details.all_qas : details.qa ? [details.qa] : []).length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>QA</span>
                      <span style={{ color: '#8b5cf6', fontWeight: 500 }}>{(details.all_qas && details.all_qas.length > 0 ? details.all_qas : [details.qa]).join(', ')}</span>
                    </div>
                  )}
                  {linkedAssignees.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, gridColumn: linkedAssignees.length > 1 ? '1/3' : undefined }}>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>Linked Workitem Assignees</span>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {linkedAssignees.map((name, i) => (
                          <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 4, background: 'var(--bg-card)', border: '1px solid var(--border-color)', fontSize: 11, fontWeight: 500, color: 'var(--text-primary)' }}>
                            <span style={{ width: 14, height: 14, borderRadius: '50%', background: avatarColor(name), display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 7, fontWeight: 700, color: '#fff' }}>{initials(name)}</span>
                            {name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {details.description && (
                  <>
                    <div className="esc-panel-section-title"><FileText size={12} /> Description</div>
                    <div className="esc-panel-desc">{details.description}</div>
                  </>
                )}

                {(details.created || details.resolution_date) && (
                  <>
                    <div className="esc-panel-section-title"><Clock size={12} /> Resolution Timeline</div>
                    <div className="esc-timeline">
                      {details.created && <div className="esc-tl-item created"><div className="esc-tl-date">{new Date(details.created).toLocaleString()}</div><div className="esc-tl-text"><strong>Reported</strong> {details.reporter ? `by ${details.reporter}` : ''}</div></div>}
                      {details.assignee && <div className="esc-tl-item assigned"><div className="esc-tl-date">Assigned</div><div className="esc-tl-text"><strong>Assigned</strong> to {details.assignee}</div></div>}
                      {details.resolution_date && <div className="esc-tl-item resolved"><div className="esc-tl-date">{new Date(details.resolution_date).toLocaleString()}</div><div className="esc-tl-text"><strong>Resolved</strong> — {details.status}</div></div>}
                    </div>
                  </>
                )}

                {/* Linked Workitems */}
                {(details.linked_issues || []).length > 0 && (
                  <>
                    <div className="esc-panel-section-title"><Layers size={12} /> Linked Workitems ({details.linked_issues.length})</div>
                    {details.linked_issues.map((li, i) => (
                      <div key={i} className="esc-panel-pr" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                          <a href={li.url} target="_blank" rel="noopener noreferrer" style={{ color: '#6366f1', textDecoration: 'none', fontWeight: 600 }}>{li.key}</a>
                          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{li.direction}</span>
                          <span className="esc-badge" style={{ background: '#f0fdf4', color: '#15803d', fontSize: 9, padding: '1px 5px', marginLeft: 'auto' }}>{li.status}</span>
                        </div>
                        <span style={{ fontSize: 11, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{li.summary}</span>
                        {li.assignee && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Assignee: <strong style={{ color: 'var(--text-primary)' }}>{li.assignee}</strong></span>}
                      </div>
                    ))}
                  </>
                )}

                {details.labels?.length > 0 && (
                  <>
                    <div className="esc-panel-section-title"><Tag size={12} /> Labels</div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {details.labels.map((l, i) => <span key={i} style={{ padding: '2px 10px', borderRadius: 12, fontSize: 11, background: 'var(--bg-tertiary)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>{l}</span>)}
                    </div>
                  </>
                )}
              </>
            );
          })()}
        </div>
      </div>
    </>
  );
};


/* ===== MAIN COMPONENT ===== */
const CustomerEscalationsSection = ({ selectedRelease = DEFAULT_RELEASE }) => {
  const [summary, setSummary] = useState(null);
  const [tickets, setTickets] = useState(null);
  const [releases, setReleases] = useState(null);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [loadingTickets, setLoadingTickets] = useState(true);
  const [, setLoadingReleases] = useState(true);
  const [error, setError] = useState(null);

  const [releaseFilter, setReleaseFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [severityFilter, setSeverityFilter] = useState(null);

  const [selectedTicket, setSelectedTicket] = useState(null);
  const [ticketDetails, setTicketDetails] = useState({});
  const [loadingDetails, setLoadingDetails] = useState({});

  // Background PR count loading
  const [prCounts, setPrCounts] = useState({});
  const [loadingPrCounts, setLoadingPrCounts] = useState(false);

  // Escalation trends over time
  const [trends, setTrends] = useState(null);
  const [loadingTrends, setLoadingTrends] = useState(true);

  // AI-analyzed ticket features from cache
  const [ticketFeatures, setTicketFeatures] = useState({});
  const [loadingFeatures, setLoadingFeatures] = useState(true);

  // Insight card state (for deep-dive into customer or component)
  const [activeInsight, setActiveInsight] = useState({ type: null, value: null });

  // Feature filter for the table
  const [featureFilter, setFeatureFilter] = useState(null);

  // Tab navigation state
  const [activeTab, setActiveTab] = useState('overview');

  // Collapsible section states
  const [expandedSections, setExpandedSections] = useState({
    hero: true,
    severity: true,
    trend: true,
    charts: true,
    breakdowns: true,
    insights: true,
    filters: true,
    table: true,
    // Insights tab
    featureMatrix: true,
    correlations: true,
    // Patterns tab
    escalationPatterns: true,
    featureTimeline: true
  });

  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const fetchReleases = useCallback(async () => {
    setLoadingReleases(true);
    try {
      const data = await api.getEscalationReleases();
      setReleases(data?.releases || []);
    } catch (err) {
      console.error('Error fetching releases:', err);
    } finally {
      setLoadingReleases(false);
    }
  }, []);

  const fetchAllData = useCallback(async () => {
    setError(null);
    setSummary(null);
    setTickets(null);
    setLoadingSummary(true);
    setLoadingTickets(true);

    const summaryP = api.getAllEscalationsSummary()
      .then(data => setSummary(data))
      .catch(err => { console.error('Summary error:', err); setError(err.message || 'Failed to load'); })
      .finally(() => setLoadingSummary(false));

    const ticketsP = api.getAllEscalationTickets()
      .then(data => setTickets(data))
      .catch(err => console.error('Tickets error:', err))
      .finally(() => setLoadingTickets(false));

    await Promise.all([summaryP, ticketsP]);
  }, []);

  const fetchTrends = useCallback(async () => {
    setLoadingTrends(true);
    try {
      const data = await api.getEscalationTrends(12);
      setTrends(data?.data || null);
    } catch (err) {
      console.error('Error fetching escalation trends:', err);
    } finally {
      setLoadingTrends(false);
    }
  }, []);

  const fetchTicketFeatures = useCallback(async () => {
    setLoadingFeatures(true);
    try {
      const data = await api.getTicketFeatures();
      setTicketFeatures(data?.ticket_features || {});
    } catch (err) {
      console.error('Error fetching ticket features:', err);
    } finally {
      setLoadingFeatures(false);
    }
  }, []);

  useEffect(() => { fetchReleases(); }, [fetchReleases]);
  useEffect(() => { fetchAllData(); }, [fetchAllData]);
  useEffect(() => { fetchTrends(); }, [fetchTrends]);
  useEffect(() => { fetchTicketFeatures(); }, [fetchTicketFeatures]);

  // Fetch PR counts in background after tickets are loaded
  useEffect(() => {
    if (!tickets?.tickets?.length || loadingPrCounts) return;

    const ticketKeys = tickets.tickets.map(t => t.key).filter(Boolean);
    if (ticketKeys.length === 0) return;

    // Check if we already have all PR counts
    const missingKeys = ticketKeys.filter(k => prCounts[k] === undefined);
    if (missingKeys.length === 0) return;

    const fetchPrCounts = async () => {
      setLoadingPrCounts(true);
      try {
        // Fetch in batches of 20 to show progress
        const BATCH_SIZE = 20;
        for (let i = 0; i < missingKeys.length; i += BATCH_SIZE) {
          const batch = missingKeys.slice(i, i + BATCH_SIZE);
          const result = await api.getTicketPrCounts(batch);
          if (result?.pr_counts) {
            setPrCounts(prev => ({ ...prev, ...result.pr_counts }));
          }
        }
      } catch (err) {
        console.error('Error fetching PR counts:', err);
      } finally {
        setLoadingPrCounts(false);
      }
    };

    fetchPrCounts();
  }, [tickets]); // eslint-disable-line react-hooks/exhaustive-deps

  const openPanel = async (key) => {
    setSelectedTicket(key);
    if (!ticketDetails[key]) {
      setLoadingDetails(prev => ({ ...prev, [key]: true }));
      try {
        const d = await api.getEscalationTicketDetails(key);
        setTicketDetails(prev => ({ ...prev, [key]: d }));
      } catch (err) {
        setTicketDetails(prev => ({ ...prev, [key]: { error: err.message } }));
      } finally {
        setLoadingDetails(prev => ({ ...prev, [key]: false }));
      }
    }
  };

  const allTickets = useMemo(() => (tickets?.tickets || []).filter(t => isResolved(t.status)), [tickets]);

  const filteredTickets = useMemo(() => {
    let list = allTickets;
    if (releaseFilter !== 'all') {
      const releaseNum = releaseFilter.replace(/^R/i, '');
      list = list.filter(t => (t.fix_versions || []).some(v => {
        const versionNum = (v || '').split('.')[0];
        return versionNum === releaseNum;
      }));
    }
    if (severityFilter) {
      const tier = SEVERITY_TIERS.find(s => s.label === severityFilter);
      if (tier) list = list.filter(t => tier.keys.includes((t.priority || '').toLowerCase()));
    }
    if (featureFilter) {
      list = list.filter(t => {
        const features = ticketFeatures[t.key]?.impacted_features || [];
        return features.includes(featureFilter);
      });
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(t => {
        const features = ticketFeatures[t.key]?.impacted_features || [];
        return (t.key || '').toLowerCase().includes(q) ||
          (t.summary || '').toLowerCase().includes(q) ||
          (t.customer || '').toLowerCase().includes(q) ||
          (t.sub_component || '').toLowerCase().includes(q) ||
          (t.assignee || '').toLowerCase().includes(q) ||
          (t.qa || '').toLowerCase().includes(q) ||
          (t.linked_assignees || []).some(a => a.toLowerCase().includes(q)) ||
          (t.fix_version_str || '').toLowerCase().includes(q) ||
          features.some(f => f.toLowerCase().includes(q));
      });
    }
    return list;
  }, [allTickets, releaseFilter, severityFilter, featureFilter, searchQuery, ticketFeatures]);

  // Get unique AI features for filter dropdown
  const uniqueFeatures = useMemo(() => {
    const featureSet = new Set();
    Object.values(ticketFeatures).forEach(tf => {
      (tf.impacted_features || []).forEach(f => featureSet.add(f));
    });
    return Array.from(featureSet).sort();
  }, [ticketFeatures]);

  // Count of tickets with AI features
  const ticketsWithFeatures = useMemo(() => {
    return allTickets.filter(t => (ticketFeatures[t.key]?.impacted_features || []).length > 0).length;
  }, [allTickets, ticketFeatures]);

  // Top AI features with counts (aggregated from all analyzed tickets)
  const topAiFeatures = useMemo(() => {
    const featureCounts = {};
    Object.values(ticketFeatures).forEach(tf => {
      (tf.impacted_features || []).forEach(f => {
        featureCounts[f] = (featureCounts[f] || 0) + 1;
      });
    });
    return Object.entries(featureCounts)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [ticketFeatures]);

  const severityCounts = useMemo(() => {
    return SEVERITY_TIERS.map(tier => {
      const matching = allTickets.filter(t => tier.keys.includes((t.priority || '').toLowerCase()));
      return { ...tier, count: matching.length };
    });
  }, [allTickets]);

  const totalCount = allTickets.length;
  const criticalCount = severityCounts[0]?.count || 0;
  const customerCount = (summary?.by_customer || []).length;
  const topCustomer = (summary?.by_customer || [])[0];

  // Compute PR count from background-loaded data
  const ticketsWithPrs = useMemo(() => {
    return allTickets.filter(t => (prCounts[t.key] || 0) > 0).length;
  }, [allTickets, prCounts]);
  const totalPrCount = useMemo(() => {
    return Object.values(prCounts).reduce((sum, c) => sum + c, 0);
  }, [prCounts]);

  const priorityColor = (p) => PRIORITY_COLORS[(p || '').toLowerCase()] || '#6b7280';

  return (
    <div className="customer-escalations-section">
      {/* Page Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1><AlertTriangle size={24} /> Customer Escalation Analysis</h1>
          <p>Post-mortem insights on resolved escalations — patterns, resolution speed, and impact areas</p>
          <span style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
            <Clock size={12} />
            Showing resolved escalations since January 2025
          </span>
        </div>
        <div className="header-right" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className={`esc-filter-pill ${!severityFilter ? 'active' : ''}`} onClick={() => setSeverityFilter(null)}>All</button>
          <button className={`esc-filter-pill ${severityFilter === 'Critical' ? 'active' : ''}`} onClick={() => setSeverityFilter(severityFilter === 'Critical' ? null : 'Critical')}>Critical</button>
          <button className={`esc-filter-pill ${severityFilter === 'High' ? 'active' : ''}`} onClick={() => setSeverityFilter(severityFilter === 'High' ? null : 'High')}>High</button>
          <button
            onClick={() => fetchAllData()}
            disabled={loadingSummary || loadingTickets}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '8px 16px', borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-color)', background: 'var(--bg-card)',
              color: 'var(--text-primary)', cursor: 'pointer', fontSize: 13,
              fontFamily: 'var(--font-body)',
            }}
          >
            <RefreshCw size={14} className={loadingSummary ? 'spinning' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Tech Preview Banner */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '14px 18px',
        background: 'linear-gradient(135deg, #fef2f2, #fff1f2)',
        border: '2px solid #fca5a5', borderRadius: 'var(--radius-md)',
        marginBottom: 20, fontSize: 14,
        boxShadow: '0 2px 8px rgba(220, 38, 38, 0.08)',
      }}>
        <AlertTriangle size={20} style={{ color: '#dc2626', flexShrink: 0 }} />
        <span style={{ color: '#991b1b' }}>
          <strong style={{ color: '#dc2626', fontSize: 15 }}>Tech Preview</strong>
          <span style={{ margin: '0 6px', opacity: 0.4 }}>|</span>
          Data and analysis results may be incomplete.
        </span>
      </div>

      {error && <div style={{ padding: '12px 16px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius-md)', color: '#dc2626', fontSize: 13, marginBottom: 16 }}>{error}</div>}

      {/* ===== TAB NAVIGATION ===== */}
      <div className="esc-tabs-container">
        <div className="esc-tabs">
          {TABS.map(tab => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                className={`esc-tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon size={16} />
                <span>{tab.label}</span>
                {tab.id === 'tickets' && <span className="esc-tab-badge">{totalCount}</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* ===== TAB CONTENT ===== */}
      <div className="esc-tab-content">

      {/* ==================== OVERVIEW TAB ==================== */}
      {activeTab === 'overview' && (
        <>
          {/* Hero Summary */}
          <CollapsibleSection
            title="Key Metrics"
            icon={BarChart3}
            iconColor="#6366f1"
            isExpanded={expandedSections.hero}
            onToggle={() => toggleSection('hero')}
          >
            {loadingSummary ? <HeroSkeleton /> : summary && (
              <div className="esc-hero esc-fade-in">
                <div className="esc-hero-stats esc-hero-stats-6">
                  <div className="esc-hero-card">
                    <div className="esc-hero-icon" style={{ background: '#f0f0ff', color: '#6366f1' }}><FileText size={16} /></div>
                    <div className="esc-hero-value">{loadingTickets ? <Loader size={16} className="spinning" /> : totalCount}</div>
                    <div className="esc-hero-label">Total Escalations</div>
                    <div className="esc-hero-sub">All resolved</div>
                  </div>
                  <div className="esc-hero-card">
                    <div className="esc-hero-icon" style={{ background: '#eff6ff', color: '#2563eb' }}><GitPullRequest size={16} /></div>
                    <div className="esc-hero-value">
                      {loadingTickets ? <Loader size={16} className="spinning" /> : (
                        loadingPrCounts ? (
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            {ticketsWithPrs > 0 ? ticketsWithPrs : '—'}
                            <Loader size={12} className="spinning" style={{ opacity: 0.5 }} />
                          </span>
                        ) : ticketsWithPrs
                      )}
                    </div>
                    <div className="esc-hero-label">Linked PRs</div>
                    <div className="esc-hero-sub">
                      {loadingPrCounts ? 'Loading...' : `${totalPrCount} total PRs`}
                    </div>
                  </div>
                  <div className="esc-hero-card">
                    <div className="esc-hero-icon" style={{ background: '#f5f3ff', color: '#8b5cf6' }}><Clock size={16} /></div>
                    <div className="esc-hero-value">{summary.mttr?.avg_days ?? '—'}<span style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-muted)' }}>d</span></div>
                    <div className="esc-hero-label">Avg Resolution</div>
                    <div className="esc-hero-sub">Median: {summary.mttr?.median_days ?? '—'}d</div>
                  </div>
                  <div className="esc-hero-card">
                    <div className="esc-hero-icon" style={{ background: '#fef2f2', color: '#dc2626' }}><AlertTriangle size={16} /></div>
                    <div className="esc-hero-value">{loadingTickets ? <Loader size={16} className="spinning" /> : criticalCount}</div>
                    <div className="esc-hero-label">Critical</div>
                    <div className="esc-hero-sub">{loadingTickets ? '...' : (criticalCount > 0 ? `${Math.round((criticalCount / totalCount) * 100)}% of total` : 'None')}</div>
                  </div>
                  <div className="esc-hero-card">
                    <div className="esc-hero-icon" style={{ background: '#f0fdf4', color: '#16a34a' }}><Building2 size={16} /></div>
                    <div className="esc-hero-value">{customerCount}</div>
                    <div className="esc-hero-label">Customers</div>
                    <div className="esc-hero-sub">{topCustomer ? `${topCustomer.customer}: ${topCustomer.count}` : 'N/A'}</div>
                  </div>
                  <div className="esc-hero-card esc-hero-card-ai">
                    <div className="esc-hero-icon" style={{ background: '#faf5ff', color: '#7c3aed' }}><Zap size={16} /></div>
                    <div className="esc-hero-value">
                      {loadingFeatures ? <Loader size={16} className="spinning" /> : uniqueFeatures.length}
                    </div>
                    <div className="esc-hero-label">AI Features</div>
                    <div className="esc-hero-sub">
                      {loadingFeatures ? 'Loading...' : (
                        ticketsWithFeatures > 0 
                          ? `${ticketsWithFeatures} tickets analyzed`
                          : 'Run AI analysis on tickets'
                      )}
                    </div>
                    {uniqueFeatures.length > 0 && (
                      <div className="esc-hero-features-preview">
                        {uniqueFeatures.slice(0, 3).map((f, i) => (
                          <span key={i} className="esc-hero-feature-tag" onClick={() => { setFeatureFilter(f); setActiveTab('tickets'); }}>
                            {f.length > 10 ? f.slice(0, 10) + '…' : f}
                          </span>
                        ))}
                        {uniqueFeatures.length > 3 && (
                          <span className="esc-hero-feature-more">+{uniqueFeatures.length - 3}</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </CollapsibleSection>

          {/* Severity Heatmap */}
          <CollapsibleSection
            title="Severity Distribution"
            icon={AlertTriangle}
            iconColor="#ea580c"
            isExpanded={expandedSections.severity}
            onToggle={() => toggleSection('severity')}
          >
            {!loadingSummary && !loadingTickets && summary && (
              <div className="esc-severity-grid esc-fade-in">
                {severityCounts.map(tier => {
                  const pct = totalCount > 0 ? Math.round((tier.count / totalCount) * 100) : 0;
                  return (
                    <div key={tier.label} className={`esc-severity-block ${tier.cls} ${severityFilter === tier.label ? 'active' : ''}`}
                      onClick={() => { setSeverityFilter(severityFilter === tier.label ? null : tier.label); setActiveTab('tickets'); }}>
                      <div className="esc-sev-pct">{pct}%</div>
                      <div className="esc-sev-count">{tier.count}</div>
                      <div className="esc-sev-label">{tier.label}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </CollapsibleSection>

          {/* Escalation Trend Over Time */}
          <CollapsibleSection
            title="Escalation Trend Over Time"
            icon={TrendingUp}
            iconColor="#6366f1"
            isExpanded={expandedSections.trend}
            onToggle={() => toggleSection('trend')}
            badge={trends?.months?.length ? `${trends.months.length} months` : null}
          >
            <div className="esc-card" style={{ width: '100%', border: 'none', boxShadow: 'none' }}>
              <div style={{ padding: '12px 0' }}>
                <EscalationTrendChart data={trends} loading={loadingTrends} />
              </div>
            </div>
          </CollapsibleSection>

          {/* Charts Row: Donut + MTTR + Distribution */}
          <CollapsibleSection
            title="Resolution Analytics"
            icon={Clock}
            iconColor="#8b5cf6"
            isExpanded={expandedSections.charts}
            onToggle={() => toggleSection('charts')}
          >
            {!loadingSummary && !loadingTickets && summary && (
              <div className="esc-insights-row esc-fade-in">
                <div className="esc-card">
                  <div className="esc-card-header">
                    <h3><BarChart3 size={15} style={{ color: '#6366f1' }} /> Escalations by Release</h3>
                    <span className="esc-card-subtitle">{releases?.length || 0} releases</span>
                  </div>
                  <div className="esc-card-body">
                    <ReleaseDonut releases={releases} />
                  </div>
                </div>
                <div className="esc-card">
                  <div className="esc-card-header">
                    <h3><Clock size={15} style={{ color: '#8b5cf6' }} /> Mean Time to Resolve</h3>
                    <span className="esc-card-subtitle">{summary.mttr?.sample_size || 0} tickets</span>
                  </div>
                  <div className="esc-card-body">
                    <MttrGauge mttr={summary.mttr} />
                  </div>
                </div>
                <div className="esc-card">
                  <div className="esc-card-header">
                    <h3><BarChart3 size={15} style={{ color: '#16a34a' }} /> Resolution Speed</h3>
                    <span className="esc-card-subtitle">How fast are we fixing?</span>
                  </div>
                  <div className="esc-card-body">
                    <ResolutionDistribution tickets={allTickets} />
                  </div>
                </div>
              </div>
            )}
          </CollapsibleSection>
        </>
      )}

      {/* ==================== TICKETS TAB ==================== */}
      {activeTab === 'tickets' && (
        <>
          {/* Table Controls */}
      {!loadingTickets && tickets && (
        <div className="esc-table-controls esc-fade-in">
          <div className="esc-search-wrap">
            <Search size={14} />
            <input className="esc-search-input" placeholder="Search by key, summary, customer, feature, version, assignee..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
          </div>
          <span className="esc-table-stat">
            Showing <strong>{filteredTickets.length}</strong> of {totalCount} resolved
            {ticketsWithFeatures > 0 && (
              <span style={{ marginLeft: 8, color: '#7c3aed', fontSize: 11 }}>
                <Zap size={10} style={{ verticalAlign: 'middle', marginRight: 2 }} />
                {ticketsWithFeatures} AI-analyzed
              </span>
            )}
          </span>
          <select className="esc-release-select" value={releaseFilter} onChange={e => setReleaseFilter(e.target.value)}>
            <option value="all">All Releases</option>
            {(releases || []).map(r => <option key={r.release_id || r.id} value={r.release_id || r.id}>{r.release_id || r.id}</option>)}
          </select>
          {uniqueFeatures.length > 0 && (
            <select 
              className="esc-feature-select" 
              value={featureFilter || ''} 
              onChange={e => setFeatureFilter(e.target.value || null)}
              style={{
                padding: '6px 10px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-color)',
                background: featureFilter ? '#f5f3ff' : 'var(--bg-card)',
                color: featureFilter ? '#7c3aed' : 'var(--text-primary)',
                fontSize: 12,
                cursor: 'pointer',
                fontWeight: featureFilter ? 600 : 400,
              }}
            >
              <option value="">All Features</option>
              {uniqueFeatures.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          )}
          {featureFilter && (
            <button
              onClick={() => setFeatureFilter(null)}
              style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '4px 8px', borderRadius: 4,
                border: 'none', background: '#7c3aed', color: '#fff',
                fontSize: 11, cursor: 'pointer',
              }}
            >
              <X size={12} /> Clear
            </button>
          )}
        </div>
      )}

      {/* Ticket Table */}
      {loadingTickets ? <TableSkeleton /> : tickets && (
        <div className="esc-table esc-fade-in">
          <div className="esc-table-header esc-table-header-with-features">
            <span></span>
            <span>Key</span>
            <span>Summary</span>
            <span>Fix Version</span>
            <span>Customer</span>
            <span>Sub-Component</span>
            <span className="esc-header-features"><Zap size={11} /> Impacted Features</span>
            <span>Assignee</span>
            <span>Resolved In</span>
            <span>PRs</span>
            <span></span>
          </div>
          {filteredTickets.length === 0 ? (
            <div className="esc-empty-table">No escalation tickets match your filters</div>
          ) : filteredTickets.map(ticket => {
            const days = calcResolutionDays(ticket.created, ticket.resolution_date);
            const component = (ticket.sub_component && ticket.sub_component !== 'Unknown')
              ? ticket.sub_component : '—';
            const assigneeName = (ticket.assignee || 'Unassigned').replace(/\s*-\s*$/, '');
            const aiFeatures = ticketFeatures[ticket.key]?.impacted_features || [];
            return (
              <div key={ticket.key} className={`esc-table-row esc-table-row-with-features ${selectedTicket === ticket.key ? 'selected' : ''}`} onClick={() => openPanel(ticket.key)}>
                <div className="esc-priority-stripe" style={{ background: priorityColor(ticket.priority) }} />
                <span className="esc-cell-key">
                  <a href={ticket.url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>{ticket.key}</a>
                </span>
                <span className="esc-cell-summary" title={ticket.summary}>{ticket.summary}</span>
                <span className="esc-cell-version" title={ticket.fix_version_str || '—'}>{ticket.fix_version_str || '—'}</span>
                <span className="esc-cell-text" title={ticket.customer}>{ticket.customer || '—'}</span>
                <span className="esc-cell-text" title={component}>{component}</span>
                <span className="esc-cell-features" title={aiFeatures.join(', ')}>
                  {aiFeatures.length > 0 ? (
                    <div className="esc-feature-badges">
                      {aiFeatures.slice(0, 2).map((f, i) => (
                        <span 
                          key={i} 
                          className="esc-feature-badge"
                          onClick={(e) => { e.stopPropagation(); setFeatureFilter(f); }}
                          title={`Filter by ${f}`}
                        >
                          {f.length > 12 ? f.slice(0, 12) + '…' : f}
                        </span>
                      ))}
                      {aiFeatures.length > 2 && (
                        <span className="esc-feature-more">+{aiFeatures.length - 2}</span>
                      )}
                    </div>
                  ) : (
                    <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>
                  )}
                </span>
                <span className="esc-cell-assignee" title={[assigneeName, ...(ticket.linked_assignees || [])].join(', ')}>
                  <span className="esc-avatar-sm" style={{ background: avatarColor(assigneeName) }}>{initials(assigneeName)}</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{assigneeName}</span>
                  {(ticket.linked_assignees || []).length > 0 && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', marginLeft: -2 }}>
                      {ticket.linked_assignees.slice(0, 2).map((la, li) => (
                        <span key={li} className="esc-avatar-sm" style={{ background: avatarColor(la), marginLeft: -4, border: '1.5px solid var(--bg-card)', fontSize: 8 }} title={la}>{initials(la)}</span>
                      ))}
                      {ticket.linked_assignees.length > 2 && <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 2 }}>+{ticket.linked_assignees.length - 2}</span>}
                    </span>
                  )}
                </span>
                <span className={`esc-cell-resolved ${resolvedClass(days)}`}>{days !== null ? `${days}d` : '—'}</span>
                <span className="esc-cell-prs" title="Click to view PRs in details">
                  {prCounts[ticket.key] !== undefined ? (
                    prCounts[ticket.key] > 0 ? (
                      <><GitPullRequest size={13} /> {prCounts[ticket.key]}</>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )
                  ) : (
                    <Loader size={12} className="spinning" style={{ opacity: 0.5 }} />
                  )}
                </span>
                <span className="esc-cell-expand"><ChevronRight size={14} /></span>
              </div>
            );
          })}
        </div>
      )}
        </>
      )}

      {/* ==================== INSIGHTS TAB ==================== */}
      {activeTab === 'insights' && (
        <>
          {/* Breakdown Analysis */}
          <CollapsibleSection
            title="Breakdown Analysis"
            icon={Layers}
            iconColor="#2563eb"
            isExpanded={expandedSections.breakdowns}
            onToggle={() => toggleSection('breakdowns')}
          >
            {!loadingSummary && !loadingTickets && summary && (
              <div className="esc-breakdowns esc-fade-in">
                {/* By Assignee */}
                <div className="esc-bd-card">
                  <div className="esc-bd-header">
                    <div className="esc-bd-icon" style={{ background: '#f0f0ff', color: '#6366f1' }}><User size={14} /></div>
                    <span className="esc-bd-title">By Assignee</span>
                    <span className="esc-bd-count">{(summary.by_assignee || []).length}</span>
                  </div>
                  <div className="esc-bd-scroll">
                    {(summary.by_assignee || []).map((a, i) => {
                      const max = (summary.by_assignee || [])[0]?.count || 1;
                      const assigneeTicketKeys = allTickets
                        .filter(t => (t.assignee || 'Unassigned') === a.assignee)
                        .map(t => t.key)
                        .filter(Boolean);
                      const jiraUrl = assigneeTicketKeys.length > 0
                        ? `https://your-org.atlassian.net/issues/?jql=${encodeURIComponent(`key IN (${assigneeTicketKeys.join(',')})`)}`
                        : null;
                      return (
                        <div key={i} className="esc-bd-item">
                          <div className="esc-bd-avatar" style={{ background: avatarColor(a.assignee) }}>{initials(a.assignee)}</div>
                          <span className="esc-bd-name">{a.assignee}</span>
                          <div className="esc-bd-bar-wrap"><div className="esc-bd-bar" style={{ width: `${(a.count / max) * 100}%`, background: avatarColor(a.assignee) }} /></div>
                          {jiraUrl ? (
                            <a 
                              href={jiraUrl} 
                              target="_blank" 
                              rel="noopener noreferrer" 
                              className="esc-bd-val esc-bd-val-clickable"
                              title={`Open ${a.count} ticket(s) in JIRA`}
                              onClick={(e) => e.stopPropagation()}
                            >
                              {a.count}
                            </a>
                          ) : (
                            <span className="esc-bd-val">{a.count}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  {(summary.by_assignee || []).length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 8 }}>No data</div>}
                </div>

                {/* By Priority */}
                <div className="esc-bd-card">
                  <div className="esc-bd-header">
                    <div className="esc-bd-icon" style={{ background: '#fff7ed', color: '#ea580c' }}><AlertTriangle size={14} /></div>
                    <span className="esc-bd-title">By Priority</span>
                  </div>
                  {Object.entries(summary.by_priority || {})
                    .sort(([a], [b]) => (PRIORITY_ORDER.indexOf(a.toLowerCase()) === -1 ? 99 : PRIORITY_ORDER.indexOf(a.toLowerCase())) - (PRIORITY_ORDER.indexOf(b.toLowerCase()) === -1 ? 99 : PRIORITY_ORDER.indexOf(b.toLowerCase())))
                    .map(([p, count]) => (
                      <div key={p} className="esc-priority-pill" style={{ background: `${priorityColor(p)}12`, color: priorityColor(p) }}>
                        <span>● {p}</span><span>{count}</span>
                      </div>
                    ))
                  }
                  {Object.keys(summary.by_priority || {}).length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 8 }}>No data</div>}
                </div>

                {/* Top Features based on AI Analysis */}
                <div className="esc-bd-card esc-bd-card-ai">
                  <div className="esc-bd-header">
                    <div className="esc-bd-icon" style={{ background: '#faf5ff', color: '#7c3aed' }}><Zap size={14} /></div>
                    <span className="esc-bd-title">Top Features based on AI Analysis</span>
                    <span className="esc-bd-count" style={{ background: '#f5f3ff', color: '#7c3aed' }}>
                      {loadingFeatures ? '...' : topAiFeatures.length}
                    </span>
                  </div>
                  {loadingFeatures ? (
                    <div style={{ padding: 16, display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-muted)', fontSize: 12 }}>
                      <Loader size={14} className="spinning" /> Loading AI features...
                    </div>
                  ) : topAiFeatures.length > 0 ? (
                    <div className="esc-bd-scroll">
                      {topAiFeatures.map((f, i) => {
                        const max = topAiFeatures[0]?.count || 1;
                        const colors = ['#7c3aed', '#8b5cf6', '#a78bfa', '#c4b5fd', '#ddd6fe'];
                        const isFiltered = featureFilter === f.name;
                        return (
                          <div 
                            key={i} 
                            className={`esc-bd-item clickable ${isFiltered ? 'active' : ''}`}
                            onClick={() => { setFeatureFilter(isFiltered ? null : f.name); setActiveTab('tickets'); }}
                            title={`Click to filter tickets by ${f.name}`}
                          >
                            <div className="esc-bd-avatar" style={{ background: colors[i % colors.length], fontSize: 9 }}>
                              <Zap size={10} />
                            </div>
                            <span className="esc-bd-name" style={{ color: isFiltered ? '#7c3aed' : undefined }}>{f.name}</span>
                            <div className="esc-bd-bar-wrap">
                              <div className="esc-bd-bar" style={{ width: `${(f.count / max) * 100}%`, background: colors[i % colors.length] }} />
                            </div>
                            <span className="esc-bd-val" style={{ color: isFiltered ? '#7c3aed' : undefined }}>{f.count}</span>
                            {isFiltered && <Filter size={12} style={{ color: '#7c3aed' }} />}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="esc-bd-empty-ai">
                      <Info size={16} />
                      <span>No AI-analyzed features yet</span>
                      <span className="esc-bd-empty-hint">Run AI Analysis on individual tickets to populate this data</span>
                    </div>
                  )}
                </div>

                {/* By Component */}
                <div className="esc-bd-card">
                  <div className="esc-bd-header">
                    <div className="esc-bd-icon" style={{ background: '#eff6ff', color: '#2563eb' }}><Layers size={14} /></div>
                    <span className="esc-bd-title">By Sub-Component</span>
                    <span className="esc-bd-count">{(summary.by_component || []).length}</span>
                  </div>
                  <div className="esc-bd-scroll">
                    {(summary.by_component || []).map((c, i) => {
                      const max = (summary.by_component || [])[0]?.count || 1;
                      const colors = ['#2563eb','#3b82f6','#6366f1','#8b5cf6','#a78bfa','#c4b5fd'];
                      const isActive = activeInsight.type === 'component' && activeInsight.value === c.component;
                      return (
                        <div 
                          key={i} 
                          className={`esc-bd-item clickable ${isActive ? 'active' : ''}`}
                          onClick={() => setActiveInsight(
                            isActive ? { type: null, value: null } : { type: 'component', value: c.component }
                          )}
                          title={`Click to see insights for ${c.component}`}
                        >
                          <div className="esc-bd-avatar" style={{ background: colors[i % colors.length] }}>{initials(c.component)}</div>
                          <span className="esc-bd-name" title={c.component}>{c.component}</span>
                          <div className="esc-bd-bar-wrap"><div className="esc-bd-bar" style={{ width: `${(c.count / max) * 100}%`, background: colors[i % colors.length] }} /></div>
                          <span className="esc-bd-val">{c.count}</span>
                          <ChevronRight size={14} className={`esc-bd-arrow ${isActive ? 'rotated' : ''}`} />
                        </div>
                      );
                    })}
                  </div>
                  {(summary.by_component || []).length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 8 }}>No data</div>}
                  
                  {activeInsight.type === 'component' && (
                    <InsightCard
                      type="component"
                      value={activeInsight.value}
                      tickets={allTickets}
                      onClose={() => setActiveInsight({ type: null, value: null })}
                    />
                  )}
                </div>

                {/* By Customer */}
                <div className="esc-bd-card esc-bd-card-customers">
                  <div className="esc-bd-header">
                    <div className="esc-bd-icon" style={{ background: '#f0fdf4', color: '#059669' }}><Building2 size={14} /></div>
                    <span className="esc-bd-title">By Customer</span>
                    <span className="esc-bd-count">{(summary.by_customer || []).length}</span>
                  </div>
                  <div className="esc-bd-scroll">
                    {(summary.by_customer || []).map((c, i) => {
                      const max = (summary.by_customer || [])[0]?.count || 1;
                      const colors = ['#059669','#0d9488','#14b8a6','#2dd4bf','#5eead4','#99f6e4'];
                      const isActive = activeInsight.type === 'customer' && activeInsight.value === c.customer;
                      const impactedFeatures = c.impacted_features || [];
                      return (
                        <div 
                          key={i} 
                          className={`esc-bd-item-enhanced clickable ${isActive ? 'active' : ''}`}
                          onClick={() => setActiveInsight(
                            isActive ? { type: null, value: null } : { type: 'customer', value: c.customer }
                          )}
                        >
                          <div className="esc-bd-item-main">
                            <div className="esc-bd-avatar" style={{ background: colors[i % colors.length] }}>{initials(c.customer)}</div>
                            <span className="esc-bd-name">{c.customer}</span>
                            <div className="esc-bd-bar-wrap"><div className="esc-bd-bar" style={{ width: `${(c.count / max) * 100}%`, background: colors[i % colors.length] }} /></div>
                            <span className="esc-bd-val">{c.count}</span>
                            <ChevronRight size={14} className={`esc-bd-arrow ${isActive ? 'rotated' : ''}`} />
                          </div>
                          {impactedFeatures.length > 0 && (
                            <div className="esc-bd-features-row">
                              <Zap size={10} style={{ color: '#7c3aed', flexShrink: 0 }} />
                              <div className="esc-bd-features-list">
                                {impactedFeatures.slice(0, 3).map((f, fi) => (
                                  <span 
                                    key={fi} 
                                    className="esc-bd-feature-tag"
                                    onClick={(e) => { e.stopPropagation(); setFeatureFilter(f.name); setActiveTab('tickets'); }}
                                    title={`${f.name}: ${f.count} escalation${f.count > 1 ? 's' : ''}`}
                                  >
                                    {f.name.length > 12 ? f.name.slice(0, 12) + '…' : f.name}
                                    <span className="feature-count">{f.count}</span>
                                  </span>
                                ))}
                                {impactedFeatures.length > 3 && (
                                  <span className="esc-bd-feature-more">+{impactedFeatures.length - 3}</span>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  {(summary.by_customer || []).length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 8 }}>No data</div>}
                  
                  {activeInsight.type === 'customer' && (
                    <InsightCard
                      type="customer"
                      value={activeInsight.value}
                      tickets={allTickets}
                      onClose={() => setActiveInsight({ type: null, value: null })}
                      aiImpactedFeatures={
                        (summary.by_customer || []).find(c => c.customer === activeInsight.value)?.impacted_features
                      }
                    />
                  )}
                </div>
              </div>
            )}
          </CollapsibleSection>

          {/* Feature-to-Customer Matrix */}
          <CollapsibleSection
            title="Feature-to-Customer Matrix"
            icon={Grid3X3}
            iconColor="#6366f1"
            isExpanded={expandedSections.featureMatrix}
            onToggle={() => toggleSection('featureMatrix')}
          >
            {!loadingSummary && !loadingTickets && allTickets.length > 0 && (
              <FeatureCustomerMatrix tickets={allTickets} summary={summary} />
            )}
          </CollapsibleSection>

          {/* Correlation Insights */}
          <CollapsibleSection
            title="Correlation Insights"
            icon={TrendingUp}
            iconColor="#8b5cf6"
            isExpanded={expandedSections.correlations}
            onToggle={() => toggleSection('correlations')}
          >
            {!loadingSummary && !loadingTickets && allTickets.length > 0 && (
              <CorrelationInsights tickets={allTickets} summary={summary} />
            )}
          </CollapsibleSection>
        </>
      )}

      {/* ==================== PATTERNS TAB ==================== */}
      {activeTab === 'patterns' && (
        <>
          <CollapsibleSection
            title="Escalation Patterns"
            icon={Activity}
            iconColor="#dc2626"
            isExpanded={expandedSections.escalationPatterns}
            onToggle={() => toggleSection('escalationPatterns')}
            badge="Recurring Issues"
            tooltip="Customer + Component combinations with multiple escalations. The Nx badge indicates how many times this exact combination occurred. Patterns spanning multiple months are flagged as recurring issues that may need systemic fixes."
          >
            {!loadingSummary && !loadingTickets && allTickets.length > 0 && (
              <EscalationPatterns tickets={allTickets} summary={summary} />
            )}
          </CollapsibleSection>

          <CollapsibleSection
            title="Feature Timeline"
            icon={Calendar}
            iconColor="#059669"
            isExpanded={expandedSections.featureTimeline}
            onToggle={() => toggleSection('featureTimeline')}
            tooltip="Track when escalations started appearing for each component. Shows first/last occurrence, monthly trend (improving or worsening), and a sparkline of the last 6 months. Click any row to see the full monthly breakdown."
          >
            {!loadingSummary && !loadingTickets && allTickets.length > 0 && (
              <FeatureTimeline tickets={allTickets} />
            )}
          </CollapsibleSection>
        </>
      )}

      </div> {/* End of esc-tab-content */}

      {/* Side Panel - Always visible regardless of tab */}
      <TicketSidePanel
        ticketKey={selectedTicket}
        details={ticketDetails[selectedTicket]}
        loading={loadingDetails[selectedTicket]}
        onClose={() => setSelectedTicket(null)}
      />
    </div>
  );
};


/* ===== COLLAPSIBLE SECTION ===== */
const CollapsibleSection = ({ title, icon: Icon, iconColor, isExpanded, onToggle, badge, tooltip, children }) => (
  <div className={`esc-collapsible-section ${isExpanded ? 'expanded' : 'collapsed'}`}>
    <div className="esc-collapsible-header" onClick={onToggle}>
      <div className="esc-collapsible-title" title={tooltip || ''}>
        {Icon && <Icon size={16} style={{ color: iconColor || 'var(--text-secondary)' }} />}
        <span>{title}</span>
        {tooltip && <Info size={14} className="esc-collapsible-info" />}
        {badge && <span className="esc-collapsible-badge">{badge}</span>}
      </div>
      <ChevronDown size={18} className={`esc-collapsible-arrow ${isExpanded ? 'rotated' : ''}`} />
    </div>
    {isExpanded && <div className="esc-collapsible-content">{children}</div>}
  </div>
);


/* ===== TAB DEFINITIONS ===== */
const TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'tickets', label: 'Tickets', icon: List },
  { id: 'insights', label: 'Insights', icon: BrainCircuit },
  { id: 'patterns', label: 'Patterns', icon: Target },
];


/* ===== SKELETONS ===== */
const HeroSkeleton = () => (
  <div className="esc-skel-wrap">
    <div className="esc-skel-label"><Loader size={14} className="spinning" /><span>Loading summary...</span></div>
    <div className="esc-skel-cards">
      {[1,2,3,4,5].map(i => (
        <div key={i} className="esc-skel-card">
          <div className="sk-icon" />
          <div className="sk-value" />
          <div className="sk-label" />
        </div>
      ))}
    </div>
  </div>
);

const TableSkeleton = () => (
  <div className="esc-skel-wrap">
    <div className="esc-skel-label"><Loader size={14} className="spinning" /><span>Loading escalation tickets...</span></div>
    <div className="esc-skel-table">
      <div className="esc-skel-table-header">{[1,2,3,4,5,6,7,8].map(i => <div key={i} className="sk-col" />)}</div>
      {[1,2,3,4,5,6].map(i => (
        <div key={i} className="esc-skel-row">
          <div className="sk-cell s" /><div className="sk-cell w" /><div className="sk-cell m" />
          <div className="sk-cell m" /><div className="sk-cell s" /><div className="sk-cell m" />
          <div className="sk-cell s" /><div className="sk-cell s" />
        </div>
      ))}
    </div>
  </div>
);


export default CustomerEscalationsSection;
