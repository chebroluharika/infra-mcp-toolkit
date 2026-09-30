import React, { useState, useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  RefreshCw,
  AlertTriangle,
  Loader,
  Lightbulb,
  Link2,
  Calendar,
} from 'lucide-react';
import api from '../../services/api';
import './FeatureInsightsSection.css';

const PHASE_ICONS = {
  under_review: '🔍',
  design_in_progress: '✏️',
  implementation_in_progress: '🔧',
  beta: '🚀',
  other: '📋',
};

const SIGNAL_COLORS = { red: '#ef4444', amber: '#f59e0b', green: '#10b981' };
const SIGNAL_LABELS = { red: 'At Risk', amber: 'Watch', green: 'On Track' };

// ---------------------------------------------------------------------------
// Sunburst Chart (2-level: Group → NPLANs)
// ---------------------------------------------------------------------------
function FeatureSunburst({ data, onNplanClick, centerLabel, centerSubLabel }) {
  const svgRef = useRef(null);
  const [tooltip, setTooltip] = useState({ visible: false, x: 0, y: 0, content: '' });

  useEffect(() => {
    if (!data || !data.categories || data.categories.length === 0 || !svgRef.current) return;

    const width = 380;
    const height = 380;
    const radius = Math.min(width, height) / 2;
    const innerRadius = radius * 0.35;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const g = svg
      .attr('width', width)
      .attr('height', height)
      .append('g')
      .attr('transform', `translate(${width / 2},${height / 2})`);

    const hierarchyData = {
      name: 'Root',
      children: data.categories.map(cat => ({
        name: cat.name,
        color: cat.color,
        children: (cat.children || []).map(child => ({
          name: child.name,
          value: child.value,
          key: child.key,
          blocked: child.blocked || 0,
          signal: child.signal || 'green',
          color: cat.color,
        })),
      })),
    };

    const root = d3.hierarchy(hierarchyData)
      .sum(d => d.value || 0)
      .sort((a, b) => b.value - a.value);

    d3.partition().size([2 * Math.PI, radius])(root);

    const arc = d3.arc()
      .startAngle(d => d.x0)
      .endAngle(d => d.x1)
      .padAngle(0.008)
      .innerRadius(d => (d.depth === 1 ? innerRadius : innerRadius + (radius - innerRadius) * 0.45))
      .outerRadius(d => (d.depth === 1 ? innerRadius + (radius - innerRadius) * 0.42 : radius - 4));

    g.selectAll('path')
      .data(root.descendants().filter(d => d.depth > 0))
      .join('path')
      .attr('d', arc)
      .attr('fill', d => {
        if (d.depth === 2 && d.data.signal === 'red') {
          return d3.interpolate(d.data.color, '#ef4444')(0.5);
        }
        if (d.depth === 2 && d.data.signal === 'amber') {
          return d3.interpolate(d.data.color, '#f59e0b')(0.3);
        }
        return d.depth === 2
          ? d3.color(d.data.color).brighter(0.3).toString()
          : d.data.color;
      })
      .attr('stroke', '#fff')
      .attr('stroke-width', 1)
      .style('cursor', d => (d.depth === 2 ? 'pointer' : 'default'))
      .on('mouseover', (event, d) => {
        const label = d.depth === 1 ? `${d.data.name}: ${d.value} ENG tickets` : d.data.name;
        const extra = d.depth === 2 && d.data.blocked > 0 ? ` (${d.data.blocked} blocked)` : '';
        setTooltip({ visible: true, x: event.offsetX, y: event.offsetY, content: label + extra });
      })
      .on('mousemove', (event) => {
        setTooltip(prev => ({ ...prev, x: event.offsetX, y: event.offsetY }));
      })
      .on('mouseout', () => setTooltip({ visible: false, x: 0, y: 0, content: '' }))
      .on('click', (event, d) => {
        if (d.depth === 2 && d.data.key && onNplanClick) onNplanClick(d.data.key);
      });

    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '-0.2em')
      .style('font-size', '28px')
      .style('font-weight', '700')
      .style('fill', '#2d2a26')
      .text(centerLabel || root.value);

    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '1.2em')
      .style('font-size', '12px')
      .style('fill', '#8a8680')
      .text(centerSubLabel || 'ENG Tickets');
  }, [data, onNplanClick, centerLabel, centerSubLabel]);

  return (
    <div className="fi-sunburst-wrapper">
      <svg ref={svgRef} />
      {tooltip.visible && (
        <div className="fi-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y - 20 }}>
          {tooltip.content}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Health Signal Bar
// ---------------------------------------------------------------------------
function SignalBar({ counts, total }) {
  if (!counts || total === 0) return null;
  const red = counts.red || 0;
  const amber = counts.amber || 0;
  const green = counts.green || 0;

  return (
    <div className="fi-signal-section">
      <h3 className="fi-section-title">Health Signals</h3>
      <div className="fi-signal-cards">
        <div className="fi-signal-card fi-signal-red">
          <div className="fi-signal-dot" style={{ background: SIGNAL_COLORS.red }} />
          <div className="fi-signal-count">{red}</div>
          <div className="fi-signal-label">At Risk</div>
        </div>
        <div className="fi-signal-card fi-signal-amber">
          <div className="fi-signal-dot" style={{ background: SIGNAL_COLORS.amber }} />
          <div className="fi-signal-count">{amber}</div>
          <div className="fi-signal-label">Watch</div>
        </div>
        <div className="fi-signal-card fi-signal-green">
          <div className="fi-signal-dot" style={{ background: SIGNAL_COLORS.green }} />
          <div className="fi-signal-count">{green}</div>
          <div className="fi-signal-label">On Track</div>
        </div>
      </div>
      <div className="fi-signal-bar-track">
        {red > 0 && <div className="fi-signal-bar-seg red" style={{ width: `${(red / total) * 100}%` }} />}
        {amber > 0 && <div className="fi-signal-bar-seg amber" style={{ width: `${(amber / total) * 100}%` }} />}
        {green > 0 && <div className="fi-signal-bar-seg green" style={{ width: `${(green / total) * 100}%` }} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quarter View
// ---------------------------------------------------------------------------
function QuarterView({ quarterView, onNplanClick }) {
  const [selectedYear, setSelectedYear] = useState(null);

  useEffect(() => {
    if (quarterView && quarterView.available_years && quarterView.available_years.length > 0 && !selectedYear) {
      setSelectedYear(String(quarterView.available_years[quarterView.available_years.length - 1]));
    }
  }, [quarterView, selectedYear]);

  if (!quarterView || !quarterView.available_years || quarterView.available_years.length === 0) {
    return (
      <div className="fi-quarter-section">
        <h3 className="fi-section-title">Quarter View</h3>
        <div className="fi-empty">No delivery target data available for quarter mapping</div>
      </div>
    );
  }

  const { available_years, quarters, yearly_charts } = quarterView;
  const chartData = selectedYear ? yearly_charts[selectedYear] : null;
  const yearQuarters = (quarters || []).filter(q => String(q.year) === selectedYear);

  return (
    <div className="fi-quarter-section">
      <div className="fi-quarter-header">
        <h3 className="fi-section-title">
          <Calendar size={16} /> Quarter View
        </h3>
        <div className="fi-year-selector">
          {available_years.map(year => (
            <button
              key={year}
              className={`fi-year-btn ${String(year) === selectedYear ? 'active' : ''}`}
              onClick={() => setSelectedYear(String(year))}
            >
              CY{year}
            </button>
          ))}
        </div>
      </div>

      <div className="fi-quarter-content">
        {/* Quarter summary cards */}
        <div className="fi-quarter-cards">
          {['Q1', 'Q2', 'Q3', 'Q4'].map(q => {
            const qData = yearQuarters.find(yq => yq.quarter === q);
            const count = qData ? qData.nplans.length : 0;
            const breakdown = qData ? qData.status_breakdown : {};
            return (
              <div key={q} className={`fi-quarter-card ${count === 0 ? 'empty' : ''}`}>
                <div className="fi-quarter-card-header" style={{ borderTopColor: count > 0 ? qData.color : '#e0e0e0' }}>
                  <span className="fi-quarter-name">{q} {selectedYear}</span>
                  <span className="fi-quarter-count">{count} NPLANs</span>
                </div>
                {count > 0 && (
                  <div className="fi-quarter-breakdown">
                    {Object.entries(breakdown).map(([status, cnt]) => (
                      <div key={status} className="fi-qb-row">
                        <span className="fi-qb-status">{status}</span>
                        <span className="fi-qb-count">{cnt}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Quarter sunburst */}
        {chartData && chartData.categories && chartData.categories.length > 0 && (
          <div className="fi-quarter-chart">
            <FeatureSunburst
              data={chartData}
              onNplanClick={onNplanClick}
              centerLabel={selectedYear}
              centerSubLabel="by Quarter"
            />
            <div className="fi-chart-legend">
              {chartData.categories.map(cat => (
                <div key={cat.key} className="fi-legend-item">
                  <span className="fi-legend-dot" style={{ background: cat.color }} />
                  <span>{cat.name} ({cat.count})</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// NPLAN Row (extracted for signal indicator)
// ---------------------------------------------------------------------------
function NplanRow({ nplan, expanded, onToggle, onTabChange, activeTab, jiraBaseUrl }) {
  return (
    <div id={`fi-nplan-${nplan.key}`} className="fi-nplan-item">
      <div className="fi-nplan-row" onClick={onToggle}>
        <div className="fi-col-expand">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </div>
        <div className="fi-col-signal">
          <span
            className={`fi-signal-indicator ${nplan.health_signal || 'green'}`}
            title={`${SIGNAL_LABELS[nplan.health_signal] || 'On Track'}: ${nplan.signal_reason || ''}`}
          />
        </div>
        <div className="fi-col-key">
          <a href={nplan.url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>
            {nplan.key}
          </a>
        </div>
        <div className="fi-col-summary" title={nplan.summary}>{nplan.summary}</div>
        <div className="fi-col-assignee">{nplan.assignee || '—'}</div>
        <div className="fi-col-eng">
          <span className="fi-eng-count">{nplan.eng_tickets.total}</span>
        </div>
        <div className="fi-col-blocked">
          {nplan.eng_tickets.blocked > 0 ? (
            <span className="fi-blocked-badge">{nplan.eng_tickets.blocked}</span>
          ) : (
            <span className="fi-ok-badge">0</span>
          )}
        </div>
        <div className="fi-col-target">{nplan.delivery_target_beta || '—'}</div>
      </div>

      {expanded && (
        <div className="fi-nplan-detail">
          <div className="fi-tabs">
            <button
              className={`fi-tab ${(activeTab || 'eng') === 'eng' ? 'active' : ''}`}
              onClick={() => onTabChange('eng')}
            >
              ENG Tickets ({nplan.eng_tickets.total})
            </button>
            <button
              className={`fi-tab ${activeTab === 'non_eng' ? 'active' : ''}`}
              onClick={() => onTabChange('non_eng')}
            >
              Non-ENG ({nplan.non_eng_tickets.total})
            </button>
            <button
              className={`fi-tab ${activeTab === 'related' ? 'active' : ''}`}
              onClick={() => onTabChange('related')}
            >
              Related NPLANs ({nplan.related_nplans.total})
            </button>
          </div>

          {/* ENG Tickets Tab */}
          {(activeTab || 'eng') === 'eng' && (
            <div className="fi-ticket-panel">
              {nplan.eng_tickets.items.length === 0 ? (
                <div className="fi-empty">No ENG tickets linked</div>
              ) : (
                <>
                  <div className="fi-mini-summary">
                    <span className="fi-mini-done">{nplan.eng_tickets.done} done</span>
                    <span className="fi-mini-ip">{nplan.eng_tickets.in_progress} in progress</span>
                    <span className="fi-mini-todo">{nplan.eng_tickets.todo} todo</span>
                    {nplan.eng_tickets.blocked > 0 && (
                      <span className="fi-mini-blocked">{nplan.eng_tickets.blocked} blocked</span>
                    )}
                  </div>
                  <div className="fi-ticket-table">
                    <div className="fi-ticket-header">
                      <div className="fi-tcol-key">Key</div>
                      <div className="fi-tcol-summary">Summary</div>
                      <div className="fi-tcol-status">Status</div>
                      <div className="fi-tcol-priority">Priority</div>
                      <div className="fi-tcol-assignee">Assignee</div>
                    </div>
                    {nplan.eng_tickets.items.map(ticket => (
                      <div key={ticket.key} className={`fi-ticket-row ${ticket.is_blocked ? 'blocked' : ''}`}>
                        <div className="fi-tcol-key">
                          <a href={ticket.url} target="_blank" rel="noopener noreferrer">{ticket.key}</a>
                        </div>
                        <div className="fi-tcol-summary" title={ticket.summary}>{ticket.summary}</div>
                        <div className="fi-tcol-status">
                          <span className={`fi-status-badge ${ticket.status_category}`}>{ticket.status}</span>
                        </div>
                        <div className="fi-tcol-priority">{ticket.priority}</div>
                        <div className="fi-tcol-assignee">{ticket.assignee || '—'}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* Non-ENG Tab */}
          {activeTab === 'non_eng' && (
            <div className="fi-ticket-panel">
              {nplan.non_eng_tickets.items.length === 0 ? (
                <div className="fi-empty">No non-ENG tickets linked</div>
              ) : (
                <div className="fi-ticket-table">
                  <div className="fi-ticket-header non-eng">
                    <div className="fi-tcol-key">Key</div>
                    <div className="fi-tcol-summary">Summary</div>
                    <div className="fi-tcol-status">Status</div>
                    <div className="fi-tcol-project">Project</div>
                    <div className="fi-tcol-link">Link Type</div>
                  </div>
                  {nplan.non_eng_tickets.items.map(ticket => (
                    <div key={ticket.key} className="fi-ticket-row">
                      <div className="fi-tcol-key">
                        <a href={ticket.url} target="_blank" rel="noopener noreferrer">{ticket.key}</a>
                      </div>
                      <div className="fi-tcol-summary" title={ticket.summary}>{ticket.summary}</div>
                      <div className="fi-tcol-status">{ticket.status}</div>
                      <div className="fi-tcol-project"><span className="fi-project-badge">{ticket.project}</span></div>
                      <div className="fi-tcol-link">{ticket.direction || ticket.link_type}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Related NPLANs Tab */}
          {activeTab === 'related' && (
            <div className="fi-ticket-panel">
              {nplan.related_nplans.items.length === 0 ? (
                <div className="fi-empty">No related NPLANs</div>
              ) : (
                <div className="fi-ticket-table">
                  <div className="fi-ticket-header related">
                    <div className="fi-tcol-key">Key</div>
                    <div className="fi-tcol-summary">Summary</div>
                    <div className="fi-tcol-status">Status</div>
                    <div className="fi-tcol-link">Relationship</div>
                  </div>
                  {nplan.related_nplans.items.map(rn => (
                    <div key={rn.key} className="fi-ticket-row">
                      <div className="fi-tcol-key">
                        <a href={rn.url} target="_blank" rel="noopener noreferrer">
                          <Link2 size={12} /> {rn.key}
                        </a>
                      </div>
                      <div className="fi-tcol-summary" title={rn.summary}>{rn.summary}</div>
                      <div className="fi-tcol-status">{rn.status}</div>
                      <div className="fi-tcol-link">{rn.direction || rn.link_type}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
let _cachedData = null;

function FeatureInsightsSection() {
  const [data, setData] = useState(_cachedData);
  const [loading, setLoading] = useState(!_cachedData);
  const [error, setError] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({
    under_review: true,
    design_in_progress: true,
    implementation_in_progress: true,
    beta: true,
    other: false,
  });
  const [expandedNplans, setExpandedNplans] = useState({});
  const [activeTabs, setActiveTabs] = useState({});
  const [activeView, setActiveView] = useState('phase');

  const fetchData = useCallback(async (refresh = false) => {
    if (!refresh && _cachedData) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.getFeatureInsights(refresh);
      _cachedData = result;
      setData(result);
    } catch (err) {
      setError(err.message || 'Failed to load Feature Insights');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const toggleGroup = (groupKey) => {
    setExpandedGroups(prev => ({ ...prev, [groupKey]: !prev[groupKey] }));
  };

  const toggleNplan = (nplanKey) => {
    setExpandedNplans(prev => ({ ...prev, [nplanKey]: !prev[nplanKey] }));
    if (!activeTabs[nplanKey]) {
      setActiveTabs(prev => ({ ...prev, [nplanKey]: 'eng' }));
    }
  };

  const setTab = (nplanKey, tab) => {
    setActiveTabs(prev => ({ ...prev, [nplanKey]: tab }));
  };

  const handleNplanClick = (nplanKey) => {
    setExpandedNplans(prev => ({ ...prev, [nplanKey]: true }));
    if (!activeTabs[nplanKey]) {
      setActiveTabs(prev => ({ ...prev, [nplanKey]: 'eng' }));
    }
    setTimeout(() => {
      const el = document.getElementById(`fi-nplan-${nplanKey}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 100);
  };

  if (loading && !data) {
    return (
      <div className="fi-dashboard">
        <div className="fi-loading">
          <Loader className="fi-spinner" size={28} />
          <span>Loading Feature Insights...</span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="fi-dashboard">
        <div className="fi-error">
          <AlertTriangle size={20} />
          <span>{error}</span>
          <button onClick={() => fetchData(true)}>Retry</button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { status_groups, summary, sunburst_data, quarter_view, health_signals, jira_url, total_nplans } = data;
  const groupEntries = Object.entries(status_groups || {});

  return (
    <div className="fi-dashboard">
      {/* Header */}
      <div className="fi-header">
        <div className="fi-header-left">
          <Lightbulb size={22} className="fi-header-icon" />
          <h2>Feature Insights</h2>
          <span className="fi-total-badge">{total_nplans} NPLANs</span>
        </div>
        <div className="fi-header-actions">
          {/* View toggle */}
          <div className="fi-view-toggle">
            <button
              className={`fi-view-btn ${activeView === 'phase' ? 'active' : ''}`}
              onClick={() => setActiveView('phase')}
            >
              By Phase
            </button>
            <button
              className={`fi-view-btn ${activeView === 'quarter' ? 'active' : ''}`}
              onClick={() => setActiveView('quarter')}
            >
              By Quarter
            </button>
          </div>
          <button className="fi-refresh-btn" onClick={() => fetchData(true)} disabled={loading} title="Refresh">
            <RefreshCw size={16} className={loading ? 'fi-spin' : ''} />
          </button>
          {jira_url && (
            <a href={jira_url} target="_blank" rel="noopener noreferrer" className="fi-jira-link">
              <ExternalLink size={14} /> Open in JIRA
            </a>
          )}
        </div>
      </div>

      {/* Health Signals Bar */}
      {health_signals && (
        <SignalBar counts={health_signals.counts} total={total_nplans} />
      )}

      {/* Phase View */}
      {activeView === 'phase' && (
        <>
          <div className="fi-overview">
            <div className="fi-cards">
              {groupEntries.map(([key, group]) => (
                <div
                  key={key}
                  className={`fi-card ${expandedGroups[key] ? 'active' : ''}`}
                  style={{ borderTopColor: group.color }}
                  onClick={() => toggleGroup(key)}
                >
                  <div className="fi-card-icon">{PHASE_ICONS[key] || '📋'}</div>
                  <div className="fi-card-count">{group.count}</div>
                  <div className="fi-card-label">{group.label}</div>
                </div>
              ))}
              {summary.total_blocked_eng > 0 && (
                <div className="fi-card fi-card-blocked" style={{ borderTopColor: '#ef4444' }}>
                  <div className="fi-card-icon"><AlertTriangle size={18} /></div>
                  <div className="fi-card-count">{summary.total_blocked_eng}</div>
                  <div className="fi-card-label">Blocked ENG</div>
                </div>
              )}
            </div>

            {sunburst_data && sunburst_data.categories && sunburst_data.categories.length > 0 && (
              <div className="fi-chart-container">
                <FeatureSunburst data={sunburst_data} onNplanClick={handleNplanClick} />
                <div className="fi-chart-legend">
                  {sunburst_data.categories.map(cat => (
                    <div key={cat.key} className="fi-legend-item">
                      <span className="fi-legend-dot" style={{ background: cat.color }} />
                      <span>{cat.name} ({cat.count})</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Status Phase Groups */}
          <div className="fi-groups">
            {groupEntries.map(([key, group]) => (
              <div key={key} className="fi-group">
                <div
                  className="fi-group-header"
                  style={{ borderLeftColor: group.color }}
                  onClick={() => toggleGroup(key)}
                >
                  <span className="fi-group-chevron">
                    {expandedGroups[key] ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                  </span>
                  <span className="fi-group-icon">{PHASE_ICONS[key] || '📋'}</span>
                  <span className="fi-group-title">{group.label}</span>
                  <span className="fi-group-count">{group.count}</span>
                </div>

                {expandedGroups[key] && group.nplans && group.nplans.length > 0 && (
                  <div className="fi-nplan-list">
                    <div className="fi-nplan-table-header">
                      <div className="fi-col-expand" />
                      <div className="fi-col-signal" />
                      <div className="fi-col-key">NPLAN</div>
                      <div className="fi-col-summary">Summary</div>
                      <div className="fi-col-assignee">Assignee</div>
                      <div className="fi-col-eng">ENG</div>
                      <div className="fi-col-blocked">Blocked</div>
                      <div className="fi-col-target">Target</div>
                    </div>

                    {group.nplans.map(nplan => (
                      <NplanRow
                        key={nplan.key}
                        nplan={nplan}
                        expanded={!!expandedNplans[nplan.key]}
                        onToggle={() => toggleNplan(nplan.key)}
                        onTabChange={(tab) => setTab(nplan.key, tab)}
                        activeTab={activeTabs[nplan.key]}
                      />
                    ))}
                  </div>
                )}

                {expandedGroups[key] && (!group.nplans || group.nplans.length === 0) && (
                  <div className="fi-empty-group">No NPLANs in this phase</div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Quarter View */}
      {activeView === 'quarter' && (
        <QuarterView quarterView={quarter_view} onNplanClick={handleNplanClick} />
      )}
    </div>
  );
}

export default FeatureInsightsSection;
