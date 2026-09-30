import React, { useState, useEffect, useMemo } from 'react';
import {
  Calendar,
  Package,
  Layers,
  Clock,
  CalendarDays,
  CalendarCheck,
  Timer,
  Tag,
  Activity,
  CheckCircle2,
  PlayCircle,
  Target,
  RefreshCw,
  Search,
  Download,
  Filter,
  Rocket,
  GitBranch,
  Hammer,
  Shield,
  Server,
  AlertCircle,
  Loader2,
  ExternalLink,
  Star
} from 'lucide-react';
import api from '../../services/api';
import './ReleaseCalendarSection.css';

// Milestone icon mapping
const MILESTONE_ICONS = {
  "IRR": <Calendar size={16} />,
  "Branch Cut - EP": <GitBranch size={16} />,
  "Final Build - EP": <Hammer size={16} />,
  "Signoff STG/FedAlpha - ENG": <Shield size={16} />,
  "Deploy MP Pre PROD": <Server size={16} />,
  "Deploy Prod Day 1": <Rocket size={16} />,
  "Deploy Prod Day 2": <Rocket size={16} />,
  "Deploy Prod Day 3": <Rocket size={16} />,
  "Deploy Prod Day 4": <Rocket size={16} />,
};

// Status Badge Component
const StatusBadge = ({ status }) => {
  const statusClass = status.toLowerCase().replace(/\s+/g, '-');
  return (
    <span className={`status-badge-calendar ${statusClass}`}>
      {status}
    </span>
  );
};

// Type Badge Component
const TypeBadge = ({ type }) => {
  const typeClass = type.toLowerCase().replace(/\s+/g, '-');
  return (
    <span className={`type-badge ${typeClass}`}>
      {type}
    </span>
  );
};

// Golden Release Badge Component
const GoldenBadge = ({ isGolden }) => {
  if (isGolden) {
    return (
      <span className="golden-badge yes">
        <CheckCircle2 size={14} /> Yes
      </span>
    );
  }
  return (
    <span className="golden-badge no">
      No
    </span>
  );
};

// Helper function to check if a release is a golden release
// Golden releases are every 3rd major release: 129.0, 132.0, 135.0, 138.0, etc.
const isGoldenRelease = (releaseName) => {
  // Must be a major release (ends with .0)
  if (!releaseName || !releaseName.endsWith('.0')) {
    return false;
  }
  // Extract the release number (e.g., R135.0 -> 135)
  const match = releaseName.match(/R(\d+)\.0/);
  if (!match) {
    return false;
  }
  const releaseNum = parseInt(match[1], 10);
  // Golden releases are divisible by 3 (129, 132, 135, 138, ...)
  return releaseNum % 3 === 0;
};

// Date Cell Component - highlights based on date status
const DateCell = ({ date }) => {
  if (!date || date === "-") {
    return <span className="date-empty">-</span>;
  }

  // Parse date and check if it's past, today, or future
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  
  let parsedDate;
  try {
    // Parse date format like "15-Jan-2026"
    const parts = date.match(/(\d{1,2})-(\w{3})-(\d{4})/);
    if (parts) {
      const months = {
        'Jan': 0, 'Feb': 1, 'Mar': 2, 'Apr': 3, 'May': 4, 'Jun': 5,
        'Jul': 6, 'Aug': 7, 'Sep': 8, 'Oct': 9, 'Nov': 10, 'Dec': 11
      };
      parsedDate = new Date(parseInt(parts[3]), months[parts[2]], parseInt(parts[1]));
    }
  } catch (e) {
    parsedDate = null;
  }

  let dateClass = "date-cell";
  if (parsedDate) {
    if (parsedDate < today) {
      dateClass += " date-past";
    } else if (parsedDate.getTime() === today.getTime()) {
      dateClass += " date-today";
    } else {
      dateClass += " date-future";
    }
  }

  return <span className={dateClass}>{date}</span>;
};

const ReleaseCalendarSection = ({ onRefresh, isRefreshing }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [releaseData, setReleaseData] = useState(null);
  const [filterType, setFilterType] = useState('all');
  const [filterGolden, setFilterGolden] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showAllWeekEvents, setShowAllWeekEvents] = useState(false);

  // Fetch release calendar data
  const fetchReleaseCalendar = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getReleaseCalendar();
      // Check if backend returned an error (PDF parsing failed)
      if (data.source === 'error') {
        setError(data.error || 'Failed to parse release calendar PDF');
        setReleaseData(null);
      } else {
        setReleaseData(data);
      }
    } catch (err) {
      console.error('Error fetching release calendar:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReleaseCalendar();
  }, []);

  const handleRefresh = async () => {
    api.clearCache();
    await fetchReleaseCalendar();
    if (onRefresh) {
      onRefresh();
    }
  };

  // Get milestone columns
  const milestones = releaseData?.milestones || [
    "IRR",
    "Branch Cut - EP",
    "Final Build - EP",
    "Signoff STG/FedAlpha - ENG",
    "Deploy MP Pre PROD",
    "Deploy Prod Day 1",
    "Deploy Prod Day 2",
    "Deploy Prod Day 3",
    "Deploy Prod Day 4",
  ];

  // Helper function to check if a release starts from 2026 (IRR date is in 2026 or later)
  const isRelease2026OrLater = (release) => {
    const milestones = release.milestones || {};
    const jan2026 = new Date(2026, 0, 1); // Jan 1, 2026
    
    // Check the IRR date (first milestone) - this is when the release starts
    const irrDate = milestones["IRR"];
    if (!irrDate || irrDate === "-") {
      // If no IRR date, check the earliest available date
      const months = {
        'Jan': 0, 'Feb': 1, 'Mar': 2, 'Apr': 3, 'May': 4, 'Jun': 5,
        'Jul': 6, 'Aug': 7, 'Sep': 8, 'Oct': 9, 'Nov': 10, 'Dec': 11
      };
      
      let earliestDate = null;
      for (const date of Object.values(milestones)) {
        if (!date || date === "-") continue;
        const parts = date.match(/(\d{1,2})-(\w{3})-(\d{4})/);
        if (parts) {
          const parsedDate = new Date(parseInt(parts[3]), months[parts[2]], parseInt(parts[1]));
          if (!earliestDate || parsedDate < earliestDate) {
            earliestDate = parsedDate;
          }
        }
      }
      
      // If we have a valid date, check if it's 2026+
      if (earliestDate) {
        return earliestDate >= jan2026;
      }
      
      // Fallback: check release name (R134+ are 2026 releases)
      // R133 was Dec 2025, R134+ are 2026
      const releaseMatch = release.name?.match(/R(\d+)/);
      if (releaseMatch) {
        const releaseNum = parseInt(releaseMatch[1]);
        return releaseNum >= 134; // R134 and later are 2026 releases
      }
      
      return false;
    }
    
    // Parse IRR date format like "01-Jan-2026"
    const parts = irrDate.match(/(\d{1,2})-(\w{3})-(\d{4})/);
    if (parts) {
      const months = {
        'Jan': 0, 'Feb': 1, 'Mar': 2, 'Apr': 3, 'May': 4, 'Jun': 5,
        'Jul': 6, 'Aug': 7, 'Sep': 8, 'Oct': 9, 'Nov': 10, 'Dec': 11
      };
      const parsedDate = new Date(parseInt(parts[3]), months[parts[2]], parseInt(parts[1]));
      return parsedDate >= jan2026;
    }
    
    return false;
  };

  // Filter releases
  const filteredReleases = useMemo(() => {
    const releases = releaseData?.releases || [];
    return releases.filter(release => {
      // Only show releases from Jan 1, 2026 onwards
      const is2026Release = isRelease2026OrLater(release);
      const matchesType = filterType === 'all' || release.type === filterType;
      const releaseIsGolden = isGoldenRelease(release.name);
      const matchesGolden = filterGolden === 'all' || 
        (filterGolden === 'yes' && releaseIsGolden) || 
        (filterGolden === 'no' && !releaseIsGolden);
      const matchesStatus = filterStatus === 'all' || release.status === filterStatus;
      const matchesSearch = searchQuery === '' || 
        release.name.toLowerCase().includes(searchQuery.toLowerCase());
      
      return is2026Release && matchesType && matchesGolden && matchesStatus && matchesSearch;
    });
  }, [releaseData, filterType, filterGolden, filterStatus, searchQuery]);

  // Calculate summary stats (only for 2026 releases)
  const summaryStats = useMemo(() => {
    const releases = releaseData?.releases || [];
    // Filter to only 2026 releases for stats
    const releases2026 = releases.filter(r => isRelease2026OrLater(r));
    const total = releases2026.length;
    const completed = releases2026.filter(r => r.status === 'Completed').length;
    const inProgress = releases2026.filter(r => r.status === 'In Progress').length;
    const planned = releases2026.filter(r => r.status === 'Planned').length;
    const majorReleases = releases2026.filter(r => r.type === 'Major Release').length;
    const minorReleases = releases2026.filter(r => r.type === 'Minor Release').length;
    const goldenReleases = releases2026.filter(r => isGoldenRelease(r.name)).length;
    
    return { total, completed, inProgress, planned, majorReleases, minorReleases, goldenReleases };
  }, [releaseData]);

  // Calculate upcoming milestones and current release info
  const upcomingInfo = useMemo(() => {
    const releases = releaseData?.releases || [];
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    const months = {
      'Jan': 0, 'Feb': 1, 'Mar': 2, 'Apr': 3, 'May': 4, 'Jun': 5,
      'Jul': 6, 'Aug': 7, 'Sep': 8, 'Oct': 9, 'Nov': 10, 'Dec': 11
    };
    
    const parseDate = (dateStr) => {
      if (!dateStr || dateStr === "-") return null;
      const parts = dateStr.match(/(\d{1,2})-(\w{3})-(\d{4})/);
      if (parts) {
        return new Date(parseInt(parts[3]), months[parts[2]], parseInt(parts[1]));
      }
      return null;
    };
    
    // Find next upcoming milestone across all releases
    let nextMilestone = null;
    let currentRelease = null;
    const thisWeekEvents = [];
    const nextWeek = new Date(today);
    nextWeek.setDate(nextWeek.getDate() + 7);
    
    releases.forEach(release => {
      if (!isRelease2026OrLater(release)) return;
      
      // Check if this is the current in-progress release
      if (release.status === 'In Progress') {
        currentRelease = release;
      }
      
      // Check all milestones
      Object.entries(release.milestones || {}).forEach(([milestoneName, dateStr]) => {
        const date = parseDate(dateStr);
        if (!date) return;
        
        // Check if this week
        if (date >= today && date <= nextWeek) {
          thisWeekEvents.push({
            release: release.name,
            milestone: milestoneName,
            date: dateStr,
            parsedDate: date,
            isToday: date.getTime() === today.getTime()
          });
        }
        
        // Find next milestone
        if (date >= today) {
          if (!nextMilestone || date < nextMilestone.parsedDate) {
            nextMilestone = {
              release: release.name,
              milestone: milestoneName,
              date: dateStr,
              parsedDate: date,
              daysUntil: Math.ceil((date - today) / (1000 * 60 * 60 * 24))
            };
          }
        }
      });
    });
    
    // Sort this week events by date
    thisWeekEvents.sort((a, b) => a.parsedDate - b.parsedDate);
    
    // Calculate progress for current release
    let currentReleaseProgress = null;
    if (currentRelease) {
      const allMilestones = Object.entries(currentRelease.milestones || {});
      const completedMilestones = allMilestones.filter(([_, dateStr]) => {
        const date = parseDate(dateStr);
        return date && date < today;
      });
      currentReleaseProgress = {
        release: currentRelease,
        completed: completedMilestones.length,
        total: allMilestones.length,
        percentage: allMilestones.length > 0 ? Math.round((completedMilestones.length / allMilestones.length) * 100) : 0
      };
    }
    
    return { nextMilestone, currentRelease, currentReleaseProgress, thisWeekEvents };
  }, [releaseData]);

  // Loading state
  if (loading) {
    return (
      <div className="release-calendar-section">
        <div className="loading-container">
          <Loader2 size={48} className="spin" />
          <p>Loading release calendar...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="release-calendar-section">
        <div className="error-container">
          <AlertCircle size={48} />
          <h3>Error Loading Release Calendar</h3>
          <p>{error}</p>
          <button onClick={handleRefresh} className="action-btn primary">
            <RefreshCw size={16} /> Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="release-calendar-section">
      {/* Header */}
      <div className="release-calendar-header">
        <div className="header-left">
          <h1 style={{ fontSize: '28px' }}><Calendar size={28} /> Release Calendar</h1>
          <p style={{ fontSize: '15px' }}>
            Track release schedules and deployment milestones in PST timezone.
            {releaseData?.source === 'sample' && (
              <span className="data-source-badge sample"> (Sample Data)</span>
            )}
            {releaseData?.source === 'pdf' && (
              <span className="data-source-badge pdf"> (From PDF)</span>
            )}
          </p>
        </div>
        <div className="header-actions">
          <a 
            href="https://your-org.atlassian.net/wiki/spaces/NH/pages/4296802580/YourCompany+Release+Schedule"
            target="_blank"
            rel="noopener noreferrer"
            className="action-btn primary"
          >
            <ExternalLink size={16} /> Release Schedule
          </a>
          <button 
            className={`action-btn secondary ${isRefreshing ? 'syncing' : ''}`}
            onClick={handleRefresh}
            disabled={isRefreshing || loading}
          >
            <RefreshCw size={16} className={isRefreshing ? 'spin' : ''} /> 
            {isRefreshing ? 'Syncing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Quick Insights Row */}
      <div className="release-insights-row">
        {/* Next Milestone Countdown */}
        {upcomingInfo.nextMilestone && (
          <div className="insight-card countdown">
            <div className="insight-icon">
              <Timer size={24} />
            </div>
            <div className="insight-content">
              <div className="insight-label">Next Milestone</div>
              <div className="insight-value">
                <span className="countdown-days">{upcomingInfo.nextMilestone.daysUntil}</span>
                <span className="countdown-unit">days</span>
              </div>
              <div className="insight-detail">
                {upcomingInfo.nextMilestone.release} • {upcomingInfo.nextMilestone.milestone}
              </div>
              <div className="insight-date">{upcomingInfo.nextMilestone.date}</div>
            </div>
          </div>
        )}
        
        {/* Current Release Progress */}
        {upcomingInfo.currentReleaseProgress && (
          <div className="insight-card current-release">
            <div className="insight-icon">
              <Activity size={24} />
            </div>
            <div className="insight-content">
              <div className="insight-label">Current Release</div>
              <div className="insight-value">
                <span className="release-name">{upcomingInfo.currentReleaseProgress.release.name}</span>
                {isGoldenRelease(upcomingInfo.currentReleaseProgress.release.name) && (
                  <Star size={16} className="golden-star" />
                )}
              </div>
              <div className="progress-bar-container">
                <div 
                  className="progress-bar-fill" 
                  style={{ width: `${upcomingInfo.currentReleaseProgress.percentage}%` }}
                />
              </div>
              <div className="insight-detail">
                {upcomingInfo.currentReleaseProgress.completed}/{upcomingInfo.currentReleaseProgress.total} milestones ({upcomingInfo.currentReleaseProgress.percentage}%)
              </div>
            </div>
          </div>
        )}
        
        {/* This Week Events */}
        <div className="insight-card this-week">
          <div className="insight-icon">
            <CalendarDays size={24} />
          </div>
          <div className="insight-content">
            <div className="insight-label">This Week</div>
            {upcomingInfo.thisWeekEvents.length === 0 ? (
              <div className="insight-empty">No events this week</div>
            ) : (
              <div className="week-events">
                {(showAllWeekEvents ? upcomingInfo.thisWeekEvents : upcomingInfo.thisWeekEvents.slice(0, 3)).map((event, idx) => (
                  <div key={idx} className={`week-event ${event.isToday ? 'today' : ''}`}>
                    <span className="event-release">{event.release}</span>
                    <span className="event-milestone">{event.milestone}</span>
                    {event.isToday && <span className="today-badge">TODAY</span>}
                  </div>
                ))}
                {upcomingInfo.thisWeekEvents.length > 3 && (
                  <div className="more-events clickable" onClick={() => setShowAllWeekEvents(!showAllWeekEvents)}>
                    {showAllWeekEvents ? 'Show less' : `+${upcomingInfo.thisWeekEvents.length - 3} more`}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="release-summary-stats">
        <div className="summary-stat-card">
          <div className="stat-icon-wrapper" style={{ background: 'linear-gradient(135deg, #3b5998, #4a6ba8)' }}>
            <Rocket size={28} />
          </div>
          <div className="stat-content">
            <span className="stat-value" style={{ fontSize: '32px' }}>{summaryStats.majorReleases}</span>
            <span className="stat-label" style={{ fontSize: '13px' }}>Major Releases</span>
          </div>
        </div>
        <div className="summary-stat-card">
          <div className="stat-icon-wrapper" style={{ background: 'linear-gradient(135deg, #8b5cf6, #7c3aed)' }}>
            <Package size={28} />
          </div>
          <div className="stat-content">
            <span className="stat-value" style={{ fontSize: '32px' }}>{summaryStats.minorReleases}</span>
            <span className="stat-label" style={{ fontSize: '13px' }}>Minor Releases</span>
          </div>
        </div>
        <div className="summary-stat-card">
          <div className="stat-icon-wrapper" style={{ background: 'linear-gradient(135deg, #f59e0b, #d97706)' }}>
            <Star size={28} />
          </div>
          <div className="stat-content">
            <span className="stat-value" style={{ fontSize: '32px' }}>{summaryStats.goldenReleases}</span>
            <span className="stat-label" style={{ fontSize: '13px' }}>Golden Releases</span>
          </div>
        </div>
        <div className="summary-stat-card">
          <div className="stat-icon-wrapper completed">
            <CheckCircle2 size={28} />
          </div>
          <div className="stat-content">
            <span className="stat-value" style={{ fontSize: '32px' }}>{summaryStats.completed}</span>
            <span className="stat-label" style={{ fontSize: '13px' }}>Completed</span>
          </div>
        </div>
        <div className="summary-stat-card">
          <div className="stat-icon-wrapper in-progress">
            <PlayCircle size={28} />
          </div>
          <div className="stat-content">
            <span className="stat-value" style={{ fontSize: '32px' }}>{summaryStats.inProgress}</span>
            <span className="stat-label" style={{ fontSize: '13px' }}>In Progress</span>
          </div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="release-filters-bar">
        <div className="filter-group">
          <Filter size={16} />
          <label>Type:</label>
          <select 
            className="filter-select"
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
          >
            <option value="all">All Types</option>
            <option value="Major Release">Major Release</option>
            <option value="Minor Release">Minor Release</option>
          </select>
        </div>
        <div className="filter-group">
          <label>Golden:</label>
          <select 
            className="filter-select"
            value={filterGolden}
            onChange={(e) => setFilterGolden(e.target.value)}
          >
            <option value="all">All</option>
            <option value="yes">Golden Only</option>
            <option value="no">Non-Golden Only</option>
          </select>
        </div>
        <div className="filter-group">
          <label>Status:</label>
          <select 
            className="filter-select"
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
          >
            <option value="all">All Status</option>
            <option value="Completed">Completed</option>
            <option value="In Progress">In Progress</option>
            <option value="Planned">Planned</option>
          </select>
        </div>
        <div className="search-input-wrapper">
          <Search size={16} />
          <input
            type="text"
            placeholder="Search releases (e.g., R134)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Release Table - Using HTML table for reliable column alignment */}
      <div className="release-table-container milestone-table">
        <table className="milestone-html-table">
          <thead>
            <tr className="milestone-table-header-row">
              <th className="milestone-th">Release</th>
              <th className="milestone-th">Type</th>
              <th className="milestone-th">Golden Release</th>
              {milestones.map((milestone, idx) => (
                <th key={idx} className="milestone-th">{milestone}</th>
              ))}
              <th className="milestone-th">Status</th>
            </tr>
          </thead>
          <tbody>
            {filteredReleases.length === 0 ? (
              <tr>
                <td colSpan={milestones.length + 4} className="no-releases-cell">
                  <div className="no-releases-message">
                    <AlertCircle size={32} />
                    <p>No releases found matching your filters.</p>
                  </div>
                </td>
              </tr>
            ) : (
              filteredReleases.map((release, index) => (
                <tr 
                  key={release.id || index} 
                  className={`milestone-table-row ${release.status.toLowerCase().replace(/\s+/g, '-')}`}
                >
                  <td className="milestone-td release-col">
                    <span className="release-name-badge">{release.name}</span>
                  </td>
                  <td className="milestone-td type-col">
                    <TypeBadge type={release.type} />
                  </td>
                  <td className="milestone-td golden-col">
                    <GoldenBadge isGolden={isGoldenRelease(release.name)} />
                  </td>
                  {milestones.map((milestone, idx) => (
                    <td key={idx} className="milestone-td date-col">
                      <DateCell date={release.milestones?.[milestone]} />
                    </td>
                  ))}
                  <td className="milestone-td status-col">
                    <StatusBadge status={release.status} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Table Footer */}
        <div className="release-table-footer">
          <div className="footer-info" style={{ fontSize: '13px' }}>
            Showing {filteredReleases.length} of {summaryStats.total} releases
            {releaseData?.source && (
              <span className="source-info"> • Source: {releaseData.source}</span>
            )}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="date-legend">
        <span className="legend-title">Date Legend:</span>
        <div className="legend-items">
          <div className="legend-item">
            <span className="legend-dot past"></span>
            <span>Past</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot today"></span>
            <span>Today</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot future"></span>
            <span>Upcoming</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ReleaseCalendarSection;
