import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Phone,
  Users,
  RefreshCw,
  AlertCircle,
  AlertTriangle,
  Loader2,
  ChevronLeft,
  ChevronRight,
  ArrowRight,
  Clock,
  Briefcase,
  Code,
  Server
} from 'lucide-react';
import api from '../../services/api';
import './OnCallCalendarSection.css';

const REGION_STYLES = {
  IST: { 
    color: '#f97316', 
    bg: 'rgba(249,115,22,0.12)', 
    gradient: 'linear-gradient(135deg,#f97316,#ea580c)', 
    flag: '🇮🇳', 
    label: 'India (IST)',
    coverageIST: '12:30 PM – 8:30 PM IST',
    coverageLocal: '12:30 PM – 8:30 PM',
    localTz: 'IST',
  },
  TW: { 
    color: '#06b6d4', 
    bg: 'rgba(6,182,212,0.12)',  
    gradient: 'linear-gradient(135deg,#06b6d4,#0891b2)', 
    flag: '🇹🇼', 
    label: 'Taiwan (CST)',
    coverageIST: '4:30 AM – 12:30 PM IST',
    coverageLocal: '7:00 AM – 3:00 PM',
    localTz: 'CST',
  },
  US: { 
    color: '#6366f1', 
    bg: 'rgba(99,102,241,0.12)', 
    gradient: 'linear-gradient(135deg,#6366f1,#4f46e5)', 
    flag: '🇺🇸', 
    label: 'US (Pacific)',
    coverageIST: '8:30 PM – 4:30 AM IST',
    coverageLocal: '8:00 AM – 4:00 PM',
    localTz: 'PST/PDT',
  },
  ALL: { 
    color: '#10b981', 
    bg: 'rgba(16,185,129,0.12)', 
    gradient: 'linear-gradient(135deg,#10b981,#059669)', 
    flag: '🌐', 
    label: 'All Regions',
    coverageIST: 'Full Week',
    coverageLocal: 'Full Week',
    localTz: '',
  },
  BACKEND: { 
    color: '#ec4899', 
    bg: 'rgba(236,72,153,0.12)', 
    gradient: 'linear-gradient(135deg,#ec4899,#db2777)', 
    flag: '🔧', 
    label: 'Backend',
    coverageIST: 'Full Week',
    coverageLocal: 'Full Week',
    localTz: '',
  },
};

const DAY_NAMES_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const isSameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

const getMonday = (d) => {
  const dt = new Date(d);
  const day = dt.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  dt.setDate(dt.getDate() + diff);
  dt.setHours(0, 0, 0, 0);
  return dt;
};

// Rotation start day per region (0=Sunday, 1=Monday, 2=Tuesday, etc.)
// Based on OpsGenie schedule configuration
const REGION_ROTATION_START_DAY = {
  IST: 2,  // Tuesday
  TW: 1,   // Monday
  US: 1,   // Monday
  ALL: 1,  // Monday (default for manager schedules)
  BACKEND: 1, // Monday
};

const getRotationWeekStart = (d, regionId) => {
  const dt = new Date(d);
  const currentDay = dt.getDay(); // 0=Sunday, 1=Monday, ..., 6=Saturday
  const startDay = REGION_ROTATION_START_DAY[regionId] || 1; // Default to Monday
  
  // Calculate days since the rotation start day
  // For Tuesday (2): if today is Tuesday(2), diff=0; if Monday(1), diff=6; if Wednesday(3), diff=1
  let diff = currentDay - startDay;
  if (diff < 0) diff += 7;
  
  dt.setDate(dt.getDate() - diff);
  dt.setHours(0, 0, 0, 0);
  return dt;
};

const addDays = (d, n) => {
  const dt = new Date(d);
  dt.setDate(dt.getDate() + n);
  return dt;
};

const formatShortDate = (d) => `${d.getDate()} ${MONTH_NAMES[d.getMonth()].slice(0, 3)}`;

const formatLocalDate = (d) => {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const OnCallCalendarSection = ({ onRefresh, isRefreshing }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [allSchedulesData, setAllSchedulesData] = useState(null);
  const [activeSchedule, setActiveSchedule] = useState('primary');
  const [viewMode, setViewMode] = useState('week');
  const [currentDate, setCurrentDate] = useState(() => getMonday(new Date()));
  const [showCoverageGaps, setShowCoverageGaps] = useState(false);

  const fetchAllSchedules = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAllOnCallSchedules();
      if (data.source === 'error') {
        setError(data.error || 'Failed to load on-call schedules');
        setAllSchedulesData(null);
      } else {
        setAllSchedulesData(data);
      }
    } catch (err) {
      console.error('Error fetching on-call schedules:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAllSchedules(); }, []);

  const handleRefresh = async () => {
    api.clearCache();
    await fetchAllSchedules();
    if (onRefresh) onRefresh();
  };

  const scheduleData = useMemo(() => {
    if (!allSchedulesData?.schedules) return null;
    return allSchedulesData.schedules[activeSchedule] || null;
  }, [allSchedulesData, activeSchedule]);

  const scheduleMetadata = useMemo(() => {
    return allSchedulesData?.schedule_metadata || {};
  }, [allSchedulesData]);

  const getHolidaysForDate = useCallback((dateStr) => {
    const allHolidays = allSchedulesData?.holidays || {};
    const dayHolidays = [];
    for (const [regionId, holidays] of Object.entries(allHolidays)) {
      for (const h of holidays) {
        if (h.date === dateStr) {
          dayHolidays.push({ ...h, region: regionId });
        }
      }
    }
    return dayHolidays;
  }, [allSchedulesData]);

  const navigatePrev = useCallback(() => {
    setCurrentDate(prev => addDays(prev, viewMode === 'week' ? -7 : -28));
  }, [viewMode]);

  const navigateNext = useCallback(() => {
    setCurrentDate(prev => addDays(prev, viewMode === 'week' ? 7 : 28));
  }, [viewMode]);

  const goToToday = useCallback(() => {
    setCurrentDate(getMonday(new Date()));
  }, []);

  const regionIds = useMemo(() => (scheduleData?.regions || []).map(r => r.id), [scheduleData]);

  const rotationsByWeekStart = useMemo(() => {
    const map = {};
    (scheduleData?.rotations || []).forEach(r => { map[r.week_start] = r; });
    return map;
  }, [scheduleData]);

  const visibleDays = useMemo(() => {
    const count = viewMode === 'week' ? 7 : 35;
    const days = [];
    for (let i = 0; i < count; i++) {
      days.push(addDays(currentDate, i));
    }
    return days;
  }, [currentDate, viewMode]);

  const allEngineers = useMemo(() => {
    const members = scheduleData?.team_members || {};
    const list = [];
    regionIds.forEach(rid => {
      (members[rid] || []).forEach(person => {
        list.push({ ...person, region: rid });
      });
    });
    return list;
  }, [scheduleData, regionIds]);

  const engineersByRegion = useMemo(() => {
    const grouped = {};
    regionIds.forEach(rid => { grouped[rid] = []; });
    allEngineers.forEach(eng => {
      if (grouped[eng.region]) grouped[eng.region].push(eng);
    });
    return grouped;
  }, [allEngineers, regionIds]);

  const getOnCallForWeek = useCallback((weekStart, regionId) => {
    const key = formatLocalDate(weekStart);
    const rotation = rotationsByWeekStart[key];
    return rotation?.regions?.[regionId] || null;
  }, [rotationsByWeekStart]);

  const headerDateRange = useMemo(() => {
    if (viewMode === 'week') {
      const end = addDays(currentDate, 6);
      return `${formatShortDate(currentDate)} – ${formatShortDate(end)}, ${currentDate.getFullYear()}`;
    }
    const end = addDays(currentDate, 34);
    if (currentDate.getMonth() === end.getMonth()) {
      return `${MONTH_NAMES[currentDate.getMonth()]} ${currentDate.getFullYear()}`;
    }
    return `${MONTH_NAMES[currentDate.getMonth()].slice(0, 3)} – ${MONTH_NAMES[end.getMonth()].slice(0, 3)} ${end.getFullYear()}`;
  }, [currentDate, viewMode]);

  const currentRotation = scheduleData?.current_rotation;
  const nextRotation = scheduleData?.next_rotation;

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const isOpsGenieLive = allSchedulesData?.source === 'opsgenie' || 
    (allSchedulesData?.schedules?.primary?.source === 'opsgenie');

  if (loading) {
    return (
      <div className="oncall-calendar-section">
        <div className="loading-container">
          <Loader2 size={48} className="spin" />
          <p>Loading on-call schedules...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="oncall-calendar-section">
        <div className="error-container">
          <AlertCircle size={48} />
          <h3>Error Loading On-Call Schedules</h3>
          <p>{error}</p>
          <button onClick={handleRefresh} className="oncall-action-btn primary">
            <RefreshCw size={16} /> Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="oncall-calendar-section">
      {/* ── Top Header: Title & Actions ── */}
      <div className="oncall-top-strip">
        <div className="oncall-top-left">
          <Phone size={22} />
          <h1>On-Call Calendar</h1>
          {isOpsGenieLive ? (
            <span className="data-source-badge opsgenie">OpsGenie Live</span>
          ) : (
            <span className="data-source-badge sample">Sample Data</span>
          )}
        </div>
        <div className="oncall-top-right">
          <button
            className={`oncall-action-btn secondary ${isRefreshing ? 'syncing' : ''}`}
            onClick={handleRefresh}
            disabled={isRefreshing || loading}
          >
            <RefreshCw size={14} className={isRefreshing ? 'spin' : ''} />
            {isRefreshing ? 'Syncing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Tech Preview Banner - only show when using sample data */}
      {!isOpsGenieLive && (
        <div className="tech-preview-banner">
          <AlertTriangle size={20} />
          <span>
            <strong>Tech Preview</strong>
            <span className="separator">|</span>
            OpsGenie integration pending API key configuration. Showing sample data.
          </span>
        </div>
      )}

      {/* ── Schedule Tabs ── */}
      <div className="schedule-tabs">
        <button
          className={`schedule-tab ${activeSchedule === 'primary' ? 'active' : ''}`}
          onClick={() => setActiveSchedule('primary')}
          style={{ '--tab-color': '#6366f1' }}
        >
          <Code size={18} />
          <div className="tab-content">
            <span className="tab-title">NSC Client Endpoint On-Call</span>
            <span className="tab-subtitle">NSC-Escalation-Oncall-Primary</span>
          </div>
          {allSchedulesData?.schedules?.primary?.current_rotation && (
            <span className="tab-badge">
              {Object.keys(allSchedulesData.schedules.primary.current_rotation.regions || {}).length} regions
            </span>
          )}
        </button>
        <button
          className={`schedule-tab ${activeSchedule === 'managers' ? 'active' : ''}`}
          onClick={() => setActiveSchedule('managers')}
          style={{ '--tab-color': '#10b981' }}
        >
          <Briefcase size={18} />
          <div className="tab-content">
            <span className="tab-title">Manager On-Call</span>
            <span className="tab-subtitle">NSC-Mangers</span>
          </div>
        </button>
        {allSchedulesData?.schedules?.backend && (
          <button
            className={`schedule-tab ${activeSchedule === 'backend' ? 'active' : ''}`}
            onClick={() => setActiveSchedule('backend')}
            style={{ '--tab-color': '#ec4899' }}
          >
            <Server size={18} />
            <div className="tab-content">
              <span className="tab-title">NSC Client Backend On-Call</span>
              <span className="tab-subtitle">{allSchedulesData.schedules.backend.schedule_name || 'Backend Schedule'}</span>
            </div>
          </button>
        )}
      </div>

      {/* ── Current On-Call Row ── */}
      <div className="oncall-section">
        <div className="oncall-section-header">
          <span className="live-dot"></span>
          <span>Current On-Call</span>
        </div>
        <div className="oncall-summary-row">
          {/* Engineer - Current */}
          {allSchedulesData?.schedules?.primary?.current_rotation && (
            <div className="summary-card primary">
              <div className="summary-card-header">
                <Code size={16} />
                <span>Engineer On-Call</span>
              </div>
              <div className="summary-card-people">
                {Object.entries(allSchedulesData.schedules.primary.current_rotation.regions || {}).map(([rid, person]) => {
                  const style = REGION_STYLES[rid];
                  if (!person || !style) return null;
                  return (
                    <div key={rid} className="summary-person">
                      <span className="person-flag">{style.flag}</span>
                      <div className="person-info">
                        <span className="person-name">{person.name}</span>
                        {style.coverageLocal && style.localTz && (
                          <span className="person-coverage">{style.coverageLocal} {style.localTz}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Manager - Current */}
          {allSchedulesData?.schedules?.managers?.current_rotation && (
            <div className="summary-card managers">
              <div className="summary-card-header">
                <Briefcase size={16} />
                <span>Manager On-Call</span>
              </div>
              <div className="summary-card-people">
                {Object.entries(allSchedulesData.schedules.managers.current_rotation.regions || {}).map(([rid, person]) => {
                  const style = REGION_STYLES[rid] || REGION_STYLES.ALL;
                  if (!person) return null;
                  return (
                    <div key={rid} className="summary-person">
                      <span className="person-flag">{style.flag}</span>
                      <div className="person-info">
                        <span className="person-name">{person.name}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Backend - Current */}
          {allSchedulesData?.schedules?.backend?.current_rotation && (
            <div className="summary-card backend">
              <div className="summary-card-header">
                <Server size={16} />
                <span>Backend Services</span>
              </div>
              <div className="summary-card-people">
                {Object.entries(allSchedulesData.schedules.backend.current_rotation.regions || {}).map(([rid, person]) => {
                  const style = REGION_STYLES[rid] || REGION_STYLES.BACKEND;
                  if (!person) return null;
                  return (
                    <div key={rid} className="summary-person">
                      <span className="person-flag">{style.flag}</span>
                      <div className="person-info">
                        <span className="person-name">{person.name}</span>
                        {style.coverageLocal && style.localTz && (
                          <span className="person-coverage">{style.coverageLocal} {style.localTz}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Next Week On-Call Row ── */}
      <div className="oncall-section next-week-section">
        <div className="oncall-section-header">
          <ArrowRight size={14} />
          <span>Next Week</span>
        </div>
        <div className="oncall-summary-row">
          {/* Engineer - Next Week */}
          {allSchedulesData?.schedules?.primary?.next_rotation && (
            <div className="summary-card primary">
              <div className="summary-card-header">
                <Code size={16} />
                <span>Engineer On-Call</span>
              </div>
              <div className="summary-card-people">
                {Object.entries(allSchedulesData.schedules.primary.next_rotation.regions || {}).map(([rid, person]) => {
                  const style = REGION_STYLES[rid];
                  if (!person || !style) return null;
                  return (
                    <div key={rid} className="summary-person">
                      <span className="person-flag">{style.flag}</span>
                      <div className="person-info">
                        <span className="person-name">{person.name}</span>
                        {style.coverageLocal && style.localTz && (
                          <span className="person-coverage">{style.coverageLocal} {style.localTz}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Manager - Next Week */}
          {allSchedulesData?.schedules?.managers?.next_rotation && (
            <div className="summary-card managers">
              <div className="summary-card-header">
                <Briefcase size={16} />
                <span>Manager On-Call</span>
              </div>
              <div className="summary-card-people">
                {Object.entries(allSchedulesData.schedules.managers.next_rotation.regions || {}).map(([rid, person]) => {
                  const style = REGION_STYLES[rid] || REGION_STYLES.ALL;
                  if (!person) return null;
                  return (
                    <div key={rid} className="summary-person">
                      <span className="person-flag">{style.flag}</span>
                      <div className="person-info">
                        <span className="person-name">{person.name}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Backend - Next Week */}
          {allSchedulesData?.schedules?.backend?.next_rotation && (
            <div className="summary-card backend">
              <div className="summary-card-header">
                <Server size={16} />
                <span>Backend Services</span>
              </div>
              <div className="summary-card-people">
                {Object.entries(allSchedulesData.schedules.backend.next_rotation.regions || {}).map(([rid, person]) => {
                  const style = REGION_STYLES[rid] || REGION_STYLES.BACKEND;
                  if (!person) return null;
                  return (
                    <div key={rid} className="summary-person">
                      <span className="person-flag">{style.flag}</span>
                      <div className="person-info">
                        <span className="person-name">{person.name}</span>
                        {style.coverageLocal && style.localTz && (
                          <span className="person-coverage">{style.coverageLocal} {style.localTz}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>


      {/* ── Coverage Timeline Panel (only for primary schedule) ── */}
      {activeSchedule === 'primary' && allSchedulesData?.regions && (
        <div className="coverage-gaps-panel">
          <button 
            className={`coverage-gaps-toggle ${showCoverageGaps ? 'active' : ''}`}
            onClick={() => setShowCoverageGaps(!showCoverageGaps)}
          >
            <Clock size={16} />
            <span>Coverage Timeline (IST)</span>
            {allSchedulesData?.coverage_gaps?.length > 0 ? (
              <span className="gap-badge warning">
                {allSchedulesData.coverage_gaps.length} gap{allSchedulesData.coverage_gaps.length > 1 ? 's' : ''}
              </span>
            ) : (
              <span className="gap-badge success">24h Coverage</span>
            )}
          </button>
          
          {showCoverageGaps && (
            <div className="coverage-timeline">
              <div className="timeline-visual">
                <div className="timeline-hours">
                  {[0, 6, 12, 18, 24].map(h => (
                    <span key={h} className="hour-mark">{h.toString().padStart(2, '0')}:00</span>
                  ))}
                </div>
                <div className="timeline-bar">
                  {['IST', 'TW', 'US'].map(rid => {
                    const region = (allSchedulesData?.regions || []).find(r => r.id === rid);
                    if (!region) return null;
                    const start = region.coverage_utc_start || 0;
                    let end = region.coverage_utc_end || 0;
                    
                    if (start > end) {
                      return (
                        <React.Fragment key={rid}>
                          <div 
                            className="timeline-region-bar"
                            style={{
                              left: `${(start / 24) * 100}%`,
                              width: `${((24 - start) / 24) * 100}%`,
                              background: REGION_STYLES[rid]?.gradient,
                            }}
                            title={`${REGION_STYLES[rid]?.label}: ${region.coverage}`}
                          >
                            <span className="region-bar-label">{REGION_STYLES[rid]?.flag} {rid}</span>
                          </div>
                          <div 
                            className="timeline-region-bar"
                            style={{
                              left: '0%',
                              width: `${(end / 24) * 100}%`,
                              background: REGION_STYLES[rid]?.gradient,
                              opacity: 0.8,
                            }}
                            title={`${REGION_STYLES[rid]?.label}: ${region.coverage} (continued)`}
                          />
                        </React.Fragment>
                      );
                    }
                    
                    if (end > 24) end = 24;
                    const left = (start / 24) * 100;
                    const width = ((end - start) / 24) * 100;
                    return (
                      <div 
                        key={rid}
                        className="timeline-region-bar"
                        style={{
                          left: `${left}%`,
                          width: `${width}%`,
                          background: REGION_STYLES[rid]?.gradient,
                        }}
                        title={`${REGION_STYLES[rid]?.label}: ${region.coverage}`}
                      >
                        <span className="region-bar-label">{REGION_STYLES[rid]?.flag} {rid}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="gaps-list">
                {allSchedulesData?.coverage_gaps?.length > 0 ? (
                  <>
                    <span className="gaps-label">⚠️ Coverage Gaps (UTC):</span>
                    {allSchedulesData.coverage_gaps.map((gap, idx) => (
                      <span key={idx} className="gap-item">
                        {gap.description} ({gap.gap_hours}h between {gap.from_region} → {gap.to_region})
                      </span>
                    ))}
                  </>
                ) : (
                  <span className="gaps-label success">✅ Full 24-hour coverage — seamless handoffs between regions</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Navigation Bar ── */}
      <div className="oncall-nav-bar">
        <div className="nav-bar-left">
          <button className="nav-arrow" onClick={navigatePrev}><ChevronLeft size={18} /></button>
          <button className="nav-arrow" onClick={navigateNext}><ChevronRight size={18} /></button>
          <button className="nav-today-btn" onClick={goToToday}>Today</button>
          <h2 className="nav-date-range">{headerDateRange}</h2>
        </div>
        <div className="nav-bar-right">
          <div className="view-toggle">
            <button className={viewMode === 'week' ? 'active' : ''} onClick={() => setViewMode('week')}>Week</button>
            <button className={viewMode === 'month' ? 'active' : ''} onClick={() => setViewMode('month')}>Month</button>
          </div>
        </div>
      </div>

      {/* ── Scheduler Grid ── */}
      <div className={`oncall-scheduler ${viewMode}`}>
        {/* Day column headers */}
        <div className="scheduler-header">
          <div className="scheduler-label-col">
            <span className="label-col-title"><Users size={14} /> {activeSchedule === 'managers' ? 'Managers' : 'Engineers'}</span>
          </div>
          {visibleDays.map((day, i) => {
            const isToday = isSameDay(day, today);
            const isWeekend = day.getDay() === 0 || day.getDay() === 6;
            const dateStr = formatLocalDate(day);
            const dayHolidays = getHolidaysForDate(dateStr);
            const hasHoliday = dayHolidays.length > 0;
            return (
              <div 
                key={i} 
                className={`scheduler-day-header ${isToday ? 'today' : ''} ${isWeekend ? 'weekend' : ''} ${hasHoliday ? 'has-holiday' : ''}`}
                title={hasHoliday ? dayHolidays.map(h => `${REGION_STYLES[h.region]?.flag || '🌐'} ${h.name}`).join('\n') : undefined}
              >
                <span className="day-name">{DAY_NAMES_SHORT[((day.getDay() + 6) % 7)]}</span>
                <span className={`day-number ${isToday ? 'today-number' : ''}`}>{day.getDate()}</span>
                {hasHoliday && (
                  <span className="holiday-indicator" title={dayHolidays.map(h => `${REGION_STYLES[h.region]?.flag || '🌐'} ${h.name}`).join(', ')}>
                    🎉
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Body: region groups → engineer rows */}
        <div className="scheduler-body">
          {regionIds.map(rid => {
            const style = REGION_STYLES[rid] || REGION_STYLES.ALL;
            const engineers = engineersByRegion[rid] || [];
            return (
              <div key={rid} className="scheduler-region-group">
                {/* Region header row */}
                <div className="scheduler-region-header" style={{ '--region-accent': style.color }}>
                  <div className="scheduler-label-col region-label">
                    <span className="region-flag">{style.flag}</span>
                    <span className="region-name">{style.label}</span>
                    <span className="region-count">{engineers.length}</span>
                  </div>
                  {visibleDays.map((day, i) => {
                    const isWeekend = day.getDay() === 0 || day.getDay() === 6;
                    return <div key={i} className={`scheduler-cell region-header-cell ${isWeekend ? 'weekend' : ''}`} />;
                  })}
                </div>

                {/* Engineer rows */}
                {engineers.map((eng) => (
                  <div key={eng.email || eng.name} className="scheduler-row">
                    <div className="scheduler-label-col engineer-label">
                      <div className="eng-avatar" style={{ background: style.gradient }}>
                        {eng.name.split(' ').map(n => n[0]).join('')}
                      </div>
                      <div className="eng-info">
                        <span className="eng-name">{eng.name}</span>
                        {eng.slack && <span className="eng-slack">{eng.slack}</span>}
                      </div>
                    </div>

                    {/* Day cells with shift bars */}
                    {visibleDays.map((day, dayIdx) => {
                      // Use region-specific rotation week start (IST=Tuesday, US/TW=Monday)
                      const weekStart = getRotationWeekStart(day, rid);
                      const onCallPerson = getOnCallForWeek(weekStart, rid);
                      const isOnCall = onCallPerson && onCallPerson.name === eng.name;
                      const isWeekend = day.getDay() === 0 || day.getDay() === 6;
                      const isDayToday = isSameDay(day, today);
                      const rotationStartDay = REGION_ROTATION_START_DAY[rid] || 1;
                      const isRotationStart = day.getDay() === rotationStartDay;

                      return (
                        <div
                          key={dayIdx}
                          className={`scheduler-cell ${isWeekend ? 'weekend' : ''} ${isDayToday ? 'today-col' : ''}`}
                        >
                          {isOnCall && !isWeekend && (
                            <div
                              className={`shift-bar ${isRotationStart ? 'first-day' : ''} ${day.getDay() === 5 ? 'last-day' : ''}`}
                              style={{
                                '--bar-color': style.color,
                                '--bar-bg': style.bg,
                                '--bar-gradient': style.gradient,
                              }}
                              title={`${eng.name} — ${onCallPerson.coverage || 'On-Call'}`}
                            >
                              <span className="shift-time">
                                {onCallPerson.coverage?.replace(/ IST$/, '') || (activeSchedule === 'managers' ? 'On-Call' : '12:30PM–8:30PM')}
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Legend with Timezone Info ── */}
      <div className="oncall-legend">
        <span className="legend-title">Coverage Hours:</span>
        <div className="legend-items timezone-grid">
          {regionIds.map(rid => {
            const s = REGION_STYLES[rid] || REGION_STYLES.ALL;
            const region = (scheduleData?.regions || []).find(r => r.id === rid);
            const coverageLocal = region?.coverage_local || s.coverageLocal;
            const localTz = region?.coverage_local_tz || s.localTz;
            const coverageIST = region?.coverage || s.coverageIST;
            return (
              <div key={rid} className="legend-item timezone-item" title={`OpsGenie: ${coverageLocal} ${localTz}`}>
                <span className="legend-swatch" style={{ background: s.gradient }}></span>
                <div className="timezone-info">
                  <span className="tz-region">{s.flag} {s.label}</span>
                  <span className="tz-local">{coverageLocal} <span className="tz-label">{localTz}</span></span>
                  <span className="tz-ist">{coverageIST}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      
      {/* ── Simple Legend ── */}
      <div className="oncall-legend simple-legend">
        <span className="legend-title">Legend:</span>
        <div className="legend-items">
          <div className="legend-item">
            <span className="legend-swatch today-swatch"></span>
            <span>Today</span>
          </div>
          {activeSchedule === 'primary' && (
            <div className="legend-item">
              <span className="legend-emoji">🎉</span>
              <span>Holiday</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default OnCallCalendarSection;
