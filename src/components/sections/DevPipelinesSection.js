/**
 * DevPipelinesSection - Dev Pipelines Dashboard
 * 
 * Displays status of Dev pipelines using shared components.
 * Pipelines are configured via JENKINS_DEV_PIPELINES environment variable.
 */
import React, { useState, useEffect } from 'react';
import {
  Code,
  RefreshCw,
  ExternalLink,
  Loader,
  AlertCircle,
  GitBranch,
  GitMerge,
  Tag,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Clock,
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  Zap,
  Heart,
  Timer,
  Filter,
  GitCommit,
  User,
  Calendar,
  BarChart2,
  Wrench
} from 'lucide-react';
import {
  PipelineCard,
  TfaModal,
  BuildLegend,
  useTfa
} from '../shared/PipelineComponents';

// Pipeline names for progressive loading
const PIPELINE_NAMES = [
  'client-feature-pipeline',
  'client-develop-pipeline', 
  'client-release-pipeline'
];

const DevPipelinesSection = ({ selectedRelease, onRefresh, isRefreshing }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [pipelinesData, setPipelinesData] = useState(null);
  const [loadingPipelines, setLoadingPipelines] = useState(new Set());
  const [useProgressiveLoad, setUseProgressiveLoad] = useState(true);
  const [prefetchedTfa, setPrefetchedTfa] = useState(new Set()); // Track pre-fetched TFA
  const [statusFilter, setStatusFilter] = useState('all'); // Quick filter state

  // Use shared TFA hook
  const {
    tfaModalOpen,
    tfaLoading,
    tfaData,
    tfaError,
    selectedBuild,
    fetchTfa,
    closeTfaModal
  } = useTfa();

  useEffect(() => {
    if (useProgressiveLoad) {
      fetchDevPipelinesProgressive();
    } else {
      fetchDevPipelines();
    }
  }, [selectedRelease]);

  // Background pre-fetch TFA data for failed/unstable builds
  // This ensures instant loading when user clicks Analyze
  useEffect(() => {
    if (!pipelinesData?.pipelines?.length) return;

    const prefetchTfaForFailedBuilds = async () => {
      const failedPipelines = pipelinesData.pipelines.filter(
        p => p.status === 'failed' || p.status === 'unstable'
      );

      // Pre-fetch TFA for each failed pipeline's last build (in background)
      failedPipelines.forEach(pipeline => {
        if (pipeline.lastBuild?.buildNumber) {
          const cacheKey = `${pipeline.name}:${pipeline.lastBuild.buildNumber}`;
          
          // Skip if already pre-fetched
          if (prefetchedTfa.has(cacheKey)) return;

          // Fire and forget - we don't need the result, just want to warm the cache
          fetch(`/api/jenkins/tfa/${pipeline.name}/${pipeline.lastBuild.buildNumber}?source=dev`)
            .then(response => {
              if (response.ok) {
                setPrefetchedTfa(prev => new Set([...prev, cacheKey]));
                console.log(`[TFA Pre-fetch] Cached: ${pipeline.name} #${pipeline.lastBuild.buildNumber}`);
              }
            })
            .catch(() => {
              // Silently ignore pre-fetch errors
            });
        }
      });
    };

    // Small delay to not compete with initial page load
    const timeoutId = setTimeout(prefetchTfaForFailedBuilds, 1000);
    return () => clearTimeout(timeoutId);
  }, [pipelinesData?.pipelines]);

  // Progressive loading: fetch each pipeline independently
  const fetchDevPipelinesProgressive = async (forceRefresh = false) => {
    setLoading(true);
    setError(null);
    setLoadingPipelines(new Set(PIPELINE_NAMES));
    
    if (forceRefresh) {
      setPipelinesData(null);
    }

    // Initialize empty structure
    setPipelinesData({
      pipelines: [],
      summary: {
        total: PIPELINE_NAMES.length,
        successRate: 0,
        buildsSuccess: 0,
        buildsFailed: 0,
        buildsRunning: 0,
        buildsUnstable: 0,
        buildsAborted: 0,
        totalBuilds: 0,
      },
      jenkinsUrl: '',
    });

    // Fetch each pipeline independently (they render as they arrive)
    const fetchSinglePipeline = async (pipelineName) => {
      try {
        const url = `/api/jenkins/dev-pipelines/${pipelineName}?num_builds=10`;
        const response = await fetch(url);
        
        if (response.ok) {
          const pipeline = await response.json();
          
          // Update pipelines data incrementally
          setPipelinesData(prev => {
            if (!prev) return prev;
            
            const existingPipelines = prev.pipelines.filter(p => p.name !== pipelineName);
            const newPipelines = [...existingPipelines, pipeline];
            
            // Recalculate summary from all loaded pipelines
            let totalBuilds = 0, buildsSuccess = 0, buildsFailed = 0;
            let buildsRunning = 0, buildsUnstable = 0, buildsAborted = 0;
            
            newPipelines.forEach(p => {
              const s = p.summary || {};
              totalBuilds += s.totalBuilds || 0;
              buildsSuccess += s.buildsSuccess || 0;
              buildsFailed += s.buildsFailed || 0;
              buildsRunning += s.buildsRunning || 0;
              buildsUnstable += s.buildsUnstable || 0;
              buildsAborted += s.buildsAborted || 0;
            });
            
            const completedBuilds = totalBuilds - buildsRunning;
            const successRate = completedBuilds > 0 ? Math.round((buildsSuccess / completedBuilds) * 100) : 0;
            
            return {
              ...prev,
              pipelines: newPipelines,
              jenkinsUrl: pipeline.url?.replace(/\/job\/.*/, '') || prev.jenkinsUrl,
              summary: {
                total: PIPELINE_NAMES.length,
                success: newPipelines.filter(p => p.status === 'success').length,
                failed: newPipelines.filter(p => p.status === 'failed').length,
                successRate,
                totalBuilds,
                buildsSuccess,
                buildsFailed,
                buildsRunning,
                buildsUnstable,
                buildsAborted,
              },
            };
          });
        }
      } catch (err) {
        console.error(`Failed to fetch pipeline ${pipelineName}:`, err);
      } finally {
        setLoadingPipelines(prev => {
          const next = new Set(prev);
          next.delete(pipelineName);
          return next;
        });
      }
    };

    // Start all fetches in parallel - each updates UI as it completes
    await Promise.all(PIPELINE_NAMES.map(name => fetchSinglePipeline(name)));
    setLoading(false);
  };

  // Original batch loading (fallback)
  const fetchDevPipelines = async (forceRefresh = false) => {
    setLoading(true);
    setError(null);

    if (forceRefresh) {
      setPipelinesData(null);
    }

    try {
      const url = `/api/jenkins/dev-pipelines?num_builds=10${forceRefresh ? '&force_refresh=true' : ''}`;
      const response = await fetch(url);

      if (response.ok) {
        const data = await response.json();
        setPipelinesData(data);
      } else {
        const errorData = await response.json().catch(() => ({}));
        setError(errorData.detail || 'Failed to fetch Dev pipelines');
        setPipelinesData(null);
      }
    } catch (err) {
      console.error('Failed to fetch Dev pipelines:', err);
      setError('Cannot connect to backend server');
      setPipelinesData(null);
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    if (useProgressiveLoad) {
      await fetchDevPipelinesProgressive(true);
    } else {
      await fetchDevPipelines(true);
    }
    setSyncing(false);
  };

  // Get icon for pipeline type
  const getPipelineIcon = (pipeline) => {
    const name = pipeline.name || '';
    if (name.includes('feature')) return <GitBranch size={18} style={{ color: 'var(--accent-purple)' }} />;
    if (name.includes('develop')) return <GitMerge size={18} style={{ color: 'var(--accent-blue)' }} />;
    if (name.includes('release')) return <Tag size={18} style={{ color: 'var(--accent-green)' }} />;
    return <Code size={18} style={{ color: 'var(--text-muted)' }} />;
  };

  // Handle TFA for a pipeline
  const handleAnalyze = (pipeline) => {
    if (pipeline.lastBuild) {
      fetchTfa(pipeline.name, pipeline.lastBuild.buildNumber, pipeline.displayName, 'dev');
    }
  };

  // Handle build click (for TFA on individual builds)
  const handleBuildClick = (pipeline, build) => {
    fetchTfa(pipeline.name, build.buildNumber, pipeline.displayName, 'dev');
  };

  // Get last success info for a pipeline
  const getLastSuccessInfo = (pipeline) => {
    const builds = pipeline.recentBuilds || [];
    if (pipeline.status === 'success') {
      return null; // Currently passing, no need to show
    }
    
    for (let i = 0; i < builds.length; i++) {
      if (builds[i].status === 'success') {
        return {
          buildNumber: builds[i].buildNumber,
          timestamp: builds[i].timestamp,
          buildsAgo: i
        };
      }
    }
    return { notFound: true, buildsChecked: builds.length };
  };

  // Detect flaky pipeline (alternating success/failure pattern)
  const detectFlakiness = (pipeline) => {
    const builds = pipeline.recentBuilds || [];
    if (builds.length < 4) return { isFlaky: false };
    
    let transitions = 0;
    let prevStatus = null;
    
    for (const build of builds.slice(0, 8)) {
      const isPass = build.status === 'success';
      const isFail = build.status === 'failed' || build.status === 'unstable';
      
      if (prevStatus !== null) {
        if ((prevStatus === 'pass' && isFail) || (prevStatus === 'fail' && isPass)) {
          transitions++;
        }
      }
      
      if (isPass) prevStatus = 'pass';
      else if (isFail) prevStatus = 'fail';
    }
    
    // 3+ transitions in 8 builds = flaky
    const isFlaky = transitions >= 3;
    const flakyScore = Math.min(100, Math.round((transitions / 4) * 100));
    
    return { 
      isFlaky, 
      transitions, 
      flakyScore,
      pattern: builds.slice(0, 6).map(b => 
        b.status === 'success' ? '✓' : (b.status === 'failed' ? '✗' : '○')
      ).join('')
    };
  };

  // Get build duration trend
  const getDurationTrend = (pipeline) => {
    const builds = pipeline.recentBuilds || [];
    // Filter out running builds (status === 'running') and builds with no duration
    const validBuilds = builds.filter(b => 
      b.status !== 'running' && b.durationMs && b.durationMs > 0
    );
    
    // If no valid builds with duration, try to use the pre-formatted duration from any completed build
    if (validBuilds.length === 0) {
      const completedBuild = builds.find(b => b.status !== 'running' && b.duration && b.duration !== 'N/A');
      return { 
        trend: 'stable', 
        avgDuration: completedBuild?.duration || '—',
        avgDurationMs: 0
      };
    }
    
    if (validBuilds.length < 2) {
      return { 
        trend: 'stable', 
        avgDuration: validBuilds[0]?.duration || formatDuration(validBuilds[0]?.durationMs) || '—',
        avgDurationMs: validBuilds[0]?.durationMs || 0
      };
    }
    
    // Calculate average of recent 3 vs previous 3
    const recent = validBuilds.slice(0, 3);
    const previous = validBuilds.slice(3, 6);
    
    const recentAvg = recent.reduce((sum, b) => sum + b.durationMs, 0) / recent.length;
    const avgDurationMs = recentAvg;
    
    if (previous.length === 0) {
      return { 
        trend: 'stable', 
        avgDuration: formatDuration(avgDurationMs),
        avgDurationMs 
      };
    }
    
    const previousAvg = previous.reduce((sum, b) => sum + b.durationMs, 0) / previous.length;
    const changePercent = ((recentAvg - previousAvg) / previousAvg) * 100;
    
    let trend = 'stable';
    if (changePercent > 15) trend = 'slower';
    else if (changePercent < -15) trend = 'faster';
    
    return {
      trend,
      changePercent: Math.round(changePercent),
      avgDuration: formatDuration(avgDurationMs),
      avgDurationMs,
      recentAvg: formatDuration(recentAvg),
      previousAvg: formatDuration(previousAvg)
    };
  };

  // Format duration from ms
  const formatDuration = (ms) => {
    if (!ms || ms <= 0) return '—';
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    
    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    if (minutes > 0) return `${minutes}m ${seconds % 60}s`;
    return `${seconds}s`;
  };

  // Get health score color
  const getHealthColor = (score) => {
    if (score >= 80) return 'var(--accent-green)';
    if (score >= 60) return 'var(--accent-yellow)';
    if (score >= 40) return 'var(--accent-orange)';
    return 'var(--accent-red)';
  };

  // Generate action items based on pipeline status
  const getActionItems = (pipelines) => {
    const actions = [];
    
    pipelines.forEach(pipeline => {
      const recentBuilds = pipeline.recentBuilds || [];
      
      // Failed pipeline
      if (pipeline.status === 'failed') {
        actions.push({
          priority: 'critical',
          title: `${pipeline.displayName} is failing`,
          description: `Build #${pipeline.lastBuild?.buildNumber || 'N/A'} failed`,
          action: 'Investigate build logs',
          url: pipeline.lastBuild?.url
        });
      }
      
      // Unstable pipeline
      if (pipeline.status === 'unstable') {
        actions.push({
          priority: 'warning',
          title: `${pipeline.displayName} is unstable`,
          description: 'Tests may be flaky',
          action: 'Review test stability'
        });
      }
      
      // Check for consecutive failures
      let consecutiveFailures = 0;
      for (const build of recentBuilds) {
        if (build.status === 'failed') {
          consecutiveFailures++;
        } else {
          break;
        }
      }
      if (consecutiveFailures >= 3 && pipeline.status !== 'failed') {
        actions.push({
          priority: 'critical',
          title: `${pipeline.displayName}: ${consecutiveFailures} consecutive failures`,
          description: 'Pipeline may have systemic issues',
          action: 'Check infrastructure & config'
        });
      }
      
      // Check failure rate
      if (recentBuilds.length >= 5) {
        const recentFailures = recentBuilds.slice(0, 5).filter(b => b.status === 'failed').length;
        if (recentFailures >= 3 && pipeline.status !== 'failed') {
          actions.push({
            priority: 'warning',
            title: `${pipeline.displayName}: ${recentFailures}/5 recent failures`,
            description: 'High failure rate detected',
            action: 'Review recent changes'
          });
        }
      }
      
      // Check for flaky pipeline
      const flakiness = detectFlakiness(pipeline);
      if (flakiness.isFlaky) {
        actions.push({
          priority: 'warning',
          title: `${pipeline.displayName} is flaky`,
          description: `${flakiness.transitions} status transitions detected`,
          action: 'Investigate test stability'
        });
      }
      
      // Check for slow builds (duration trend)
      const durationTrend = getDurationTrend(pipeline);
      if (durationTrend.trend === 'slower' && durationTrend.changePercent > 30) {
        actions.push({
          priority: 'info',
          title: `${pipeline.displayName}: builds slowing down`,
          description: `+${durationTrend.changePercent}% slower than previous`,
          action: 'Check for performance issues'
        });
      }
    });
    
    // All healthy
    if (actions.length === 0) {
      actions.push({
        priority: 'success',
        title: 'All pipelines healthy',
        description: 'All Dev pipelines are passing',
        action: 'Continue monitoring'
      });
    }
    
    // Sort by priority
    const priorityOrder = { critical: 0, warning: 1, info: 2, success: 3 };
    actions.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);
    
    return actions.slice(0, 4);
  };

  // Get commit info for a pipeline
  const getCommitInfo = (pipeline) => {
    const lastBuild = pipeline.lastBuild;
    if (!lastBuild) return null;
    
    // Check for changeSet or culprits data from Jenkins
    if (lastBuild.changeSet?.items?.length > 0) {
      const commit = lastBuild.changeSet.items[0];
      return {
        message: commit.msg || commit.comment || 'No message',
        author: commit.author?.fullName || commit.authorEmail || 'Unknown',
        id: commit.commitId?.substring(0, 7) || commit.id?.substring(0, 7) || ''
      };
    }
    
    // Fallback to culprits (who triggered the build)
    if (lastBuild.culprits?.length > 0) {
      return {
        message: 'Build triggered',
        author: lastBuild.culprits[0]?.fullName || 'Unknown',
        id: ''
      };
    }
    
    // Use any available commit data from the build
    if (lastBuild.commit) {
      return {
        message: lastBuild.commit.message || lastBuild.commit.msg || 'No message',
        author: lastBuild.commit.author || 'Unknown',
        id: lastBuild.commit.id?.substring(0, 7) || ''
      };
    }
    
    return null;
  };

  // Detect failure patterns across pipelines
  const getFailurePatterns = (pipelines) => {
    const patterns = {};
    
    pipelines.forEach(pipeline => {
      if (pipeline.status === 'failed' || pipeline.status === 'unstable') {
        // Group by error type if available, otherwise by status
        const errorType = pipeline.lastBuild?.errorType || pipeline.status;
        if (!patterns[errorType]) {
          patterns[errorType] = {
            type: errorType,
            pipelines: [],
            count: 0
          };
        }
        patterns[errorType].pipelines.push(pipeline.displayName);
        patterns[errorType].count++;
      }
    });
    
    // Also check for time-based patterns (failures in same timeframe)
    const recentFailures = pipelines.filter(p => 
      (p.status === 'failed' || p.status === 'unstable') && 
      p.lastBuild?.timestampMs
    );
    
    if (recentFailures.length >= 2) {
      // Check if failures happened within 30 minutes of each other
      const sortedByTime = recentFailures.sort((a, b) => 
        (b.lastBuild?.timestampMs || 0) - (a.lastBuild?.timestampMs || 0)
      );
      
      const timeWindow = 30 * 60 * 1000; // 30 minutes
      const clusteredFailures = [];
      
      for (let i = 0; i < sortedByTime.length - 1; i++) {
        const timeDiff = (sortedByTime[i].lastBuild?.timestampMs || 0) - 
                        (sortedByTime[i + 1].lastBuild?.timestampMs || 0);
        if (timeDiff < timeWindow) {
          if (!clusteredFailures.includes(sortedByTime[i].displayName)) {
            clusteredFailures.push(sortedByTime[i].displayName);
          }
          if (!clusteredFailures.includes(sortedByTime[i + 1].displayName)) {
            clusteredFailures.push(sortedByTime[i + 1].displayName);
          }
        }
      }
      
      if (clusteredFailures.length >= 2) {
        patterns['concurrent_failures'] = {
          type: 'Concurrent Failures',
          pipelines: clusteredFailures,
          count: clusteredFailures.length,
          description: 'Multiple pipelines failed around the same time'
        };
      }
    }
    
    return Object.values(patterns).sort((a, b) => b.count - a.count);
  };

  // Calculate build frequency stats
  const getBuildFrequencyStats = (pipelines) => {
    const now = Date.now();
    const oneDayMs = 24 * 60 * 60 * 1000;
    const oneWeekMs = 7 * oneDayMs;
    
    let buildsToday = 0;
    let buildsThisWeek = 0;
    let totalBuilds = 0;
    
    pipelines.forEach(pipeline => {
      const builds = pipeline.recentBuilds || [];
      builds.forEach(build => {
        const buildTime = build.timestampMs || 0;
        if (buildTime > 0) {
          totalBuilds++;
          if (now - buildTime < oneDayMs) {
            buildsToday++;
          }
          if (now - buildTime < oneWeekMs) {
            buildsThisWeek++;
          }
        }
      });
    });
    
    // Calculate daily average
    const avgBuildsPerDay = buildsThisWeek > 0 ? Math.round(buildsThisWeek / 7 * 10) / 10 : 0;
    
    return {
      today: buildsToday,
      thisWeek: buildsThisWeek,
      total: totalBuilds,
      avgPerDay: avgBuildsPerDay
    };
  };

  // Calculate time-to-fix metric
  const getTimeToFixStats = (pipelines) => {
    const fixTimes = [];
    
    pipelines.forEach(pipeline => {
      const builds = pipeline.recentBuilds || [];
      
      // Look for failure -> success transitions
      for (let i = 0; i < builds.length - 1; i++) {
        const currentBuild = builds[i];
        const previousBuild = builds[i + 1];
        
        // Found a fix: previous was failure, current is success
        if (currentBuild.status === 'success' && 
            (previousBuild.status === 'failed' || previousBuild.status === 'unstable')) {
          const fixTime = (currentBuild.timestampMs || 0) - (previousBuild.timestampMs || 0);
          if (fixTime > 0) {
            fixTimes.push({
              pipeline: pipeline.displayName,
              fixTimeMs: fixTime,
              fromBuild: previousBuild.buildNumber,
              toBuild: currentBuild.buildNumber
            });
          }
        }
      }
    });
    
    if (fixTimes.length === 0) {
      return { avgFixTime: null, fixes: [] };
    }
    
    const avgFixTimeMs = fixTimes.reduce((sum, f) => sum + f.fixTimeMs, 0) / fixTimes.length;
    const minFixTimeMs = Math.min(...fixTimes.map(f => f.fixTimeMs));
    const maxFixTimeMs = Math.max(...fixTimes.map(f => f.fixTimeMs));
    
    return {
      avgFixTime: formatDuration(avgFixTimeMs),
      avgFixTimeMs,
      minFixTime: formatDuration(minFixTimeMs),
      maxFixTime: formatDuration(maxFixTimeMs),
      totalFixes: fixTimes.length,
      fixes: fixTimes.slice(0, 5) // Last 5 fixes
    };
  };

  // Filter pipelines by status
  const getFilteredPipelines = (pipelines) => {
    if (statusFilter === 'all') return pipelines;
    if (statusFilter === 'passing') return pipelines.filter(p => p.status === 'success');
    if (statusFilter === 'failing') return pipelines.filter(p => p.status === 'failed');
    if (statusFilter === 'unstable') return pipelines.filter(p => p.status === 'unstable');
    return pipelines;
  };

  // Loading state
  if (loading && !pipelinesData) {
    return (
      <div className="jenkins-section">
        <div className="section-page-header">
          <div className="header-left">
            <h1><Code size={24} /> Dev Pipelines</h1>
            <p>Client Build Pipelines</p>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: '60px 20px' }}>
          {error ? (
            <>
              <AlertCircle size={32} style={{ color: 'var(--accent-red)', marginBottom: '12px' }} />
              <span style={{ color: 'var(--text-secondary)' }}>{error}</span>
              <button
                onClick={() => fetchDevPipelines()}
                style={{ marginTop: '16px', padding: '8px 16px', borderRadius: '6px', border: 'none', background: 'var(--accent-blue)', color: 'white', cursor: 'pointer' }}
              >
                Retry
              </button>
            </>
          ) : (
            <>
              <Loader size={32} className="spin" />
              <span style={{ marginTop: '12px' }}>Loading Dev pipeline data...</span>
            </>
          )}
        </div>
      </div>
    );
  }

  const { pipelines = [], summary = {} } = pipelinesData || {};
  const actionItems = getActionItems(pipelines);
  
  // Calculate additional stats
  const flakyPipelines = pipelines.filter(p => detectFlakiness(p).isFlaky);
  const avgHealthScore = pipelines.length > 0 
    ? Math.round(pipelines.reduce((sum, p) => sum + (p.health || 0), 0) / pipelines.length)
    : 0;
  const avgDurationMs = pipelines.length > 0
    ? pipelines.reduce((sum, p) => sum + (getDurationTrend(p).avgDurationMs || 0), 0) / pipelines.length
    : 0;
  
  // New metrics
  const failurePatterns = getFailurePatterns(pipelines);
  const buildFrequency = getBuildFrequencyStats(pipelines);
  const timeToFix = getTimeToFixStats(pipelines);
  const filteredPipelines = getFilteredPipelines(pipelines);
  
  // Filter counts for badges
  const filterCounts = {
    all: pipelines.length,
    passing: pipelines.filter(p => p.status === 'success').length,
    failing: pipelines.filter(p => p.status === 'failed').length,
    unstable: pipelines.filter(p => p.status === 'unstable').length
  };

  return (
    <div className="jenkins-section">
      {/* Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1><Code size={24} /> Dev Pipelines</h1>
          <p>Client Build Pipelines (Feature, Develop, Release)</p>
        </div>
        <div className="header-actions">
          <button
            className={`action-btn secondary ${syncing ? 'syncing' : ''}`}
            onClick={handleSync}
            disabled={syncing || loading}
          >
            <RefreshCw size={16} className={syncing ? 'spin' : ''} />
            {syncing ? 'Syncing...' : 'Refresh'}
          </button>
          <a
            href={pipelinesData?.jenkinsUrl || 'https://iad0-cisystem.example.com'}
            target="_blank"
            rel="noopener noreferrer"
            className="action-btn primary"
          >
            <ExternalLink size={16} /> Open in Jenkins
          </a>
        </div>
      </div>

      {/* Summary Section */}
      <div style={{
        background: 'var(--bg-secondary)',
        borderRadius: '12px',
        border: '1px solid var(--border-color)',
        padding: '20px',
        marginBottom: '20px'
      }}>
        <div style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
          {/* Stats Cards - Based on ALL recent builds */}
          <div style={{ display: 'flex', gap: '12px', flexShrink: 0, flexWrap: 'wrap' }}>
            <StatCard 
              value={`${summary.successRate || 0}%`}
              label="Success Rate"
              color={summary.successRate >= 80 ? 'var(--accent-green)' : 
                     summary.successRate >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)'}
            />
            <StatCard 
              value={summary.buildsSuccess || 0}
              label="Passed"
              color="var(--accent-green)"
              icon={<CheckCircle size={14} />}
            />
            <StatCard 
              value={summary.buildsFailed || 0} 
              label="Failed" 
              color={(summary.buildsFailed || 0) > 0 ? 'var(--accent-red)' : 'var(--text-muted)'}
              icon={<XCircle size={14} />}
            />
            <StatCard 
              value={summary.buildsRunning || 0} 
              label="Running" 
              color={(summary.buildsRunning || 0) > 0 ? 'var(--accent-blue)' : 'var(--text-muted)'}
              icon={<Loader size={14} />}
            />
            <StatCard 
              value={`${avgHealthScore}%`}
              label="Avg Health"
              color={getHealthColor(avgHealthScore)}
              icon={<Heart size={14} />}
            />
            <StatCard 
              value={flakyPipelines.length} 
              label="Flaky" 
              color={flakyPipelines.length > 0 ? 'var(--accent-orange)' : 'var(--text-muted)'}
              icon={<Zap size={14} />}
            />
            <StatCard 
              value={formatDuration(avgDurationMs)} 
              label="Avg Duration" 
              color="var(--accent-purple)"
              icon={<Timer size={14} />}
            />
          </div>

          {/* Action Items */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
              {(summary.buildsFailed || 0) > 0 ? (
                <AlertTriangle size={16} style={{ color: 'var(--accent-red)' }} />
              ) : (
                <CheckCircle size={16} style={{ color: 'var(--accent-green)' }} />
              )}
              <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                Action Items
              </span>
              {(summary.buildsFailed || 0) > 0 && (
                <span style={{ 
                  fontSize: '11px', padding: '3px 8px', borderRadius: '4px', 
                  background: 'rgba(244, 67, 54, 0.15)',
                  color: 'var(--accent-red)',
                  fontWeight: '600'
                }}>
                  {summary.buildsFailed} failed build(s)
                </span>
              )}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
              {actionItems.map((item, idx) => (
                <ActionItem key={idx} item={item} />
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Insights Row - Build Frequency, Time-to-Fix, Failure Patterns */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(3, 1fr)', 
        gap: '16px', 
        marginBottom: '20px' 
      }}>
        {/* Build Frequency Stats */}
        <div style={{
          background: 'var(--bg-secondary)',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          padding: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <BarChart2 size={16} style={{ color: 'var(--accent-blue)' }} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>Build Frequency</span>
          </div>
          <div style={{ display: 'flex', gap: '16px' }}>
            <div style={{ textAlign: 'center', flex: 1 }}>
              <div style={{ fontSize: '24px', fontWeight: '700', color: 'var(--accent-blue)' }}>
                {buildFrequency.today}
              </div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Today</div>
            </div>
            <div style={{ textAlign: 'center', flex: 1 }}>
              <div style={{ fontSize: '24px', fontWeight: '700', color: 'var(--accent-purple)' }}>
                {buildFrequency.thisWeek}
              </div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>This Week</div>
            </div>
            <div style={{ textAlign: 'center', flex: 1 }}>
              <div style={{ fontSize: '24px', fontWeight: '700', color: 'var(--text-secondary)' }}>
                {buildFrequency.avgPerDay}
              </div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Avg/Day</div>
            </div>
          </div>
        </div>

        {/* Time-to-Fix Metric */}
        <div style={{
          background: 'var(--bg-secondary)',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          padding: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <Wrench size={16} style={{ color: 'var(--accent-green)' }} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>Time to Fix</span>
          </div>
          {timeToFix.avgFixTime ? (
            <div style={{ display: 'flex', gap: '16px' }}>
              <div style={{ textAlign: 'center', flex: 1 }}>
                <div style={{ fontSize: '20px', fontWeight: '700', color: 'var(--accent-green)' }}>
                  {timeToFix.avgFixTime}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Average</div>
              </div>
              <div style={{ textAlign: 'center', flex: 1 }}>
                <div style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-secondary)' }}>
                  {timeToFix.minFixTime}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Fastest</div>
              </div>
              <div style={{ textAlign: 'center', flex: 1 }}>
                <div style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-secondary)' }}>
                  {timeToFix.totalFixes}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Fixes</div>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '10px', color: 'var(--text-muted)', fontSize: '13px' }}>
              <CheckCircle size={20} style={{ color: 'var(--accent-green)', marginBottom: '6px' }} />
              <div>No recent failures to fix</div>
            </div>
          )}
        </div>

        {/* Failure Patterns */}
        <div style={{
          background: 'var(--bg-secondary)',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          padding: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <Activity size={16} style={{ color: 'var(--accent-orange)' }} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>Failure Patterns</span>
          </div>
          {failurePatterns.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '80px', overflowY: 'auto' }}>
              {failurePatterns.slice(0, 3).map((pattern, idx) => (
                <div key={idx} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '6px 10px',
                  background: pattern.type === 'Concurrent Failures' ? 'rgba(255, 152, 0, 0.1)' : 'rgba(244, 67, 54, 0.1)',
                  borderRadius: '6px',
                  border: `1px solid ${pattern.type === 'Concurrent Failures' ? 'rgba(255, 152, 0, 0.2)' : 'rgba(244, 67, 54, 0.2)'}`
                }}>
                  <span style={{
                    fontSize: '11px',
                    fontWeight: '600',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: pattern.type === 'failed' ? 'var(--accent-red)' : 
                               pattern.type === 'unstable' ? 'var(--accent-orange)' : 'var(--accent-orange)',
                    color: 'white'
                  }}>
                    {pattern.count}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-primary)' }}>
                      {pattern.type === 'failed' ? 'Failed Builds' : 
                       pattern.type === 'unstable' ? 'Unstable Builds' : pattern.type}
                    </div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {pattern.pipelines.join(', ')}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '10px', color: 'var(--text-muted)', fontSize: '13px' }}>
              <CheckCircle size={20} style={{ color: 'var(--accent-green)', marginBottom: '6px' }} />
              <div>No failure patterns detected</div>
            </div>
          )}
        </div>
      </div>

      {/* Quick Filters */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        marginBottom: '16px',
        padding: '12px 16px',
        background: 'var(--bg-secondary)',
        borderRadius: '8px',
        border: '1px solid var(--border-color)'
      }}>
        <Filter size={16} style={{ color: 'var(--text-muted)' }} />
        <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-secondary)' }}>Filter:</span>
        <div style={{ display: 'flex', gap: '8px' }}>
          {[
            { key: 'all', label: 'All', color: 'var(--accent-blue)' },
            { key: 'passing', label: 'Passing', color: 'var(--accent-green)' },
            { key: 'failing', label: 'Failing', color: 'var(--accent-red)' },
            { key: 'unstable', label: 'Unstable', color: 'var(--accent-orange)' }
          ].map(filter => (
            <button
              key={filter.key}
              onClick={() => setStatusFilter(filter.key)}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: 'none',
                cursor: 'pointer',
                fontSize: '12px',
                fontWeight: '600',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                background: statusFilter === filter.key ? filter.color : 'var(--bg-tertiary)',
                color: statusFilter === filter.key ? 'white' : 'var(--text-secondary)',
                transition: 'all 0.2s ease'
              }}
            >
              {filter.label}
              <span style={{
                fontSize: '10px',
                padding: '2px 6px',
                borderRadius: '10px',
                background: statusFilter === filter.key ? 'rgba(255,255,255,0.2)' : 'var(--bg-secondary)',
                color: statusFilter === filter.key ? 'white' : 'var(--text-muted)'
              }}>
                {filterCounts[filter.key]}
              </span>
            </button>
          ))}
        </div>
        {statusFilter !== 'all' && (
          <button
            onClick={() => setStatusFilter('all')}
            style={{
              marginLeft: 'auto',
              padding: '4px 8px',
              borderRadius: '4px',
              border: 'none',
              background: 'transparent',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              fontSize: '11px'
            }}
          >
            Clear filter
          </button>
        )}
      </div>

      {/* Pipeline Cards - Enhanced with health, duration, flakiness */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: '16px' }}>
        {/* Show loading skeletons for pipelines still being fetched */}
        {Array.from(loadingPipelines).map((pipelineName) => (
          <div key={`loading-${pipelineName}`} style={{
            background: 'var(--bg-secondary)',
            borderRadius: '12px',
            border: '1px solid var(--border-color)',
            padding: '20px',
            minHeight: '200px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            gap: '12px'
          }}>
            <Loader size={24} className="spin" style={{ color: 'var(--accent-blue)' }} />
            <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>
              Loading {pipelineName.replace('client-', '').replace('-pipeline', '')}...
            </span>
          </div>
        ))}
        {filteredPipelines.length === 0 && loadingPipelines.size === 0 && (
          <div style={{
            gridColumn: '1 / -1',
            textAlign: 'center',
            padding: '40px 20px',
            color: 'var(--text-muted)'
          }}>
            <Filter size={32} style={{ marginBottom: '12px', opacity: 0.5 }} />
            <div style={{ fontSize: '14px' }}>No pipelines match the current filter</div>
            <button
              onClick={() => setStatusFilter('all')}
              style={{
                marginTop: '12px',
                padding: '8px 16px',
                borderRadius: '6px',
                border: 'none',
                background: 'var(--accent-blue)',
                color: 'white',
                cursor: 'pointer',
                fontSize: '13px'
              }}
            >
              Show All Pipelines
            </button>
          </div>
        )}
        {filteredPipelines.map((pipeline) => {
          const lastSuccess = getLastSuccessInfo(pipeline);
          const flakiness = detectFlakiness(pipeline);
          const durationTrend = getDurationTrend(pipeline);
          const healthScore = pipeline.health || 0;
          const commitInfo = getCommitInfo(pipeline);
          
          return (
            <div key={pipeline.name} style={{ position: 'relative' }}>
              {/* Flaky Badge */}
              {flakiness.isFlaky && (
                <div style={{
                  position: 'absolute',
                  top: '-8px',
                  right: '12px',
                  background: 'linear-gradient(135deg, #ff9800, #f57c00)',
                  color: 'white',
                  padding: '4px 10px',
                  borderRadius: '12px',
                  fontSize: '10px',
                  fontWeight: '700',
                  textTransform: 'uppercase',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  zIndex: 10,
                  boxShadow: '0 2px 8px rgba(255, 152, 0, 0.4)'
                }}>
                  <Zap size={10} /> Flaky
                </div>
              )}
              
              <PipelineCard
                key={pipeline.name}
                pipeline={pipeline}
                onAnalyze={handleAnalyze}
                onBuildClick={handleBuildClick}
                renderIcon={getPipelineIcon}
                isTfaCached={prefetchedTfa.has(`${pipeline.name}:${pipeline.lastBuild?.buildNumber}`)}
              />
              
              {/* Commit Info Bar */}
              {commitInfo && (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '10px 14px',
                  background: 'linear-gradient(135deg, rgba(33, 150, 243, 0.05), rgba(33, 150, 243, 0.02))',
                  borderLeft: '3px solid var(--accent-blue)',
                  marginTop: '-12px',
                  fontSize: '11px'
                }}>
                  <GitCommit size={14} style={{ color: 'var(--accent-blue)', flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      gap: '6px',
                      marginBottom: '2px'
                    }}>
                      {commitInfo.id && (
                        <span style={{
                          fontFamily: 'monospace',
                          fontSize: '10px',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          background: 'var(--accent-blue)',
                          color: 'white'
                        }}>
                          {commitInfo.id}
                        </span>
                      )}
                      <span style={{ 
                        color: 'var(--text-primary)', 
                        fontWeight: '500',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis'
                      }}>
                        {commitInfo.message.length > 50 
                          ? commitInfo.message.substring(0, 50) + '...' 
                          : commitInfo.message}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--text-muted)' }}>
                      <User size={10} />
                      <span>{commitInfo.author}</span>
                    </div>
                  </div>
                </div>
              )}
              
              {/* Enhanced Info Bar */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 14px',
                background: 'var(--bg-tertiary)',
                borderRadius: '0 0 12px 12px',
                marginTop: commitInfo ? '0' : '-12px',
                borderTop: '1px solid var(--border-color)',
                fontSize: '11px'
              }}>
                {/* Health Score */}
                <div style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '6px',
                  title: `Jenkins health score: ${healthScore}%`
                }} title={`Jenkins health score: ${healthScore}%`}>
                  <Heart size={12} style={{ color: getHealthColor(healthScore) }} />
                  <span style={{ 
                    color: getHealthColor(healthScore),
                    fontWeight: '600'
                  }}>
                    {healthScore}%
                  </span>
                  <span style={{ color: 'var(--text-muted)' }}>health</span>
                </div>
                
                {/* Duration Trend */}
                <div style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '6px'
                }} title={`Avg: ${durationTrend.avgDuration}${durationTrend.changePercent ? ` (${durationTrend.changePercent > 0 ? '+' : ''}${durationTrend.changePercent}%)` : ''}`}>
                  <Timer size={12} style={{ color: 'var(--text-muted)' }} />
                  <span style={{ color: 'var(--text-secondary)' }}>{durationTrend.avgDuration}</span>
                  {durationTrend.trend === 'slower' && (
                    <TrendingUp size={12} style={{ color: 'var(--accent-red)' }} title="Getting slower" />
                  )}
                  {durationTrend.trend === 'faster' && (
                    <TrendingDown size={12} style={{ color: 'var(--accent-green)' }} title="Getting faster" />
                  )}
                  {durationTrend.trend === 'stable' && (
                    <Minus size={12} style={{ color: 'var(--text-muted)' }} title="Stable" />
                  )}
                </div>
                
                {/* Last Success (for failing pipelines) */}
                {lastSuccess && !lastSuccess.notFound && (
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '6px',
                    color: 'var(--accent-orange)'
                  }} title={`Last passed: Build #${lastSuccess.buildNumber}`}>
                    <CheckCircle size={12} />
                    <span style={{ fontWeight: '500' }}>
                      #{lastSuccess.buildNumber}
                    </span>
                    <span style={{ color: 'var(--text-muted)' }}>
                      ({lastSuccess.buildsAgo} ago)
                    </span>
                  </div>
                )}
                {lastSuccess && lastSuccess.notFound && (
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '6px',
                    color: 'var(--accent-red)'
                  }} title={`No success in last ${lastSuccess.buildsChecked} builds`}>
                    <XCircle size={12} />
                    <span style={{ fontSize: '10px' }}>No recent success</span>
                  </div>
                )}
                
                {/* Flaky indicator (when flaky) */}
                {flakiness.isFlaky && (
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '4px',
                    color: 'var(--accent-orange)',
                    fontSize: '10px',
                    fontFamily: 'monospace'
                  }} title={`Pattern: ${flakiness.pattern} (${flakiness.transitions} transitions)`}>
                    <Activity size={12} />
                    <span>{flakiness.pattern}</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend - using shared component */}
      <div style={{ marginTop: '20px' }}>
        <BuildLegend />
      </div>

      {/* TFA Modal - using shared component */}
      <TfaModal
        isOpen={tfaModalOpen}
        onClose={closeTfaModal}
        loading={tfaLoading}
        error={tfaError}
        data={tfaData}
        selectedBuild={selectedBuild}
      />
    </div>
  );
};

// Helper components
const StatCard = ({ value, label, color, icon }) => (
  <div style={{
    background: color ? `linear-gradient(135deg, ${color}15, ${color}08)` : 'var(--bg-tertiary)',
    border: `1px solid ${color ? `${color}30` : 'var(--border-color)'}`,
    borderRadius: '10px',
    padding: '12px 16px',
    textAlign: 'center',
    minWidth: '70px'
  }}>
    <div style={{ 
      fontSize: '24px', 
      fontWeight: '700', 
      color: color || 'var(--text-primary)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '6px'
    }}>
      {icon && <span style={{ opacity: 0.8 }}>{icon}</span>}
      {value}
    </div>
    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>
      {label}
    </div>
  </div>
);

const ActionItem = ({ item }) => {
  const bgColor = {
    critical: 'rgba(244, 67, 54, 0.1)',
    warning: 'rgba(255, 193, 7, 0.1)',
    info: 'rgba(33, 150, 243, 0.1)',
    success: 'rgba(76, 175, 80, 0.1)'
  };
  
  const borderColor = {
    critical: 'rgba(244, 67, 54, 0.3)',
    warning: 'rgba(255, 193, 7, 0.3)',
    info: 'rgba(33, 150, 243, 0.3)',
    success: 'rgba(76, 175, 80, 0.3)'
  };
  
  const Icon = {
    critical: XCircle,
    warning: AlertTriangle,
    info: Clock,
    success: CheckCircle
  }[item.priority];
  
  const iconColor = {
    critical: 'var(--accent-red)',
    warning: 'var(--accent-orange)',
    info: 'var(--accent-blue)',
    success: 'var(--accent-green)'
  };

  return (
    <div 
      style={{ 
        display: 'flex', 
        alignItems: 'center', 
        gap: '8px', 
        padding: '8px 12px', 
        borderRadius: '8px',
        background: bgColor[item.priority],
        border: `1px solid ${borderColor[item.priority]}`,
        cursor: item.url ? 'pointer' : 'default'
      }}
      onClick={() => item.url && window.open(item.url, '_blank')}
      title={item.url ? 'Click to view in Jenkins' : ''}
    >
      <Icon size={14} style={{ color: iconColor[item.priority] }} />
      <div>
        <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>{item.title}</div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          {item.description} → {item.action}
        </div>
      </div>
    </div>
  );
};

export default DevPipelinesSection;
