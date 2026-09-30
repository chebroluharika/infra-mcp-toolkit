/**
 * ReleaseRegressionSection - Regression Tracking Dashboard
 * 
 * Displays hierarchical regression tracking data from Jira:
 * - Parent Epic (configured per release in backend/config.py)
 *   - Automation Efforts Epic -> Stories with status & subtasks
 *   - Manual Feature Validation Epic -> Stories with status & subtasks
 *   - Non-Functional Validation Epic -> Stories with status & subtasks
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  RefreshCw,
  ExternalLink,
  CheckCircle,
  XCircle,
  Clock,
  Target,
  Settings,
  AlertCircle,
  PlayCircle,
  MessageSquare,
  Loader,
  X,
  ChevronRight,
  BarChart3,
  Filter,
  ChevronDown,
  User,
  Search
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell
} from 'recharts';
import { DEFAULT_RELEASE, API_BASE_URL } from '../../config';
import DrillDownSunburst from '../charts/DrillDownSunburst';
import './ReleaseRegressionSection.css';

const ReleaseRegressionSection = ({ selectedRelease = DEFAULT_RELEASE }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [releaseConfig, setReleaseConfig] = useState(null);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [loadingComments, setLoadingComments] = useState({});
  const [comments, setComments] = useState({});
  const [parsedComments, setParsedComments] = useState({}); // For semantic comment display
  const [expandedComments, setExpandedComments] = useState({}); // Track which comments are expanded
  const [subtaskModal, setSubtaskModal] = useState(null); // { story, subtasks }
  const [testrailData, setTestrailData] = useState(null);
  const [testrailLoading, setTestrailLoading] = useState(false); // Loading state for TestRail
  const [testrailRunModal, setTestrailRunModal] = useState(null); // { story, run }
  const [testrailRunCases, setTestrailRunCases] = useState(null);
  const [loadingRunCases, setLoadingRunCases] = useState(false);
  const [progressData, setProgressData] = useState(null); // For completion timeline chart
  
  // Engineer filter state
  const [selectedEngineers, setSelectedEngineers] = useState([]); // Empty = show all
  const [engineerFilterOpen, setEngineerFilterOpen] = useState(false);
  const [engineerSearchQuery, setEngineerSearchQuery] = useState(''); // Search within engineer list

  // Mapping of Jira story patterns to TestRail run names
  // Patterns are checked in order - more specific patterns first
  // Format: { pattern: 'lowercase story text to match', run: 'TestRail Run Name' }
  const TESTRAIL_RUN_MAPPING = [
    // Windows - specific bit versions first
    { pattern: 'regression on windows - 32', run: 'Windows Automation - 32-bit' },
    { pattern: 'regression on windows - 64', run: 'Windows Automation - 64-bit' },
    { pattern: 'windows - 32', run: 'Windows Automation - 32-bit' },
    { pattern: 'windows - 64', run: 'Windows Automation - 64-bit' },
    
    // Backend
    { pattern: 'automated regression for backend', run: 'Backend Regression' },
    { pattern: 'regression for backend', run: 'Backend Regression' },
    { pattern: 'backend regression', run: 'Backend Regression' },
    
    // Mac
    { pattern: 'automated regression on mac', run: 'Mac Automation' },
    { pattern: 'regression on mac', run: 'Mac Automation' },
    
    // iOS
    { pattern: 'automated regression on ios', run: 'iOS Client Regression' },
    { pattern: 'regression on ios', run: 'iOS Client Regression' },
    
    // Android
    { pattern: 'automated regression on android', run: 'Android Regression (Version 13)' },
    { pattern: 'regression on android', run: 'Android Regression (Version 13)' },
    
    // Linux
    { pattern: 'automated regression on linux', run: 'Linux Automation' },
    { pattern: 'regression on linux', run: 'Linux Automation' },
    
    // Chrome OS
    { pattern: 'automated regression on chrome os', run: 'Chrome OS Regression' },
    { pattern: 'regression on chrome os', run: 'Chrome OS Regression' },
    { pattern: 'regression on chromeos', run: 'Chrome OS Regression' },
    
    // Web UI
    { pattern: 'webui automated regression', run: 'Web UI Automation' },
    { pattern: 'web ui automated regression', run: 'Web UI Automation' },
    { pattern: 'web ui regression', run: 'Web UI Automation' },
  ];

  // Category display configuration
  const CATEGORY_CONFIG = {
    automation: {
      label: 'Automation Efforts',
      icon: '🤖',
      color: '#6366f1',
      gradient: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
    },
    manual: {
      label: 'Manual Feature Validation',
      icon: '👆',
      color: '#10b981',
      gradient: 'linear-gradient(135deg, #10b981 0%, #34d399 100%)',
    },
    non_functional: {
      label: 'Non-Functional Validation',
      icon: '⚡',
      color: '#f59e0b',
      gradient: 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%)',
    },
    other: {
      label: 'Interop',
      icon: '🔗',
      color: '#6b7280',
      gradient: 'linear-gradient(135deg, #6b7280 0%, #9ca3af 100%)',
    }
  };

  // Get epic keys from release config
  const currentEpicKeys = releaseConfig?.regression_epics || [];
  const hasEpicsConfigured = currentEpicKeys.length > 0;

  // Fetch release config
  useEffect(() => {
    const fetchReleaseConfig = async () => {
      setConfigLoaded(false);
      try {
        const response = await fetch(`${API_BASE_URL}/api/config/releases`);
        if (response.ok) {
          const configData = await response.json();
          const releaseData = configData.releases?.find(r => r.id === selectedRelease);
          setReleaseConfig(releaseData || null);
        } else {
          setReleaseConfig(null);
        }
      } catch (err) {
        console.error('Failed to fetch release config:', err);
        setReleaseConfig(null);
      } finally {
        setConfigLoaded(true);
      }
    };
    
    fetchReleaseConfig();
  }, [selectedRelease]);

  // Fetch regression data when we have epic keys
  useEffect(() => {
    if (!configLoaded) return;
    
    if (hasEpicsConfigured) {
      fetchRegressionData();
    } else {
      setLoading(false);
      setData(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configLoaded, hasEpicsConfigured, JSON.stringify(currentEpicKeys)]);

  // Clear search query when dropdown closes
  useEffect(() => {
    if (!engineerFilterOpen) {
      setEngineerSearchQuery('');
    }
  }, [engineerFilterOpen]);

  // Reset engineer filter when release changes (data refresh)
  useEffect(() => {
    setSelectedEngineers([]);
    setEngineerFilterOpen(false);
    setEngineerSearchQuery('');
  }, [selectedRelease]);

  // Close engineer filter dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (engineerFilterOpen && !event.target.closest('.engineer-filter-container')) {
        setEngineerFilterOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [engineerFilterOpen]);

  const fetchRegressionData = async () => {
    if (!hasEpicsConfigured) return;
    
    setLoading(true);
    setError(null);
    
    // Clear all cached data to ensure fresh data on refresh
    setComments({});
    setParsedComments({});
    setExpandedComments({});
    setTestrailData(null);
    
    try {
      const epicKey = currentEpicKeys[0];
      const response = await fetch(
        `${API_BASE_URL}/api/jira/regression-tracking/hierarchy?epic_key=${epicKey}`
      );
      
      if (!response.ok) {
        throw new Error(`Failed to fetch regression data: ${response.status}`);
      }
      
      const result = await response.json();
      setData(result);
      
      // Auto-select first category with data
      const categories = result.categories || {};
      const firstWithData = ['automation', 'manual', 'non_functional', 'other'].find(
        cat => categories[cat]?.summary?.total > 0
      );
      if (firstWithData) {
        setSelectedCategory(firstWithData);
      }
      
      // Fetch progress data for timeline chart
      try {
        const progressResponse = await fetch(
          `${API_BASE_URL}/api/jira/regression-tracking/progress?epic_key=${epicKey}`
        );
        if (progressResponse.ok) {
          const progressResult = await progressResponse.json();
          setProgressData(progressResult);
        }
      } catch (progressErr) {
        console.error('Error fetching progress data:', progressErr);
      }
    } catch (err) {
      console.error('Error fetching regression data:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Find matching TestRail run for a story
  const findMatchingRun = useCallback((story) => {
    if (!testrailData?.testRuns || testrailData.testRuns.length === 0) {
      return null;
    }
    
    const summaryLower = story.summary.toLowerCase();
    
    // Check patterns in order (more specific patterns first)
    for (const { pattern, run: runName } of TESTRAIL_RUN_MAPPING) {
      if (summaryLower.includes(pattern)) {
        // Find the run in testrailData by matching the run name
        // Try exact match first, then partial match
        const runNameLower = runName.toLowerCase();
        let matchingRun = testrailData.testRuns.find(
          run => run.name.toLowerCase() === runNameLower
        );
        
        // Fallback: partial match (run name contains our target or vice versa)
        if (!matchingRun) {
          matchingRun = testrailData.testRuns.find(
            run => run.name.toLowerCase().includes(runNameLower) || 
                   runNameLower.includes(run.name.toLowerCase())
          );
        }
        
        // Fallback: match first significant word (for names like "Backend Regression")
        if (!matchingRun) {
          const firstWord = runNameLower.split(' ')[0];
          matchingRun = testrailData.testRuns.find(
            run => run.name.toLowerCase().startsWith(firstWord)
          );
        }
        
        if (matchingRun) {
          return { ...matchingRun, displayName: runName };
        }
      }
    }
    return null;
  }, [testrailData]);

  // Handle clicking on a story's TestRail badge
  const handleTestrailClick = useCallback(async (story, run) => {
    if (!run?.id) return;
    
    setTestrailRunModal({ story, run });
    setLoadingRunCases(true);
    setTestrailRunCases(null);
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/testrail/run/${run.id}/tests`);
      if (response.ok) {
        const data = await response.json();
        setTestrailRunCases(data);
      }
    } catch (err) {
      console.error('Failed to load TestRail test cases:', err);
    } finally {
      setLoadingRunCases(false);
    }
  }, []);

  // Load TestRail milestone data when Automation category is selected
  useEffect(() => {
    if (selectedCategory !== 'automation') {
      setTestrailData(null);
      setTestrailLoading(false);
      return;
    }
    
    const loadTestrailData = async () => {
      setTestrailLoading(true);
      console.log('[TestRail] Loading data for release:', selectedRelease);
      try {
        const response = await fetch(`${API_BASE_URL}/api/testrail/milestone-data?release_id=${selectedRelease}`);
        if (response.ok) {
          const result = await response.json();
          console.log('[TestRail] Loaded runs:', result.testRuns?.length, result.testRuns?.map(r => r.name));
          setTestrailData(result);
        } else {
          console.error('[TestRail] API error:', response.status);
        }
      } catch (err) {
        console.error('[TestRail] Failed to load data:', err);
      } finally {
        setTestrailLoading(false);
      }
    };
    
    loadTestrailData();
  }, [selectedCategory, selectedRelease]);

  // State for loading all comments
  const [loadingAllComments, setLoadingAllComments] = useState(false);

  // Categories that support parsed comments with LLM
  const PARSED_COMMENT_CATEGORIES = ['manual', 'automation', 'non_functional', 'other'];

  // Load all parsed comments for selected category
  const loadAllParsedComments = useCallback(async () => {
    if (!selectedCategory || !PARSED_COMMENT_CATEGORIES.includes(selectedCategory)) return;
    if (!data?.categories?.[selectedCategory]?.stories || loadingAllComments) return;
    
    const stories = data.categories[selectedCategory].stories;
    setLoadingAllComments(true);
    
    try {
      // Load comments for all stories in parallel (batch of 5 at a time)
      const batchSize = 5;
      for (let i = 0; i < stories.length; i += batchSize) {
        const batch = stories.slice(i, i + batchSize);
        await Promise.all(
          batch.map(async (story) => {
            if (parsedComments[story.key]) return; // Skip if already loaded
            
            try {
              const response = await fetch(`${API_BASE_URL}/api/jira/issue/${story.key}/parsed-comments`);
              if (response.ok) {
                const result = await response.json();
                setParsedComments(prev => ({ ...prev, [story.key]: result }));
              } else {
                // Mark as loaded but with error so UI doesn't show "pending" message
                console.error('Failed to load parsed comments for', story.key, '- status:', response.status);
                setParsedComments(prev => ({ 
                  ...prev, 
                  [story.key]: { intent: 'info', test_results: [], summary_notes: [], error: true } 
                }));
              }
            } catch (err) {
              console.error('Failed to load parsed comments for', story.key, err);
              // Mark as loaded but with error so UI doesn't show "pending" message
              setParsedComments(prev => ({ 
                ...prev, 
                [story.key]: { intent: 'info', test_results: [], summary_notes: [], error: true } 
              }));
            }
          })
        );
      }
    } finally {
      setLoadingAllComments(false);
    }
  }, [selectedCategory, data?.categories, parsedComments, loadingAllComments]);

  // Load comments for a specific issue on-demand
  const loadComment = useCallback(async (issueKey) => {
    if (comments[issueKey] || loadingComments[issueKey]) return;
    
    setLoadingComments(prev => ({ ...prev, [issueKey]: true }));
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/jira/issue/${issueKey}/comments`);
      if (response.ok) {
        const result = await response.json();
        const latestComment = result.comments?.[0]?.body || '';
        setComments(prev => ({ ...prev, [issueKey]: latestComment }));
      }
    } catch (err) {
      console.error('Failed to load comment for', issueKey, err);
    } finally {
      setLoadingComments(prev => ({ ...prev, [issueKey]: false }));
    }
  }, [comments, loadingComments]);

  const getStatusIcon = (statusCategory) => {
    switch (statusCategory) {
      case 'done':
        return <CheckCircle size={14} className="status-icon done" />;
      case 'in_progress':
        return <PlayCircle size={14} className="status-icon in-progress" />;
      case 'blocked':
        return <XCircle size={14} className="status-icon blocked" />;
      default:
        return <Clock size={14} className="status-icon todo" />;
    }
  };

  // Extract data (moved before conditional returns for hooks)
  const { parent_epic, categories = {}, overall_summary = {}, labels_summary = {} } = data || {};
  const selectedCatData = selectedCategory ? categories[selectedCategory] : null;
  const selectedConfig = selectedCategory ? CATEGORY_CONFIG[selectedCategory] : null;
  
  // Get ALL engineers across ALL categories (for global filter)
  const globalEngineerData = React.useMemo(() => {
    if (!categories) return { engineers: [], taskCounts: {}, byCategory: {} };
    
    const engineerSet = new Set();
    const taskCounts = {};
    const byCategory = {};
    
    Object.entries(categories).forEach(([catKey, cat]) => {
      byCategory[catKey] = {};
      (cat.stories || []).forEach(story => {
        const assignee = story.assignee || 'Unassigned';
        engineerSet.add(assignee);
        taskCounts[assignee] = (taskCounts[assignee] || 0) + 1;
        byCategory[catKey][assignee] = (byCategory[catKey][assignee] || 0) + 1;
      });
    });
    
    const engineers = Array.from(engineerSet).sort((a, b) => {
      if (a === 'Unassigned') return 1;
      if (b === 'Unassigned') return -1;
      return a.localeCompare(b);
    });
    
    return { engineers, taskCounts, byCategory };
  }, [categories]);

  // Calculate filtered category summaries (for category cards when global filter is active)
  const filteredCategorySummaries = React.useMemo(() => {
    if (selectedEngineers.length === 0) return null; // Use original summaries
    
    const summaries = {};
    Object.entries(categories).forEach(([catKey, cat]) => {
      const stories = (cat.stories || []).filter(story => {
        const assignee = story.assignee || 'Unassigned';
        return selectedEngineers.includes(assignee);
      });
      const total = stories.length;
      const done = stories.filter(s => s.status_category === 'done').length;
      const in_progress = stories.filter(s => s.status_category === 'in_progress').length;
      const blocked = stories.filter(s => s.status_category === 'blocked').length;
      const todo = total - done - in_progress - blocked;
      summaries[catKey] = {
        total,
        done,
        in_progress,
        blocked,
        todo,
        completion_percent: total > 0 ? Math.round((done / total) * 100) : 0
      };
    });
    return summaries;
  }, [categories, selectedEngineers]);

  // Filter stories by selected engineers
  const selectedStories = React.useMemo(() => {
    const stories = selectedCatData?.stories || [];
    if (selectedEngineers.length === 0) return stories; // No filter = show all
    return stories.filter(story => {
      const assignee = story.assignee || 'Unassigned';
      return selectedEngineers.includes(assignee);
    });
  }, [selectedCatData, selectedEngineers]);

  // Calculate filtered summary for display (current category)
  const filteredSummary = React.useMemo(() => {
    if (selectedEngineers.length === 0) return selectedCatData?.summary || {};
    const stories = selectedStories;
    const total = stories.length;
    const done = stories.filter(s => s.status_category === 'done').length;
    const in_progress = stories.filter(s => s.status_category === 'in_progress').length;
    const blocked = stories.filter(s => s.status_category === 'blocked').length;
    const todo = total - done - in_progress - blocked;
    return {
      total,
      done,
      in_progress,
      blocked,
      todo,
      completion_percent: total > 0 ? Math.round((done / total) * 100) : 0
    };
  }, [selectedStories, selectedEngineers, selectedCatData]);

  // Calculate filtered overall summary
  const filteredOverallSummary = React.useMemo(() => {
    if (selectedEngineers.length === 0) return overall_summary;
    
    let total = 0, done = 0, in_progress = 0, blocked = 0, todo = 0;
    Object.values(categories).forEach(cat => {
      (cat.stories || []).forEach(story => {
        const assignee = story.assignee || 'Unassigned';
        if (selectedEngineers.includes(assignee)) {
          total++;
          if (story.status_category === 'done') done++;
          else if (story.status_category === 'in_progress') in_progress++;
          else if (story.status_category === 'blocked') blocked++;
          else todo++;
        }
      });
    });
    
    return {
      total,
      done,
      in_progress,
      blocked,
      todo,
      completion_percent: total > 0 ? Math.round((done / total) * 100) : 0
    };
  }, [categories, selectedEngineers, overall_summary]);

  // Sunburst chart data - 3 levels: Category → Status → Engineer
  // Format for D3 sunburst component
  const sunburstData = React.useMemo(() => {
    const categoryColors = {
      automation: '#6366f1',
      manual: '#10b981', 
      non_functional: '#f59e0b',
      other: '#8b5cf6'
    };
    const statusColors = {
      done: '#22c55e',
      in_progress: '#3b82f6',
      blocked: '#ef4444',
      todo: '#94a3b8'
    };
    const categoryLabels = {
      automation: 'Automation',
      manual: 'Manual',
      non_functional: 'Non-Func',
      other: 'Interop'
    };
    const statusLabels = {
      done: 'Done',
      in_progress: 'In Prog',
      blocked: 'Blocked',
      todo: 'To Do'
    };

    let totalTasks = 0;
    const categoriesData = [];

    ['automation', 'manual', 'non_functional', 'other'].forEach(catKey => {
      const catStories = categories[catKey]?.stories || [];
      // Apply engineer filter if active
      const filteredStories = selectedEngineers.length === 0 
        ? catStories 
        : catStories.filter(s => selectedEngineers.includes(s.assignee || 'Unassigned'));
      
      if (filteredStories.length === 0) return;

      totalTasks += filteredStories.length;

      // Group by status
      const statusGroups = { done: [], in_progress: [], blocked: [], todo: [] };
      filteredStories.forEach(story => {
        const status = story.status_category || 'todo';
        statusGroups[status].push(story);
      });

      const statusesData = [];
      ['done', 'in_progress', 'blocked', 'todo'].forEach(status => {
        const statusStories = statusGroups[status];
        if (statusStories.length === 0) return;

        // Group by engineer
        const engineerCounts = {};
        statusStories.forEach(story => {
          const eng = story.assignee || 'Unassigned';
          engineerCounts[eng] = (engineerCounts[eng] || 0) + 1;
        });

        // Sort by count
        const engineersData = Object.entries(engineerCounts)
          .sort((a, b) => b[1] - a[1])
          .map(([engineer, count]) => ({
            name: engineer,
            value: count
          }));

        statusesData.push({
          name: statusLabels[status],
          key: status,
          color: statusColors[status],
          engineers: engineersData
        });
      });

      categoriesData.push({
        name: categoryLabels[catKey],
        key: catKey,
        color: categoryColors[catKey],
        statuses: statusesData
      });
    });

    return {
      total: totalTasks,
      categories: categoriesData
    };
  }, [categories, selectedEngineers]);

  // Check if no data available (e.g., R134 with old hierarchy)
  const hasNoData = !overall_summary.total || overall_summary.total === 0;

  // Loading state
  if (loading) {
    return (
      <div className="section-page regression-tracking">
        <div className="loading-state">
          <RefreshCw size={32} className="spinning" />
          <p>Loading regression tracking data...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="section-page regression-tracking">
        <div className="error-state">
          <AlertCircle size={32} />
          <p>Error loading regression data</p>
          <span>{error}</span>
          <button onClick={fetchRegressionData} className="action-btn primary" style={{ marginTop: '1rem' }}>
            <RefreshCw size={16} /> Retry
          </button>
        </div>
      </div>
    );
  }

  // No epic configured state
  if (!hasEpicsConfigured) {
    return (
      <div className="section-page regression-tracking">
        <div className="section-page-header">
          <div className="header-left">
            <h1><TrendingUp size={24} /> Regression Tracking</h1>
            <p className="header-subtitle">Release: {selectedRelease}</p>
          </div>
        </div>
        <div className="no-config-state">
          <div className="no-config-icon">
            <Settings size={40} />
          </div>
          <h3>No Epic Configured for {selectedRelease}</h3>
          <p>
            To track regression progress for this release, add the Jira epic key(s) to the 
            <code>regression_epics</code> field in <code>backend/config.py</code> (RELEASE_MILESTONES)
          </p>
          <div className="config-example">
{`{
  "id": "${selectedRelease}",
  ...
  "regression_epics": ["ENG-XXXXXX"]
}`}
          </div>
        </div>
      </div>
    );
  }

  // Show message for releases with no data
  if (hasNoData && data) {
    return (
      <div className="section-page regression-tracking">
        <div className="section-page-header">
          <div className="header-left">
            <h1><TrendingUp size={24} /> Regression Tracking</h1>
            <p className="header-subtitle">
              Release: {selectedRelease} • Epic: {currentEpicKeys.join(', ')}
            </p>
          </div>
          <div className="header-actions">
            <button onClick={fetchRegressionData} className="action-btn secondary">
              <RefreshCw size={16} /> Refresh
            </button>
            {parent_epic?.url && (
              <a 
                href={parent_epic.url}
                target="_blank" 
                rel="noopener noreferrer"
                className="action-btn primary"
              >
                <ExternalLink size={16} /> Open in Jira
              </a>
            )}
          </div>
        </div>
        
        <div className="no-data-message">
          <AlertCircle size={48} />
          <h3>No Regression Data Available</h3>
          <p>
            Regression tracking data is not available for <strong>{selectedRelease}</strong>.
          </p>
          <p className="hint">
            This release may use a different Jira hierarchy structure that is not supported, 
            or the regression epic has no child items.
          </p>
          {parent_epic?.url && (
            <a 
              href={parent_epic.url}
              target="_blank" 
              rel="noopener noreferrer"
              className="action-btn primary"
              style={{ marginTop: '16px' }}
            >
              <ExternalLink size={16} /> View Epic in Jira
            </a>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="section-page regression-tracking">
      {/* Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1><TrendingUp size={24} /> Regression Tracking</h1>
          <p className="header-subtitle">
            Release: {selectedRelease} • Epic: {currentEpicKeys.join(', ')}
          </p>
        </div>
        <div className="header-actions">
          <button onClick={fetchRegressionData} className="action-btn secondary">
            <RefreshCw size={16} /> Refresh
          </button>
          {parent_epic?.url && (
            <a 
              href={parent_epic.url}
              target="_blank" 
              rel="noopener noreferrer"
              className="action-btn primary"
            >
              <ExternalLink size={16} /> Open in Jira
            </a>
          )}
        </div>
      </div>

      {/* Overall Progress with Donut Chart */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '20px', marginBottom: '24px' }}>
        {/* Progress Donut Chart */}
        <div className="overall-progress-section" style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
          <div style={{ width: '140px', height: '140px', position: 'relative' }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={[
                    { name: 'Done', value: overall_summary.done || 0, color: '#10b981' },
                    { name: 'In Progress', value: overall_summary.in_progress || 0, color: '#3b82f6' },
                    { name: 'To Do', value: (overall_summary.total || 0) - (overall_summary.done || 0) - (overall_summary.in_progress || 0), color: '#e5e7eb' }
                  ]}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={65}
                  dataKey="value"
                  strokeWidth={0}
                >
                  {[
                    { name: 'Done', value: overall_summary.done || 0, color: '#10b981' },
                    { name: 'In Progress', value: overall_summary.in_progress || 0, color: '#3b82f6' },
                    { name: 'To Do', value: (overall_summary.total || 0) - (overall_summary.done || 0) - (overall_summary.in_progress || 0), color: '#e5e7eb' }
                  ].map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div style={{ 
              position: 'absolute', top: '50%', left: '50%', 
              transform: 'translate(-50%, -50%)', textAlign: 'center' 
            }}>
              <div style={{ fontSize: '24px', fontWeight: '700', color: '#10b981' }}>
                {overall_summary.completion_percent || 0}%
              </div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Complete</div>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <div className="progress-header" style={{ marginBottom: '12px' }}>
              <Target size={18} />
              <span className="progress-title">Overall Progress</span>
            </div>
            <div style={{ display: 'flex', gap: '20px', marginBottom: '12px' }}>
              <div>
                <div style={{ fontSize: '20px', fontWeight: '700', color: '#10b981' }}>{overall_summary.done || 0}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Completed</div>
              </div>
              <div>
                <div style={{ fontSize: '20px', fontWeight: '700', color: '#3b82f6' }}>{overall_summary.in_progress || 0}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>In Progress</div>
              </div>
              <div>
                <div style={{ fontSize: '20px', fontWeight: '700', color: '#94a3b8' }}>{(overall_summary.total || 0) - (overall_summary.done || 0) - (overall_summary.in_progress || 0)}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>To Do</div>
              </div>
            </div>
            <div className="progress-bar-container">
              <div className="progress-bar-fill" style={{ width: `${overall_summary.completion_percent || 0}%` }} />
            </div>
          </div>
        </div>

        {/* Action Items */}
        <div style={{ 
          background: 'var(--bg-secondary)', 
          borderRadius: '12px', 
          border: '1px solid var(--border-color)',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column'
        }}>
          <h4 style={{ margin: '0 0 12px 0', fontSize: '13px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertCircle size={16} style={{ color: 'var(--accent-orange)' }} />
            Action Items
          </h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flex: 1 }}>
            {(() => {
              const actions = [];
              const todoCount = (overall_summary.total || 0) - (overall_summary.done || 0) - (overall_summary.in_progress || 0);
              
              if (todoCount > 0) {
                actions.push({
                  type: 'warning',
                  text: `${todoCount} items not started yet`,
                  action: 'Start pending work'
                });
              }
              if (overall_summary.in_progress > 5) {
                actions.push({
                  type: 'info',
                  text: `${overall_summary.in_progress} items in progress`,
                  action: 'Complete ongoing work'
                });
              }
              if (overall_summary.completion_percent >= 90 && overall_summary.completion_percent < 100) {
                actions.push({
                  type: 'success',
                  text: 'Almost complete!',
                  action: 'Push for final completion'
                });
              }
              if (overall_summary.completion_percent === 100) {
                actions.push({
                  type: 'success',
                  text: 'All items completed!',
                  action: 'Verify and sign off'
                });
              }
              if (actions.length === 0) {
                actions.push({
                  type: 'info',
                  text: 'Continue steady progress',
                  action: 'Maintain momentum'
                });
              }
              
              return actions.slice(0, 3).map((item, idx) => (
                <div key={idx} style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  background: item.type === 'warning' ? 'rgba(245, 158, 11, 0.1)' :
                             item.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(59, 130, 246, 0.1)',
                  borderLeft: `3px solid ${item.type === 'warning' ? '#f59e0b' : item.type === 'success' ? '#10b981' : '#3b82f6'}`
                }}>
                  <div style={{ fontSize: '12px', fontWeight: '500', marginBottom: '2px' }}>{item.text}</div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>→ {item.action}</div>
                </div>
              ));
            })()}
          </div>
        </div>
      </div>

      {/* Analysis Charts Row */}
      <div className="regression-charts-section">
        {/* Completion Timeline Chart */}
        <div className="chart-card chart-card-wide">
          <div className="chart-header">
            <span className="chart-title"><BarChart3 size={14} /> Completion Timeline</span>
            <div className="chart-stats">
              <span className="stat-item"><strong>{overall_summary.done || 0}</strong> Completed</span>
              <span className="stat-item"><strong>{overall_summary.total || 0}</strong> Total</span>
              <span className="stat-item"><strong>{progressData?.summary?.avgPerDay?.toFixed(1) || '0'}</strong> Avg/Day</span>
            </div>
          </div>
          <div className="timeline-chart-container">
            {progressData?.chartData?.length > 0 ? (
              <ResponsiveContainer width="100%" height={140}>
                <AreaChart data={progressData.chartData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorCompleted" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.05}/>
                    </linearGradient>
                  </defs>
                  <XAxis 
                    dataKey="displayDate" 
                    tick={{ fontSize: 9, fill: 'var(--text-muted)' }} 
                    tickLine={false} 
                    axisLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis 
                    tick={{ fontSize: 9, fill: 'var(--text-muted)' }} 
                    tickLine={false} 
                    axisLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip 
                    contentStyle={{ 
                      background: 'var(--bg-secondary)', 
                      border: '1px solid var(--border-color)', 
                      borderRadius: '6px', 
                      fontSize: '11px' 
                    }}
                    formatter={(value, name) => [value, name === 'total' ? 'Completed' : name]}
                    labelFormatter={(label) => `Date: ${label}`}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="total" 
                    stroke="#10b981" 
                    strokeWidth={2}
                    fill="url(#colorCompleted)" 
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="no-chart-data">
                <TrendingUp size={20} />
                <span>No completion data available yet</span>
              </div>
            )}
          </div>
        </div>

        {/* Status Distribution */}
        <div className="chart-card">
          <div className="chart-header">
            <span className="chart-title"><PlayCircle size={14} /> By Status</span>
          </div>
          <div className="horizontal-bars">
            {(() => {
              const statusCounts = { done: 0, in_progress: 0, todo: 0 };
              ['automation', 'manual', 'non_functional', 'other'].forEach(catKey => {
                (categories[catKey]?.stories || []).forEach(story => {
                  statusCounts[story.status_category || 'todo']++;
                });
              });
              const maxCount = Math.max(...Object.values(statusCounts), 1);
              const cfg = { done: { label: 'Completed', color: '#10b981' }, in_progress: { label: 'In Progress', color: '#3b82f6' }, todo: { label: 'To Do', color: '#94a3b8' } };
              
              return ['done', 'in_progress', 'todo'].map(status => (
                <div key={status} className="bar-row">
                  <span className="bar-label">{cfg[status].label}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${(statusCounts[status] / maxCount) * 100}%`, background: cfg[status].color }} />
                  </div>
                  <span className="bar-count">{statusCounts[status]}</span>
                </div>
              ));
            })()}
          </div>
        </div>

        {/* Test Results from Comments (Semantic Intent Classification) */}
        <div className="chart-card">
          <div className="chart-header">
            <span className="chart-title"><CheckCircle size={14} /> Test Results</span>
            {Object.keys(parsedComments).length > 0 && (
              <span className="chart-badge">{Object.values(parsedComments).reduce((sum, pc) => sum + (pc.passed_count || 0) + (pc.failed_count || 0) + (pc.in_progress_count || 0) + (pc.blocked_count || 0), 0)} items</span>
            )}
          </div>
          {(() => {
            const results = { passed: 0, failed: 0, blocked: 0, in_progress: 0 };
            Object.values(parsedComments).forEach(pc => {
              results.passed += pc.passed_count || 0;
              results.failed += pc.failed_count || 0;
              results.blocked += pc.blocked_count || 0;
              results.in_progress += pc.in_progress_count || 0;
            });
            const total = results.passed + results.failed + results.blocked + results.in_progress;
            const maxCount = Math.max(...Object.values(results), 1);
            
            if (total === 0) {
              return (
                <div className="no-results-message">
                  <MessageSquare size={14} />
                  <span>Load comments to see results</span>
                </div>
              );
            }
            
            const cfg = { 
              passed: { label: 'Passed', color: '#10b981' }, 
              failed: { label: 'Failed', color: '#ef4444' }, 
              blocked: { label: 'Blocked', color: '#f59e0b' },
              in_progress: { label: 'In Progress', color: '#3b82f6' } 
            };
            return (
              <div className="horizontal-bars">
                {['passed', 'failed', 'blocked', 'in_progress'].map(status => (
                  results[status] > 0 && (
                    <div key={status} className="bar-row">
                      <span className="bar-label">{cfg[status].label}</span>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${(results[status] / maxCount) * 100}%`, background: cfg[status].color }} />
                      </div>
                      <span className="bar-count">{results[status]}</span>
                    </div>
                  )
                ))}
              </div>
            );
          })()}
        </div>
      </div>

      {/* Platform Coverage Sunburst */}
      {Object.keys(labels_summary).length > 0 && (() => {
        const PLATFORM_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#84cc16', '#14b8a6'];
        const sortedPlatforms = Object.entries(labels_summary).sort((a, b) => b[1].total - a[1].total);
        const totalTagged = sortedPlatforms.reduce((sum, [, v]) => sum + v.total, 0);
        const totalDone = sortedPlatforms.reduce((sum, [, v]) => sum + v.done, 0);
        const overallPercent = totalTagged > 0 ? Math.round((totalDone / totalTagged) * 100) : 0;

        const sunburstPlatformData = sortedPlatforms.map(([platform, pData]) => {
          const features = Object.entries(pData.features || {}).sort((a, b) => b[1].total - a[1].total);
          return { platform, ...pData, featureList: features };
        });

        const innerData = sunburstPlatformData.map(({ platform, total }) => ({ name: platform, value: total }));
        const outerData = sunburstPlatformData.flatMap(({ featureList }, pIdx) =>
          featureList.map(([feature, fData]) => ({ name: feature, value: fData.total, platformIndex: pIdx, ...fData }))
        );

        return (
        <div className="labels-sunburst-section" style={{ marginBottom: '24px' }}>
          <div className="chart-card">
            <div className="chart-header">
              <span className="chart-title"><Target size={14} /> Platform Coverage</span>
              <span className="chart-badge">{totalTagged} tagged items</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: '32px', padding: '20px 0' }}>
              {/* Sunburst: inner ring = platform, outer ring = features */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div style={{ width: '320px', height: '320px', position: 'relative' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      {/* Inner ring — Platforms */}
                      <Pie
                        data={innerData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={95}
                        dataKey="value"
                        strokeWidth={2}
                        stroke="var(--bg-primary)"
                      >
                        {innerData.map((entry, index) => (
                          <Cell key={entry.name} fill={PLATFORM_COLORS[index % PLATFORM_COLORS.length]} />
                        ))}
                      </Pie>
                      {/* Outer ring — Features */}
                      <Pie
                        data={outerData}
                        cx="50%"
                        cy="50%"
                        innerRadius={100}
                        outerRadius={140}
                        dataKey="value"
                        strokeWidth={1}
                        stroke="var(--bg-primary)"
                        label={({ name, cx, cy, midAngle, outerRadius: or2 }) => {
                          const RADIAN = Math.PI / 180;
                          const r = or2 + 14;
                          const x = cx + r * Math.cos(-midAngle * RADIAN);
                          const y = cy + r * Math.sin(-midAngle * RADIAN);
                          return (
                            <text x={x} y={y} fill="var(--text-secondary)" textAnchor={x > cx ? 'start' : 'end'} dominantBaseline="central" fontSize={10}>
                              {name}
                            </text>
                          );
                        }}
                      >
                        {outerData.map((entry, index) => {
                          const baseColor = PLATFORM_COLORS[entry.platformIndex % PLATFORM_COLORS.length];
                          const featureCount = sunburstPlatformData[entry.platformIndex].featureList.length;
                          const featureIdx = sunburstPlatformData[entry.platformIndex].featureList.findIndex(([f]) => f === entry.name);
                          const lighten = featureCount > 1 ? 0.15 + (featureIdx * 0.2) : 0.15;
                          const r = parseInt(baseColor.slice(1, 3), 16);
                          const g = parseInt(baseColor.slice(3, 5), 16);
                          const b = parseInt(baseColor.slice(5, 7), 16);
                          const lr = Math.min(255, Math.round(r + (255 - r) * lighten));
                          const lg = Math.min(255, Math.round(g + (255 - g) * lighten));
                          const lb = Math.min(255, Math.round(b + (255 - b) * lighten));
                          return <Cell key={`${entry.name}-${index}`} fill={`rgb(${lr},${lg},${lb})`} />;
                        })}
                      </Pie>
                      <Tooltip
                        formatter={(value, name) => [`${value} items`, name]}
                        contentStyle={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '8px', fontSize: '12px' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{
                    position: 'absolute', top: '50%', left: '50%',
                    transform: 'translate(-50%, -50%)', textAlign: 'center'
                  }}>
                    <div style={{ fontSize: '28px', fontWeight: '700', color: '#10b981' }}>{overallPercent}%</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Done</div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'center', marginTop: '8px' }}>
                  {sortedPlatforms.map(([name], index) => (
                    <span key={name} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--text-secondary)' }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: PLATFORM_COLORS[index % PLATFORM_COLORS.length], display: 'inline-block' }} />
                      {name}
                    </span>
                  ))}
                </div>
              </div>

              {/* Platform → Feature breakdown cards */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', maxHeight: '340px' }}>
                {sunburstPlatformData.map(({ platform, total, done, in_progress, todo, featureList }, pIdx) => {
                  const color = PLATFORM_COLORS[pIdx % PLATFORM_COLORS.length];
                  const donePercent = total > 0 ? Math.round((done / total) * 100) : 0;
                  return (
                    <div key={platform} style={{
                      padding: '14px 16px',
                      borderRadius: '10px',
                      background: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                      borderLeft: `4px solid ${color}`,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                        <span style={{ fontSize: '14px', fontWeight: '700' }}>{platform}</span>
                        <span style={{ fontSize: '13px', fontWeight: '600', color }}>{total} total</span>
                      </div>
                      <div style={{ height: '4px', borderRadius: '2px', background: 'var(--border-color)', marginBottom: '8px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${donePercent}%`, background: '#10b981', borderRadius: '2px' }} />
                      </div>
                      <div style={{ display: 'flex', gap: '12px', fontSize: '11px', marginBottom: featureList.length > 0 ? '10px' : '0' }}>
                        <span title="Completed" style={{ color: '#10b981' }}>✓ {done} done</span>
                        <span title="In progress" style={{ color: '#3b82f6' }}>↻ {in_progress} active</span>
                        <span title="Not started" style={{ color: '#94a3b8' }}>○ {todo} pending</span>
                        <span style={{ marginLeft: 'auto', fontWeight: '600' }}>{donePercent}%</span>
                      </div>
                      {featureList.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                          {featureList.map(([feature, fData]) => (
                            <span key={feature} style={{
                              padding: '3px 10px',
                              borderRadius: '12px',
                              fontSize: '11px',
                              fontWeight: '500',
                              background: `${color}18`,
                              color: color,
                              border: `1px solid ${color}30`,
                            }}>
                              {feature} <strong>{fData.done}/{fData.total}</strong>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
        );
      })()}

      {/* Interactive Drill-Down Sunburst Chart */}
      {sunburstData.total > 0 && (
        <div className="sunburst-section">
          <div className="sunburst-header">
            <h3>Task Distribution Overview</h3>
            <p>Interactive drill-down chart • Click segments to explore</p>
          </div>
          <div className="sunburst-content drilldown-layout">
            <DrillDownSunburst 
              data={sunburstData}
              width={420}
              height={420}
              onCategoryClick={(category) => setSelectedCategory(category)}
              onEngineerClick={(engineer) => {
                if (!selectedEngineers.includes(engineer)) {
                  setSelectedEngineers([engineer]);
                }
              }}
            />
            
            {/* Compact Legend */}
            <div className="sunburst-legend compact">
              <div className="legend-section">
                <h4>Categories</h4>
                <div className="legend-items">
                  {sunburstData.categories.map((cat, idx) => (
                    <div 
                      key={idx} 
                      className="legend-item clickable"
                      onClick={() => setSelectedCategory(cat.key)}
                    >
                      <span className="legend-color" style={{ background: cat.color }}></span>
                      <span className="legend-label">{cat.name}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="legend-section">
                <h4>Status Colors</h4>
                <div className="legend-items horizontal">
                  <div className="legend-item">
                    <span className="legend-color" style={{ background: '#22c55e' }}></span>
                    <span className="legend-label">Done</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-color" style={{ background: '#3b82f6' }}></span>
                    <span className="legend-label">In Progress</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-color" style={{ background: '#ef4444' }}></span>
                    <span className="legend-label">Blocked</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-color" style={{ background: '#94a3b8' }}></span>
                    <span className="legend-label">To Do</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Global Engineer Filter - only show when there are engineers */}
      {globalEngineerData.engineers.length > 0 && (
        <div className="global-filter-section">
          <div className="global-filter-row">
            <div className="global-filter-label">
              <Filter size={16} />
              <span>Filter by Engineer</span>
              {selectedEngineers.length > 0 && (
                <span className="filter-badge">{selectedEngineers.length} selected</span>
              )}
            </div>
            
            <div className="engineer-filter-container">
              <button 
                className={`engineer-filter-btn ${engineerFilterOpen ? 'open' : ''} ${selectedEngineers.length > 0 ? 'has-filter' : ''}`}
                onClick={() => setEngineerFilterOpen(!engineerFilterOpen)}
              >
                <User size={14} />
                <span>
                  {selectedEngineers.length === 0 
                    ? `Select from ${globalEngineerData.engineers.length} engineers` 
                    : selectedEngineers.length === 1 
                      ? selectedEngineers[0]
                      : `${selectedEngineers.length} engineers selected`}
                </span>
                <ChevronDown size={14} className={`chevron ${engineerFilterOpen ? 'rotated' : ''}`} />
              </button>
              
              {engineerFilterOpen && (
                <div className="engineer-filter-dropdown">
                  <div className="filter-dropdown-header">
                    <span>Select Engineers</span>
                    <div className="filter-actions">
                      <button
                        className="filter-action-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedEngineers([]);
                        }}
                        disabled={selectedEngineers.length === 0}
                      >
                        Clear
                      </button>
                      <button
                        className="filter-action-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedEngineers([...globalEngineerData.engineers]);
                        }}
                      >
                        Select All
                      </button>
                    </div>
                  </div>
                  <div className="filter-search-box">
                    <Search size={14} className="search-icon" />
                    <input
                      type="text"
                      placeholder="Search engineers..."
                      value={engineerSearchQuery}
                      onChange={(e) => setEngineerSearchQuery(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                    />
                    {engineerSearchQuery && (
                      <button 
                        className="search-clear-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setEngineerSearchQuery('');
                        }}
                      >
                        <X size={12} />
                      </button>
                    )}
                  </div>
                  <div className="filter-options-list">
                    {(() => {
                      const filteredEngineers = globalEngineerData.engineers
                        .filter(engineer => 
                          engineer.toLowerCase().includes(engineerSearchQuery.toLowerCase())
                        );
                      
                      if (filteredEngineers.length === 0) {
                        return (
                          <div className="no-results">
                            No engineers found for "{engineerSearchQuery}"
                          </div>
                        );
                      }
                      
                      return filteredEngineers.map(engineer => (
                        <label key={engineer} className="filter-option">
                          <input
                            type="checkbox"
                            checked={selectedEngineers.includes(engineer)}
                            onChange={(e) => {
                              e.stopPropagation();
                              if (e.target.checked) {
                                setSelectedEngineers(prev => [...prev, engineer]);
                              } else {
                                setSelectedEngineers(prev => prev.filter(eng => eng !== engineer));
                              }
                            }}
                          />
                          <span className="engineer-name">{engineer}</span>
                          <span className="engineer-count">{globalEngineerData.taskCounts[engineer]} tasks</span>
                        </label>
                      ));
                    })()}
                  </div>
                </div>
              )}
            </div>
            
            {selectedEngineers.length > 0 && (
              <div className="filter-summary">
                <span className="filter-summary-text">
                  Showing {filteredOverallSummary.total} of {overall_summary.total} tasks
                </span>
                <button 
                  className="clear-filter-btn"
                  onClick={() => setSelectedEngineers([])}
                >
                  <X size={12} />
                  Clear
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Category Cards - Clickable */}
      <div className="category-cards-grid">
        {['automation', 'manual', 'non_functional', 'other'].map(catKey => {
          const config = CATEGORY_CONFIG[catKey];
          const catData = categories[catKey] || { summary: {} };
          // Use filtered summary if filter is active, otherwise original
          const summary = filteredCategorySummaries 
            ? filteredCategorySummaries[catKey] 
            : (catData.summary || {});
          const originalSummary = catData.summary || {};
          const isSelected = selectedCategory === catKey;
          // Show card if original has data (even if filtered is 0)
          const hasData = originalSummary.total > 0;
          const hasFilteredData = summary.total > 0;
          
          if (!hasData && catKey === 'other') return null; // Hide empty "Other" category
          
          return (
            <div 
              key={catKey} 
              className={`category-card ${isSelected ? 'selected' : ''} ${!hasData ? 'empty' : ''} ${selectedEngineers.length > 0 && !hasFilteredData ? 'no-matches' : ''}`}
              onClick={() => hasFilteredData && setSelectedCategory(prev => prev === catKey ? null : catKey)}
              style={{ 
                '--card-color': config.color,
                '--card-gradient': config.gradient,
              }}
            >
              <div className="card-icon-wrapper">
                <span className="card-icon">{config.icon}</span>
              </div>
              <div className="card-content">
                <div className="card-label">{config.label}</div>
                <div className="card-stats-row">
                  <span className="card-progress">
                    {summary.done || 0}/{summary.total || 0}
                  </span>
                  <span className="card-percent">
                    {summary.completion_percent || 0}%
                  </span>
                </div>
                <div className="card-progress-bar">
                  <div 
                    className="card-progress-fill"
                    style={{ width: `${summary.completion_percent || 0}%` }}
                  />
                </div>
                {selectedEngineers.length > 0 && !hasFilteredData && (
                  <div className="no-matches-label">No matches for filter</div>
                )}
              </div>
              {isSelected && <div className="selected-indicator"><ChevronRight size={16} /></div>}
            </div>
          );
        })}
      </div>

      {/* Selected Category Table */}
      {selectedCategory && selectedCatData && (
        <div className="selected-category-section">
          <div className="section-header" style={{ borderLeftColor: selectedConfig?.color }}>
            <span className="section-icon">{selectedConfig?.icon}</span>
            <span className="section-title">{selectedConfig?.label}</span>
            <span className="section-count">
              {filteredSummary.done || 0}/{filteredSummary.total || 0} Complete
              {selectedEngineers.length > 0 && (
                <span className="filter-indicator"> (filtered)</span>
              )}
            </span>
            
            {/* Load All Comments button for categories with parsed comments */}
            {PARSED_COMMENT_CATEGORIES.includes(selectedCategory) && (
              <button 
                className={`load-all-comments-btn ${loadingAllComments ? 'loading' : ''}`}
                onClick={loadAllParsedComments}
                disabled={loadingAllComments}
              >
                {loadingAllComments ? (
                  <>
                    <Loader size={14} className="spinning" />
                    Loading Comments...
                  </>
                ) : (
                  <>
                    <MessageSquare size={14} />
                    Load All Comments
                  </>
                )}
              </button>
            )}
          </div>
          
          <div className="stories-table-container">
            <table className="stories-table">
              <thead>
                <tr>
                  <th className="col-key">Key</th>
                  <th className="col-name">Test Scenario</th>
                  <th className="col-assignee">Assignee</th>
                  <th className="col-status">Status</th>
                  {selectedCategory === 'automation' && <th className="col-testrail">TestRail</th>}
                  <th className="col-comment">Comments</th>
                </tr>
              </thead>
              <tbody>
                {selectedStories.map(story => (
                  <tr key={story.key} className={`status-row-${story.status_category}`}>
                    <td className="col-key">
                      <a 
                        href={story.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="story-key-link"
                      >
                        {story.key}
                      </a>
                    </td>
                    <td className="col-name">
                      <span className="story-summary">{story.summary}</span>
                    </td>
                    <td className="col-assignee">
                      <span className="assignee-name">{story.assignee || 'Unassigned'}</span>
                    </td>
                    <td className="col-status">
                      <span className={`status-badge ${story.status_category || 'todo'}`}>
                        {getStatusIcon(story.status_category)}
                        <span>{story.status}</span>
                      </span>
                    </td>
                    {selectedCategory === 'automation' && (
                      <td className="col-testrail">
                        {(() => {
                          // For automation category, check for matching TestRail run
                          const matchingRun = findMatchingRun(story);
                          
                          if (matchingRun) {
                            return (
                              <button 
                                className="testrail-run-badge"
                                onClick={() => handleTestrailClick(story, matchingRun)}
                                title={`View ${matchingRun.displayName} test cases`}
                              >
                                <span className="run-name-short">🧪 {matchingRun.displayName}</span>
                                <span className="run-stats">
                                  {matchingRun.passed}/{matchingRun.total}
                                </span>
                                <div className="run-mini-bar">
                                  <div 
                                    className="run-mini-fill"
                                    style={{ 
                                      width: `${matchingRun.passRate || 0}%`,
                                      background: matchingRun.passRate >= 95 ? '#10b981' : matchingRun.passRate >= 80 ? '#f59e0b' : '#ef4444'
                                    }}
                                  />
                                </div>
                                <span className="run-percent">{matchingRun.passRate}%</span>
                              </button>
                            );
                          } else if (testrailLoading) {
                            return (
                              <span className="loading-testrail" title="Loading TestRail data...">
                                <Loader size={12} className="spinning" />
                              </span>
                            );
                          } else {
                            return <span className="no-testrail">—</span>;
                          }
                        })()}
                      </td>
                    )}
                    <td className="col-comment">
                      {/* Show parsed comments with badges only for passed/failed */}
                      {PARSED_COMMENT_CATEGORIES.includes(selectedCategory) ? (
                        parsedComments[story.key] ? (
                          <div className="parsed-comments">
                            {/* Only show badges for definitive passed/failed statuses */}
                            {parsedComments[story.key].intent === 'passed' && (
                              <span className="intent-badge passed">✅ Passed</span>
                            )}
                            {parsedComments[story.key].intent === 'failed' && (
                              <span className="intent-badge failed">❌ Failed</span>
                            )}
                            {/* Show comment summary text */}
                            {(parsedComments[story.key].summary_notes?.length > 0 || 
                              parsedComments[story.key].test_results?.length > 0) ? (
                              <div className="comment-summary">
                                <span 
                                  className={`summary-text ${expandedComments[story.key] ? 'expanded' : ''}`}
                                  title={parsedComments[story.key].summary_notes?.[0] || 
                                         parsedComments[story.key].test_results?.[0]?.item || ''}
                                >
                                  {parsedComments[story.key].summary_notes?.[0] || 
                                   parsedComments[story.key].test_results?.[0]?.item || 'No details'}
                                </span>
                              </div>
                            ) : parsedComments[story.key].error ? (
                              <span className="no-parsed-results">⚠️ Load failed</span>
                            ) : (
                              <span className="no-parsed-results">No comments</span>
                            )}
                          </div>
                        ) : loadingAllComments ? (
                          <span className="loading-comment">
                            <Loader size={12} className="spinning" />
                          </span>
                        ) : (
                          <span className="pending-load">Click "Load All Comments" above</span>
                        )
                      ) : comments[story.key] ? (
                        <div className="comment-cell">
                          <MessageSquare size={12} />
                          <span className="comment-text">{comments[story.key]}</span>
                        </div>
                      ) : loadingComments[story.key] ? (
                        <span className="loading-comment">
                          <Loader size={12} className="spinning" />
                        </span>
                      ) : (
                        <button 
                          className="load-comment-btn"
                          onClick={() => loadComment(story.key)}
                          title="Load comment"
                        >
                          <MessageSquare size={12} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Subtask Modal */}
      {subtaskModal && (
        <div className="subtask-modal-overlay" onClick={() => setSubtaskModal(null)}>
          <div className="subtask-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">
                <span className="modal-icon">📋</span>
                <div>
                  <div className="modal-story-key">{subtaskModal.story.key}</div>
                  <div className="modal-story-summary">{subtaskModal.story.summary}</div>
                </div>
              </div>
              <button className="modal-close" onClick={() => setSubtaskModal(null)}>
                <X size={20} />
              </button>
            </div>
            <div className="modal-subtitle">
              Test Cases Covered ({subtaskModal.story.subtask_done}/{subtaskModal.story.subtask_count})
            </div>
            <div className="subtask-list">
              {subtaskModal.subtasks?.map(subtask => (
                <div key={subtask.key} className={`subtask-item ${subtask.status_category}`}>
                  <div className="subtask-status-icon">
                    {getStatusIcon(subtask.status_category)}
                  </div>
                  <div className="subtask-info">
                    <a 
                      href={`https://your-org.atlassian.net/browse/${subtask.key}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="subtask-key"
                    >
                      {subtask.key}
                    </a>
                    <span className="subtask-summary">{subtask.summary}</span>
                  </div>
                  <span className={`subtask-status-label ${subtask.status_category}`}>
                    {subtask.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TestRail Run Modal */}
      {testrailRunModal && (
        <div className="subtask-modal-overlay" onClick={() => { setTestrailRunModal(null); setTestrailRunCases(null); }}>
          <div className="subtask-modal testrail-run-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">
                <span className="modal-icon">🧪</span>
                <div>
                  <div className="modal-story-key">{testrailRunModal.story.key}</div>
                  <div className="modal-story-summary">{testrailRunModal.run.displayName || testrailRunModal.run.name}</div>
                </div>
              </div>
              <button className="modal-close" onClick={() => { setTestrailRunModal(null); setTestrailRunCases(null); }}>
                <X size={20} />
              </button>
            </div>
            
            {loadingRunCases ? (
              <div className="modal-loading">
                <Loader size={24} className="spinning" />
                <span>Loading test cases...</span>
              </div>
            ) : testrailRunCases ? (
              <>
                <div className="testrail-run-summary">
                  <div className="run-summary-stats">
                    <span className="stat passed"><CheckCircle size={14} /> {testrailRunCases.passed} Passed</span>
                    <span className="stat failed"><XCircle size={14} /> {testrailRunCases.failed} Failed</span>
                    <span className="stat blocked"><AlertCircle size={14} /> {testrailRunCases.blocked} Blocked</span>
                    <span className="stat untested"><Clock size={14} /> {testrailRunCases.untested} Untested</span>
                  </div>
                  <div className="run-progress-row">
                    <div className="run-progress-bar">
                      <div className="run-progress-fill" style={{ width: `${testrailRunCases.pass_rate || 0}%` }} />
                    </div>
                    <span className="run-pass-rate">{testrailRunCases.pass_rate || 0}%</span>
                  </div>
                  {testrailRunCases.url && (
                    <a href={testrailRunCases.url} target="_blank" rel="noopener noreferrer" className="testrail-open-link">
                      Open in TestRail <ExternalLink size={12} />
                    </a>
                  )}
                </div>
                <div className="modal-subtitle">
                  Test Cases ({testrailRunCases.tests?.length || 0})
                </div>
                <div className="testrail-test-list">
                  {testrailRunCases.tests?.map(test => (
                    <div key={test.id} className={`testrail-test-item ${test.status}`}>
                      <div className="test-status-icon">
                        {test.status === 'passed' && <CheckCircle size={14} className="status-icon done" />}
                        {test.status === 'failed' && <XCircle size={14} className="status-icon blocked" />}
                        {test.status === 'blocked' && <AlertCircle size={14} className="status-icon blocked" />}
                        {test.status === 'untested' && <Clock size={14} className="status-icon todo" />}
                        {test.status === 'retest' && <RefreshCw size={14} className="status-icon in-progress" />}
                      </div>
                      <div className="test-info">
                        <span className="test-case-id">C{test.case_id}</span>
                        <span className="test-title">{test.title}</span>
                      </div>
                      <span className={`test-status-label ${test.status}`}>
                        {test.status}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="modal-error">Failed to load test cases</div>
            )}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="legend">
        <span className="legend-item">
          <CheckCircle size={12} className="status-icon done" /> Done
        </span>
        <span className="legend-item">
          <PlayCircle size={12} className="status-icon in-progress" /> In Progress
        </span>
        <span className="legend-item">
          <XCircle size={12} className="status-icon blocked" /> Blocked
        </span>
        <span className="legend-item">
          <Clock size={12} className="status-icon todo" /> Not Started
        </span>
      </div>
    </div>
  );
};

export default ReleaseRegressionSection;
