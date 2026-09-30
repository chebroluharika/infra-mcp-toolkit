import React from 'react';
import {
  LayoutDashboard,
  Calendar,
  Phone,
  TestTube,
  Activity,
  AlertTriangle,
  FileSpreadsheet,
  HeartPulse,
  TrendingUp,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Menu,
  GitBranch,
  RotateCcw,
  FlaskConical,
  Shuffle,
  Lightbulb,
  FileBarChart,
  Rocket,
  Server,
  Workflow,
  Target,
  BookOpen
} from 'lucide-react';
import { DEFAULT_RELEASE } from '../config';

const Sidebar = ({ activeSection, setActiveSection, releaseInfo, collapsed, onToggle, isLoading }) => {
  const [expandedGroups, setExpandedGroups] = React.useState({
    'releases': true,
    'escalations': true,
    'health': true,
    'qa': true,
    'insights': true,
    'reports': true
  });

  const toggleGroup = (group) => {
    if (collapsed) return; // Don't toggle groups when collapsed
    setExpandedGroups(prev => ({
      ...prev,
      [group]: !prev[group]
    }));
  };

  const navGroups = [
    // ═══════════════════════════════════════════════════
    // OVERVIEW - Dashboard home
    // ═══════════════════════════════════════════════════
    {
      id: 'main',
      items: [
        { id: 'overview', label: 'Overview', icon: LayoutDashboard, color: '#d4552a' },
      ]
    },

    // ═══════════════════════════════════════════════════
    // RELEASES - Everything release-related
    // ═══════════════════════════════════════════════════
    {
      id: 'releases',
      label: 'Releases',
      icon: Rocket,
      color: '#e08d30',
      items: [
        { id: 'readiness-tracking', label: 'Release Readiness', icon: CheckSquare, source: 'JIRA' },
        { id: 'regression-tracking', label: 'Release Regressions', icon: TrendingUp, source: 'JIRA' },
        { id: 'release-calendar', label: 'Release Calendar', icon: Calendar, source: 'GCal' },
        { id: 'on-call-calendar', label: 'On-Call Calendar', icon: Phone, source: 'OpsGenie' },
        { id: 'feature-insights', label: 'Feature Insights', icon: Lightbulb, source: 'JIRA' },
      ]
    },

    // ═══════════════════════════════════════════════════
    // ESCALATIONS - High visibility, standalone
    // ═══════════════════════════════════════════════════
    {
      id: 'escalations',
      label: 'Escalations',
      icon: AlertTriangle,
      color: '#c93d3d',
      items: [
        { id: 'escalations-dashboard', label: 'Customer Escalations', icon: AlertTriangle, source: 'Jira + AI' },
        { id: 'docs-updates', label: 'Docs Updates', icon: BookOpen, source: 'JIRA' },
      ]
    },

    // ═══════════════════════════════════════════════════
    // SYSTEM HEALTH - Operational monitoring
    // ═══════════════════════════════════════════════════
    {
      id: 'health',
      label: 'System Health',
      icon: HeartPulse,
      color: '#10b981',
      items: [
        { id: 'stack-monitoring', label: 'Stack Health', icon: Server, source: 'Rancher' },
        { id: 'dev-pipelines', label: 'Build Health', icon: GitBranch, source: 'Jenkins' },
        { id: 'pdv-pipelines', label: 'PDV Health', icon: Workflow, source: 'Jenkins' },
        { id: 'regression-pipelines', label: 'Regression Status', icon: RotateCcw, source: 'Jenkins' },
      ]
    },

    // ═══════════════════════════════════════════════════
    // QA INSIGHTS - Testing & Quality
    // ═══════════════════════════════════════════════════
    {
      id: 'qa',
      label: 'QA Insights',
      icon: FlaskConical,
      color: '#7c5cdb',
      items: [
        { id: 'testrail', label: 'Test Coverage', icon: TestTube, source: 'TestRail' },
        { id: 'flaky-tests', label: 'Flaky Tests', icon: Shuffle, source: 'Jenkins' },
        { id: 'test-efficacy', label: 'Test Efficacy', icon: Target, source: 'JIRA', disabled: true },
      ]
    },

    // ═══════════════════════════════════════════════════
    // DEV INSIGHTS - Standalone, unique value
    // ═══════════════════════════════════════════════════
    {
      id: 'insights',
      label: 'Dev Insights',
      icon: Lightbulb,
      color: '#3b82f6',
      items: [
        { id: 'dev-digest', label: 'Activity Summary', icon: Activity, source: 'Multi' },
      ]
    },

    // ═══════════════════════════════════════════════════
    // REPORTS - Weekly status and documentation
    // ═══════════════════════════════════════════════════
    {
      id: 'reports',
      label: 'Reports',
      icon: FileBarChart,
      color: '#64748b',
      items: [
        { id: 'weekly-status', label: 'Weekly Status', icon: FileSpreadsheet, source: 'GSheets' },
      ]
    }
  ];

  const getSourceColor = (source) => {
    const colors = {
      'TestRail': '#3b7dd8',
      'JIRA': '#3b7dd8',
      'GSheets': '#1d9a6c',
      'Jenkins': '#c93d3d',
      'GCal': '#e08d30',
      'Rancher': '#0075a8',
      'Multi': '#7c5cdb'
    };
    return colors[source] || '#64748b';
  };

  // Get icon color based on source or explicit color
  const getIconColor = (item) => {
    if (item.color) return item.color;
    if (item.source) return getSourceColor(item.source);
    return '#8a8a8a'; // Default grey
  };

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      {/* Header */}
      <div className="sidebar-header">
        {!collapsed && (
          <div className="sidebar-logo">
            <div className="logo-icon">AI</div>
            <div className="logo-text">
              <span className="logo-title">Agentic Insights Portal</span>
              <span className="logo-version">{releaseInfo?.currentRelease || DEFAULT_RELEASE}</span>
            </div>
          </div>
        )}
        <button className="sidebar-toggle" onClick={onToggle} title={collapsed ? 'Expand menu' : 'Collapse menu'}>
          <Menu size={20} />
        </button>
      </div>


      {/* Navigation */}
      <nav className="sidebar-nav">
        {navGroups.map((group) => (
          <div key={group.id} className="nav-group">
            {group.label ? (
              <>
                <button 
                  className={`nav-group-header ${group.disabled ? 'disabled' : ''}`}
                  onClick={() => !group.disabled && toggleGroup(group.id)}
                  title={collapsed ? group.label : (group.disabled ? 'Coming Soon' : undefined)}
                  style={group.disabled ? { opacity: 0.5, cursor: 'not-allowed' } : {}}
                >
                  <group.icon size={16} style={{ color: group.disabled ? '#888' : (group.color || '#8a8a8a') }} />
                  {!collapsed && (
                    <>
                      <span style={group.disabled ? { color: '#888' } : {}}>{group.label}</span>
                      {group.disabled && <span style={{ fontSize: '9px', color: '#888', marginLeft: '8px' }}>Coming Soon</span>}
                      {!group.disabled && (expandedGroups[group.id] ? <ChevronDown size={16} /> : <ChevronRight size={16} />)}
                    </>
                  )}
                </button>
                {(expandedGroups[group.id] || collapsed) && (
                  <div className="nav-group-items">
                    {group.items.map((item) => (
                      <button
                        key={item.id}
                        className={`nav-item ${activeSection === item.id ? 'active' : ''} ${item.disabled ? 'disabled' : ''}`}
                        onClick={() => !item.disabled && setActiveSection(item.id)}
                        title={collapsed ? item.label : (item.disabled ? 'Coming Soon' : undefined)}
                        disabled={item.disabled}
                        style={item.disabled ? { opacity: 0.5, cursor: 'not-allowed', pointerEvents: 'auto' } : {}}
                      >
                        <item.icon size={16} style={{ color: item.disabled ? '#888' : getIconColor(item) }} />
                        {!collapsed && (
                          <>
                            <span className="nav-label" style={item.disabled ? { color: '#888' } : {}}>{item.label}</span>
                            {item.source && (
                              <span 
                                className="nav-source" 
                                style={{ color: item.disabled ? '#888' : getSourceColor(item.source) }}
                              >
                                {item.source}
                              </span>
                            )}
                            {item.disabled && (
                              <span style={{ fontSize: '9px', color: '#888', marginLeft: 'auto' }}>Coming Soon</span>
                            )}
                          </>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="nav-group-items main-items">
                {group.items.map((item) => (
                  <button
                    key={item.id}
                    className={`nav-item main ${activeSection === item.id ? 'active' : ''}`}
                    onClick={() => setActiveSection(item.id)}
                    title={collapsed ? item.label : undefined}
                  >
                    <item.icon size={18} style={{ color: getIconColor(item) }} />
                    {!collapsed && <span className="nav-label">{item.label}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </nav>

      {/* Footer (only when expanded) */}
      {!collapsed && (
        <div className="sidebar-footer">
          <div className="data-sources">
            <span className="sources-title">Connected</span>
            <div className="source-pills">
              <span className="source-pill" style={{ '--source-color': '#3b7dd8' }}>JIRA</span>
              <span className="source-pill" style={{ '--source-color': '#c93d3d' }}>Jenkins</span>
              <span className="source-pill" style={{ '--source-color': '#3b7dd8' }}>TestRail</span>
              <span className="source-pill" style={{ '--source-color': '#0075a8' }}>Rancher</span>
              <span className="source-pill" style={{ '--source-color': '#1d9a6c' }}>GSheets</span>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
};

export default Sidebar;
