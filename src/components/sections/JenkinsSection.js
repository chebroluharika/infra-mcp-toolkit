import React, { useState, useEffect } from 'react';
import {
  Activity,
  CheckCircle,
  XCircle,
  AlertCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Timer,
  TrendingUp,
  Bug,
  Loader,
  Server,
  Layers,
  Info
} from 'lucide-react';
import { TfaModal, useTfa } from '../shared/PipelineComponents';

// Helper to format stack display name
const formatStackName = (stack, byStackData) => {
  if (stack === 'default') return 'No Stack';
  // Try to get displayName from byStack data if available
  const stackData = byStackData?.[stack];
  if (stackData?.displayName) return stackData.displayName;
  return stack.toUpperCase();
};

const JenkinsSection = ({ selectedRelease, onRefresh, isRefreshing }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [syncing, setSyncing] = useState(false);
  
  // New stack-based state
  const [regressionByStack, setRegressionByStack] = useState(null);
  const [regressionGroupBy, setRegressionGroupBy] = useState('stack'); // 'stack' or 'pipeline'
  const [selectedStackFilter, setSelectedStackFilter] = useState('all');
  const [recentBuilds, setRecentBuilds] = useState([]);
  
  // TFA state - using shared hook
  const {
    tfaModalOpen,
    tfaLoading,
    tfaData,
    tfaError,
    selectedBuild,
    fetchTfa,
    closeTfaModal
  } = useTfa();
  const [selectedPipelineForTfa, setSelectedPipelineForTfa] = useState(null);
  
  // Expanded state for views
  const [expandedStacks, setExpandedStacks] = useState({});
  const [expandedPipelines, setExpandedPipelines] = useState({});

  useEffect(() => {
    fetchRegressionByStack();
  }, [selectedRelease]);

  // Fetch Regression data grouped by stack
  const fetchRegressionByStack = async (forceRefresh = false) => {
    setLoading(true);
    setError(null);
    
    if (forceRefresh) {
      setRegressionByStack(null);
      setRecentBuilds([]);
    }
    
    try {
      const url = `/api/jenkins/regression-summary?num_builds=30${forceRefresh ? '&force_refresh=true' : ''}`;
      const response = await fetch(url);
      
      if (response.ok) {
        const data = await response.json();
        setRegressionByStack(data);
        
        // Construct recent builds from byStack data
        const allBuilds = [];
        Object.entries(data.byStack || {}).forEach(([stack, stackInfo]) => {
          (stackInfo.allBuilds || []).forEach(build => {
            allBuilds.push({
              ...build,
              stack: stack,
              jobName: build.pipelineName || build.pipelineKey
            });
          });
        });
        
        // Sort by timestamp and take top 30
        const sortedBuilds = allBuilds.sort((a, b) => {
          return (b.timestampMs || 0) - (a.timestampMs || 0);
        }).slice(0, 30);
        
        setRecentBuilds(sortedBuilds);
      } else {
        const errorData = await response.json().catch(() => ({}));
        setError(errorData.detail || 'Failed to fetch regression data');
        setRegressionByStack(null);
      }
    } catch (err) {
      console.error('Failed to fetch regression data:', err);
      setError('Cannot connect to backend server');
      setRegressionByStack(null);
    } finally {
      setLoading(false);
    }
  };

  // Handle refresh
  const handleSync = async () => {
    setSyncing(true);
    await fetchRegressionByStack(true);
    setSyncing(false);
  };

  // Parse duration string to minutes
  const parseDuration = (durationStr) => {
    if (!durationStr || durationStr === '-') return 0;
    let minutes = 0;
    const hourMatch = durationStr.match(/(\d+)h/);
    const minMatch = durationStr.match(/(\d+)m/);
    const secMatch = durationStr.match(/(\d+)s/);
    if (hourMatch) minutes += parseInt(hourMatch[1]) * 60;
    if (minMatch) minutes += parseInt(minMatch[1]);
    if (secMatch) minutes += parseInt(secMatch[1]) / 60;
    return Math.round(minutes * 10) / 10;
  };

  // Get stack success rates
  const getStackSuccessRates = () => {
    if (!regressionByStack?.byStack) return [];
    
    return Object.entries(regressionByStack.byStack).map(([stack, stackInfo]) => {
      const summary = stackInfo.summary || {};
      return {
        stack: stack,
        successRate: summary.passRate || 0,
        passed: summary.passed || 0,
        failed: summary.failed || 0,
        total: summary.total || 0
      };
    }).sort((a, b) => b.successRate - a.successRate);
  };

  // Get recent failures
  const getRecentFailures = () => {
    if (!regressionByStack?.byStack) return [];
    
    const failures = [];
    Object.entries(regressionByStack.byStack).forEach(([stack, stackInfo]) => {
      (stackInfo.allBuilds || []).forEach(build => {
        if (build.status === 'failed' || build.status === 'aborted') {
          failures.push({ ...build, stack });
        }
      });
    });
    
    return failures.sort((a, b) => (b.timestampMs || 0) - (a.timestampMs || 0)).slice(0, 10);
  };

  // Get failure reasons
  const getFailureReasons = () => {
    const failures = getRecentFailures();
    const reasons = {};
    
    failures.forEach(build => {
      const pipelineName = build.pipelineKey || 'Unknown';
      if (!reasons[pipelineName]) {
        reasons[pipelineName] = { count: 0, stacks: new Set() };
      }
      reasons[pipelineName].count++;
      reasons[pipelineName].stacks.add(build.stack);
    });
    
    const sorted = Object.entries(reasons)
      .map(([reason, data]) => ({
        reason: reason,
        count: data.count,
        stacks: Array.from(data.stacks)
      }))
      .sort((a, b) => b.count - a.count);
    
    return {
      total: failures.length,
      reasons: sorted.slice(0, 5),
      recurring: sorted.filter(r => r.count >= 2)
    };
  };

  // Get execution times per stack
  const getExecutionTimes = () => {
    if (!regressionByStack?.byStack) return [];
    
    return Object.entries(regressionByStack.byStack).map(([stack, stackInfo]) => {
      const builds = stackInfo.allBuilds || [];
      const durations = builds.map(b => parseDuration(b.duration)).filter(d => d > 0);
      const avgDuration = durations.length > 0 
        ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) 
        : 0;
      
      return {
        stack: stack,
        avgDuration: avgDuration,
        buildCount: builds.length
      };
    }).sort((a, b) => b.avgDuration - a.avgDuration);
  };

  // Get action items
  const getActionItems = () => {
    if (!regressionByStack) return [];
    
    const actions = [];
    const failedBuilds = getRecentFailures();
    const stackSuccessRates = getStackSuccessRates();
    const { recurring } = getFailureReasons();
    const executionTimes = getExecutionTimes();
    
    // Collect all builds for analysis
    const allBuilds = [];
    Object.entries(regressionByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      (stackInfo.allBuilds || []).forEach(build => {
        allBuilds.push({ ...build, stack });
      });
    });
    
    // Helper for formatting stack names in action items
    const fmtStack = (s) => formatStackName(s, regressionByStack?.byStack);
    
    // 1. Critical: Failed builds
    if (failedBuilds.length > 0) {
      actions.push({
        priority: failedBuilds.length >= 3 ? 'critical' : 'warning',
        title: `${failedBuilds.length} failed build(s)`,
        description: `Stacks: ${[...new Set(failedBuilds.map(b => b.stack))].slice(0, 3).map(fmtStack).join(', ')}`,
        action: 'Investigate and fix failures'
      });
    }
    
    // 2. Warning: Unstable builds
    const unstableBuilds = allBuilds.filter(b => b.status === 'unstable');
    if (unstableBuilds.length > 0) {
      const uniqueStacks = [...new Set(unstableBuilds.map(b => b.stack))];
      actions.push({
        priority: 'warning',
        title: `${unstableBuilds.length} unstable build(s)`,
        description: `Flaky tests on ${uniqueStacks.slice(0, 2).map(fmtStack).join(', ')}${uniqueStacks.length > 2 ? '...' : ''}`,
        action: 'Review test stability'
      });
    }
    
    // 3. Info: Long-running builds (> 60 minutes average for regression)
    const longRunningStacks = executionTimes.filter(s => s.avgDuration > 60);
    if (longRunningStacks.length > 0) {
      actions.push({
        priority: 'info',
        title: `${longRunningStacks.length} slow stack(s)`,
        description: longRunningStacks.slice(0, 2).map(s => `${fmtStack(s.stack)}: ${s.avgDuration}m`).join(', '),
        action: 'Optimize test execution'
      });
    }
    
    // 4. Critical: Consecutive failures
    const consecutiveFailures = [];
    Object.entries(regressionByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      const builds = (stackInfo.allBuilds || []).sort((a, b) => (b.buildNumber || 0) - (a.buildNumber || 0));
      let consecutiveCount = 0;
      for (const build of builds) {
        if (build.status === 'failed' || build.status === 'aborted') {
          consecutiveCount++;
        } else {
          break;
        }
      }
      if (consecutiveCount >= 3) {
        consecutiveFailures.push({ stack, count: consecutiveCount });
      }
    });
    if (consecutiveFailures.length > 0) {
      actions.push({
        priority: 'critical',
        title: `${consecutiveFailures.length} stack(s) failing consecutively`,
        description: consecutiveFailures.slice(0, 2).map(s => `${fmtStack(s.stack)}: ${s.count}x`).join(', '),
        action: 'Urgent: Check infrastructure'
      });
    }
    
    // 5. Info: Rarely tested stacks
    const lowActivityStacks = [];
    Object.entries(regressionByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      const totalBuilds = (stackInfo.allBuilds || []).length;
      if (totalBuilds < 2) {
        lowActivityStacks.push({ stack, runs: totalBuilds });
      }
    });
    if (lowActivityStacks.length > 0) {
      actions.push({
        priority: 'info',
        title: `${lowActivityStacks.length} stack(s) rarely tested`,
        description: lowActivityStacks.slice(0, 3).map(s => `${fmtStack(s.stack)}: ${s.runs} run(s)`).join(', '),
        action: 'Increase test coverage'
      });
    }
    
    // 6. Warning: Low success rate stacks
    const lowSuccessStacks = stackSuccessRates.filter(s => s.successRate < 70 && s.total > 0);
    if (lowSuccessStacks.length > 0) {
      actions.push({
        priority: 'warning',
        title: `${lowSuccessStacks.length} stack(s) below 70%`,
        description: lowSuccessStacks.slice(0, 3).map(s => `${fmtStack(s.stack)}: ${s.successRate}%`).join(', '),
        action: 'Review test stability'
      });
    }
    
    // 7. Warning: Recurring failures
    if (recurring.length > 0) {
      actions.push({
        priority: 'warning',
        title: `${recurring.length} recurring issue(s)`,
        description: recurring[0]?.reason || 'Multiple failures detected',
        action: 'Address root cause'
      });
    }
    
    // Success: All healthy
    if (actions.length === 0) {
      actions.push({
        priority: 'success',
        title: 'All stacks healthy',
        description: `${regressionByStack.summary?.stacksList?.length || 0} stacks passing`,
        action: 'Continue monitoring'
      });
    }
    
    // Sort by priority
    const priorityOrder = { critical: 0, warning: 1, info: 2, success: 3 };
    actions.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);
    
    return actions;
  };

  // TFA handlers - using shared hook
  const openTFA = async (pipeline, buildNum) => {
    const jobName = pipeline.pipelineName || pipeline.name;
    setSelectedPipelineForTfa(pipeline);
    fetchTfa(jobName, buildNum, 'main'); // Use 'main' for regression pipelines
  };

  const closeTFA = () => {
    closeTfaModal();
    setSelectedPipelineForTfa(null);
  };

  // Loading state
  if (loading || !regressionByStack) {
    return (
      <div className="jenkins-section">
        <div className="section-page-header">
          <div className="header-left">
            <h1><Activity size={24} /> Jenkins Regression Pipelines</h1>
            <p>Backend Regression Runs by Stack</p>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: '60px 20px' }}>
          {error ? (
            <>
              <AlertCircle size={32} style={{ color: 'var(--accent-red)', marginBottom: '12px' }} />
              <span style={{ color: 'var(--text-secondary)' }}>{error}</span>
              <button 
                onClick={() => fetchRegressionByStack()}
                style={{ marginTop: '16px', padding: '8px 16px', borderRadius: '6px', border: 'none', background: 'var(--accent-blue)', color: 'white', cursor: 'pointer' }}
              >
                Retry
              </button>
            </>
          ) : (
            <>
              <Loader size={32} className="spin" />
              <span style={{ marginTop: '12px' }}>Loading regression pipeline data...</span>
            </>
          )}
        </div>
      </div>
    );
  }

  // Get sorted data
  const sortedStacks = regressionByStack.summary?.stacksList || [];
  const sortedPipelines = regressionByStack.summary?.pipelinesList || [];
  const stackMatrix = regressionByStack.stackMatrix || {};

  return (
    <div className="jenkins-section">
      {/* Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1><Activity size={24} /> Jenkins Regression Pipelines</h1>
          <p>Backend Regression Runs by Stack</p>
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
            href="http://jenkins03-int.stg01-mp.nc4.iad0.nsscloud.net:8080/view/Your-Product/"
            target="_blank"
            rel="noopener noreferrer"
            className="action-btn primary"
          >
            <ExternalLink size={16} /> Open in Jenkins
          </a>
        </div>
      </div>

      {/* ============ SUMMARY SECTION WITH ACTION ITEMS & RECENT ACTIVITY ============ */}
      {(() => {
        const actionItems = getActionItems();
        const hasCritical = actionItems.some(a => a.priority === 'critical');
        const allHealthy = actionItems.every(a => a.priority === 'success');
        
        return (
          <div style={{ marginBottom: '20px' }}>
            <div style={{ 
              background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)',
              padding: '16px', marginBottom: '16px'
            }}>
              {/* Top Row: Stats + Action Items */}
              <div style={{ display: 'flex', gap: '24px', marginBottom: '16px' }}>
                {/* Stats Cards - Matching Endpoint PDV style */}
                <div style={{ display: 'flex', gap: '12px', flexShrink: 0 }}>
                  <div 
                    style={{ 
                      background: 'linear-gradient(135deg, rgba(76, 175, 80, 0.12), rgba(76, 175, 80, 0.04))', 
                      border: '1px solid rgba(76, 175, 80, 0.2)',
                      borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '75px',
                      cursor: 'help'
                    }}
                    title={`${regressionByStack.summary?.overallPassRate || 0}% = ${regressionByStack.summary?.totalPassed || 0} passed / ${regressionByStack.summary?.totalRuns || 0} total runs`}
                  >
                    <div style={{ fontSize: '22px', fontWeight: '700', color: 'var(--accent-green)' }}>{regressionByStack.summary?.overallPassRate || 0}%</div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Success</div>
                  </div>
                  <div style={{ 
                    background: 'var(--bg-tertiary)', 
                    border: '1px solid var(--border-color)',
                    borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '65px'
                  }}>
                    <div style={{ fontSize: '22px', fontWeight: '700', color: 'var(--accent-blue)' }}>{regressionByStack.summary?.totalRuns || 0}</div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Runs</div>
                  </div>
                  <div style={{ 
                    background: (regressionByStack.summary?.totalFailed || 0) > 0 ? 'linear-gradient(135deg, rgba(244, 67, 54, 0.12), rgba(244, 67, 54, 0.04))' : 'var(--bg-tertiary)', 
                    border: `1px solid ${(regressionByStack.summary?.totalFailed || 0) > 0 ? 'rgba(244, 67, 54, 0.2)' : 'var(--border-color)'}`,
                    borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '65px'
                  }}>
                    <div style={{ fontSize: '22px', fontWeight: '700', color: (regressionByStack.summary?.totalFailed || 0) > 0 ? 'var(--accent-red)' : 'var(--text-muted)' }}>{regressionByStack.summary?.totalFailed || 0}</div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Failed</div>
                  </div>
                  <div style={{ 
                    background: 'var(--bg-tertiary)', 
                    border: '1px solid var(--border-color)',
                    borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '65px'
                  }}>
                    <div style={{ fontSize: '22px', fontWeight: '700', color: 'var(--accent-purple)' }}>{sortedStacks.length}</div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Stacks</div>
                  </div>
                  <div style={{ 
                    background: 'var(--bg-tertiary)', 
                    border: '1px solid var(--border-color)',
                    borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '65px',
                    cursor: 'help'
                  }}
                    title={Object.values(regressionByStack.byPipeline || {}).map(p => p.displayName || p.name).sort().join(', ')}
                  >
                    <div style={{ fontSize: '22px', fontWeight: '700', color: 'var(--text-secondary)' }}>{Object.keys(regressionByStack.byPipeline || {}).length}</div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Services</div>
                  </div>
                </div>
                
                {/* Action Items */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                    {allHealthy ? (
                      <CheckCircle size={16} style={{ color: 'var(--accent-green)' }} />
                    ) : hasCritical ? (
                      <AlertTriangle size={16} style={{ color: 'var(--accent-red)' }} />
                    ) : (
                      <AlertTriangle size={16} style={{ color: 'var(--accent-orange)' }} />
                    )}
                    <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                      Action Items
                    </span>
                    {!allHealthy && (
                      <span style={{ 
                        fontSize: '11px', padding: '3px 8px', borderRadius: '4px', 
                        background: hasCritical ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 193, 7, 0.15)',
                        color: hasCritical ? 'var(--accent-red)' : 'var(--accent-orange)',
                        fontWeight: '600'
                      }}>
                        {actionItems.filter(a => a.priority !== 'success').length} issues
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                    {actionItems.map((item, idx) => (
                      <div key={idx} style={{ 
                        display: 'flex', alignItems: 'center', gap: '8px', 
                        padding: '8px 12px', borderRadius: '8px',
                        background: item.priority === 'critical' ? 'rgba(244, 67, 54, 0.1)' :
                                   item.priority === 'warning' ? 'rgba(255, 193, 7, 0.1)' :
                                   item.priority === 'info' ? 'rgba(33, 150, 243, 0.1)' :
                                   'rgba(76, 175, 80, 0.1)',
                        border: `1px solid ${item.priority === 'critical' ? 'rgba(244, 67, 54, 0.3)' :
                                            item.priority === 'warning' ? 'rgba(255, 193, 7, 0.3)' :
                                            item.priority === 'info' ? 'rgba(33, 150, 243, 0.3)' :
                                            'rgba(76, 175, 80, 0.3)'}`
                      }}>
                        {item.priority === 'critical' && <XCircle size={14} style={{ color: 'var(--accent-red)' }} />}
                        {item.priority === 'warning' && <AlertTriangle size={14} style={{ color: 'var(--accent-orange)' }} />}
                        {item.priority === 'info' && <Info size={14} style={{ color: 'var(--accent-blue)' }} />}
                        {item.priority === 'success' && <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />}
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>{item.title}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{item.description}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              
              {/* Bottom Row: Recent Activity Timeline */}
              <div style={{ 
                borderTop: '1px solid var(--border-color)', paddingTop: '14px',
                display: 'flex', flexDirection: 'column'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                  <Clock size={16} style={{ color: 'var(--accent-blue)' }} />
                  <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                    Recent Activity
                  </span>
                </div>
                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                  {recentBuilds.slice(0, 30).map((build, idx) => (
                    <div 
                      key={`${build.pipelineKey}-${build.buildNumber}-${idx}`}
                      style={{
                        width: '28px', height: '28px', borderRadius: '4px', cursor: 'pointer',
                        background: build.status === 'success' ? 'var(--accent-green)' :
                                   build.status === 'failed' ? 'var(--accent-red)' :
                                   build.status === 'running' ? 'var(--accent-blue)' :
                                   build.status === 'unstable' ? 'var(--accent-orange)' : 'var(--text-muted)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: '9px', color: 'white', fontWeight: '600'
                      }}
                      title={`${build.pipelineKey?.toUpperCase() || 'Unknown'} on ${formatStackName(build.stack, regressionByStack?.byStack)}\n#${build.buildNumber} • ${build.timestamp}\nStatus: ${build.status?.toUpperCase()}\nDuration: ${build.duration || 'N/A'}`}
                      onClick={() => build.url && window.open(build.url, '_blank')}
                    >
                      {build.status === 'running' ? '⟳' : build.status === 'success' ? '✓' : build.status === 'failed' ? '✗' : '!'}
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: '16px', marginTop: '8px', fontSize: '11px', color: 'var(--text-muted)' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{ width: '10px', height: '10px', borderRadius: '2px', background: 'var(--accent-green)' }}></span> Passed
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{ width: '10px', height: '10px', borderRadius: '2px', background: 'var(--accent-red)' }}></span> Failed
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{ width: '10px', height: '10px', borderRadius: '2px', background: 'var(--accent-orange)' }}></span> Unstable
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{ width: '10px', height: '10px', borderRadius: '2px', background: 'var(--accent-blue)' }}></span> Running
                  </span>
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ============ ANALYSIS GRID (3 columns) ============ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', marginBottom: '20px' }}>
        {/* Stack Health Matrix */}
        <div style={{ 
          background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)',
          padding: '16px', display: 'flex', flexDirection: 'column'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <Server size={16} style={{ color: 'var(--accent-purple)' }} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>Stack Health Matrix</span>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <div style={{ flex: 1, overflowX: 'auto', maxHeight: '200px', overflowY: 'auto' }}>
              <table style={{ width: '100%', fontSize: '11px', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid var(--border-color)', position: 'sticky', top: 0, background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}>Stack</th>
                    {sortedPipelines.map(pKey => (
                      <th key={pKey} style={{ padding: '6px 4px', textAlign: 'center', borderBottom: '1px solid var(--border-color)', position: 'sticky', top: 0, background: 'var(--bg-secondary)', color: 'var(--text-muted)', fontSize: '9px' }}>
                        {pKey.substring(0, 2).toUpperCase()}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedStacks.map(stack => (
                    <tr key={stack}>
                      <td style={{ padding: '5px 8px', fontWeight: '500', color: 'var(--text-primary)', borderBottom: '1px solid var(--border-color)' }}>
                        {formatStackName(stack, regressionByStack?.byStack)}
                      </td>
                      {sortedPipelines.map(pKey => {
                        const status = stackMatrix.matrix?.[stack]?.[pKey];
                        return (
                          <td key={pKey} style={{ padding: '5px 4px', textAlign: 'center', borderBottom: '1px solid var(--border-color)' }}>
                            {status === 'success' && <span style={{ color: 'var(--accent-green)' }}>✓</span>}
                            {status === 'failed' && <span style={{ color: 'var(--accent-red)' }}>✗</span>}
                            {status === 'unstable' && <span style={{ color: 'var(--accent-orange)' }}>!</span>}
                            {status === 'running' && <span style={{ color: 'var(--accent-blue)' }}>⟳</span>}
                            {!status && <span style={{ color: 'var(--text-muted)' }}>-</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Legend */}
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', minWidth: '90px', paddingLeft: '8px', borderLeft: '1px solid var(--border-color)' }}>
              <div style={{ fontWeight: '600', marginBottom: '6px', color: 'var(--text-secondary)' }}>Legend</div>
              {sortedPipelines.map(pKey => (
                <div key={pKey} style={{ marginBottom: '3px' }}>
                  <strong>{pKey.substring(0, 2).toUpperCase()}</strong>: {stackMatrix.pipelineDisplayNames?.[pKey] || pKey}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Stack Success Rate */}
        <div style={{ 
          background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)',
          padding: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <TrendingUp size={16} style={{ color: 'var(--accent-green)' }} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>Stack Success Rate</span>
          </div>
          <div style={{ maxHeight: '180px', overflowY: 'auto' }}>
            {getStackSuccessRates().map((s, idx) => (
              <div key={s.stack} style={{ marginBottom: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <span style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-primary)' }}>{formatStackName(s.stack, regressionByStack?.byStack)}</span>
                  <span style={{ fontSize: '12px', color: s.successRate >= 80 ? 'var(--accent-green)' : s.successRate >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)', fontWeight: '600' }}>
                    {s.successRate}%
                  </span>
                </div>
                <div style={{ height: '8px', background: 'var(--bg-tertiary)', borderRadius: '4px', overflow: 'hidden' }}>
                  <div style={{ 
                    height: '100%', 
                    width: `${s.successRate}%`,
                    background: s.successRate >= 80 ? 'var(--accent-green)' : s.successRate >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)',
                    borderRadius: '4px',
                    transition: 'width 0.3s ease'
                  }}></div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Execution Time */}
        <div style={{ 
          background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)',
          padding: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <Timer size={16} style={{ color: 'var(--accent-cyan)' }} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>Execution Time</span>
          </div>
          <div style={{ maxHeight: '180px', overflowY: 'auto' }}>
            {getExecutionTimes().map((s, idx) => (
              <div key={s.stack} style={{ marginBottom: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <span style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-primary)' }}>{formatStackName(s.stack, regressionByStack?.byStack)}</span>
                  <span style={{ fontSize: '12px', color: s.avgDuration <= 45 ? 'var(--accent-green)' : s.avgDuration <= 90 ? 'var(--accent-orange)' : 'var(--accent-red)', fontWeight: '600' }}>
                    {s.avgDuration}m
                  </span>
                </div>
                <div style={{ height: '8px', background: 'var(--bg-tertiary)', borderRadius: '4px', overflow: 'hidden' }}>
                  <div style={{ 
                    height: '100%', 
                    width: `${Math.min((s.avgDuration / 120) * 100, 100)}%`,
                    background: s.avgDuration <= 45 ? 'var(--accent-green)' : s.avgDuration <= 90 ? 'var(--accent-orange)' : 'var(--accent-red)',
                    borderRadius: '4px'
                  }}></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ============ DETAILS GRID (2 columns) ============ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
        {/* Recent Failures */}
        <div style={{ 
          background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)',
          padding: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <XCircle size={16} style={{ color: 'var(--accent-red)' }} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>Recent Failures</span>
          </div>
          <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
            {getRecentFailures().length === 0 ? (
              <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-muted)', fontSize: '13px' }}>
                <CheckCircle size={24} style={{ color: 'var(--accent-green)', marginBottom: '8px' }} />
                <div>No recent failures</div>
              </div>
            ) : (
              getRecentFailures().map((build, idx) => (
                <div 
                  key={`${build.pipelineKey}-${build.buildNumber}-${idx}`}
                  style={{ 
                    display: 'flex', alignItems: 'center', gap: '10px', padding: '10px',
                    background: 'var(--bg-tertiary)', borderRadius: '8px', marginBottom: '8px'
                  }}
                >
                  <XCircle size={16} style={{ color: 'var(--accent-red)', flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {stackMatrix.pipelineDisplayNames?.[build.pipelineKey] || build.pipelineKey} - {formatStackName(build.stack, regressionByStack?.byStack)}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      #{build.buildNumber} • {build.timestamp} • {build.duration || 'N/A'}
                    </div>
                  </div>
                  <button
                    onClick={() => openTFA(build, build.buildNumber)}
                    style={{
                      padding: '4px 8px', borderRadius: '4px', border: 'none',
                      background: 'rgba(244, 67, 54, 0.15)', color: 'var(--accent-red)',
                      fontSize: '10px', fontWeight: '600', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', gap: '4px',
                      flexShrink: 0
                    }}
                    title="Analyze test failures"
                  >
                    <Bug size={12} /> Analyze
                  </button>
                  <ExternalLink 
                    size={14} 
                    style={{ color: 'var(--text-muted)', cursor: 'pointer', flexShrink: 0 }}
                    onClick={() => build.url && window.open(build.url, '_blank')}
                  />
                </div>
              ))
            )}
          </div>
        </div>

        {/* Failure Reasons */}
        <div style={{ 
          background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)',
          padding: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <Bug size={16} style={{ color: 'var(--accent-orange)' }} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>Failure Reasons</span>
          </div>
          <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
            {(() => {
              const { reasons } = getFailureReasons();
              if (reasons.length === 0) {
                return (
                  <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-muted)', fontSize: '13px' }}>
                    <CheckCircle size={24} style={{ color: 'var(--accent-green)', marginBottom: '8px' }} />
                    <div>No failures to analyze</div>
                  </div>
                );
              }
              return reasons.map((r, idx) => (
                <div key={idx} style={{ 
                  display: 'flex', alignItems: 'center', gap: '10px', padding: '10px',
                  background: 'var(--bg-tertiary)', borderRadius: '8px', marginBottom: '8px'
                }}>
                  <div style={{ 
                    width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
                    background: r.count >= 3 ? 'var(--accent-red)' : r.count >= 2 ? 'var(--accent-orange)' : 'var(--accent-yellow)'
                  }}></div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
                      {stackMatrix.pipelineDisplayNames?.[r.reason] || r.reason}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {r.count} failure(s) on {r.stacks.slice(0, 3).map(s => formatStackName(s, regressionByStack?.byStack)).join(', ')}
                    </div>
                  </div>
                  <span style={{ 
                    fontSize: '11px', fontWeight: '600', padding: '3px 8px', borderRadius: '4px',
                    background: r.count >= 3 ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 193, 7, 0.15)',
                    color: r.count >= 3 ? 'var(--accent-red)' : 'var(--accent-orange)'
                  }}>
                    {r.count}x
                  </span>
                </div>
              ));
            })()}
          </div>
        </div>
      </div>

      {/* ============ VIEW BY TOGGLE ============ */}
      <div style={{ 
        display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '16px',
        padding: '12px 16px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)'
      }}>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setRegressionGroupBy('stack')}
            style={{
              padding: '8px 16px', borderRadius: '6px', border: 'none', cursor: 'pointer',
              background: regressionGroupBy === 'stack' ? 'var(--accent-blue)' : 'var(--bg-tertiary)',
              color: regressionGroupBy === 'stack' ? 'white' : 'var(--text-secondary)',
              fontSize: '13px', fontWeight: '500', display: 'flex', alignItems: 'center', gap: '6px'
            }}
          >
            <Server size={14} /> By Stack
          </button>
          <button
            onClick={() => setRegressionGroupBy('pipeline')}
            style={{
              padding: '8px 16px', borderRadius: '6px', border: 'none', cursor: 'pointer',
              background: regressionGroupBy === 'pipeline' ? 'var(--accent-blue)' : 'var(--bg-tertiary)',
              color: regressionGroupBy === 'pipeline' ? 'white' : 'var(--text-secondary)',
              fontSize: '13px', fontWeight: '500', display: 'flex', alignItems: 'center', gap: '6px'
            }}
          >
            <Layers size={14} /> By Pipeline
          </button>
        </div>
        
        {regressionGroupBy === 'stack' && (
          <select
            value={selectedStackFilter}
            onChange={(e) => setSelectedStackFilter(e.target.value)}
            style={{
              padding: '8px 12px', borderRadius: '6px', border: '1px solid var(--border-color)',
              background: 'var(--bg-tertiary)', color: 'var(--text-primary)', fontSize: '13px'
            }}
          >
            <option value="all">All Stacks</option>
            {sortedStacks.map(stack => (
              <option key={stack} value={stack}>{formatStackName(stack, regressionByStack?.byStack)}</option>
            ))}
          </select>
        )}
      </div>

      {/* ============ VIEW BY STACK ============ */}
      {regressionGroupBy === 'stack' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {Object.entries(regressionByStack.byStack || {})
            .filter(([stack]) => selectedStackFilter === 'all' || stack === selectedStackFilter)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([stackName, stackData]) => {
              const isStackExpanded = expandedStacks[stackName] !== false;
              const pipelines = Object.entries(stackData.pipelines || {});
              const stackSummary = stackData.summary || {};
              
              return (
                <div key={stackName} style={{ 
                  background: 'var(--bg-secondary)', borderRadius: '12px', 
                  border: `1px solid ${stackSummary.failed > 0 ? 'rgba(244, 67, 54, 0.3)' : 'var(--border-color)'}`,
                  overflow: 'hidden'
                }}>
                  {/* Stack Header */}
                  <div 
                    onClick={() => setExpandedStacks(prev => ({ ...prev, [stackName]: !isStackExpanded }))}
                    style={{ 
                      padding: '14px 18px', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      background: stackSummary.failed > 0 ? 'rgba(244, 67, 54, 0.05)' : 'var(--bg-tertiary)'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      {isStackExpanded ? <ChevronDown size={18} /> : <ChevronUp size={18} style={{ transform: 'rotate(180deg)' }} />}
                      <Server size={18} style={{ color: 'var(--accent-purple)' }} />
                      <span style={{ fontSize: '16px', fontWeight: '600' }}>{formatStackName(stackName, regressionByStack?.byStack)}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                        {stackSummary.passed}/{stackSummary.total} Passing
                      </span>
                      <div 
                        style={{ 
                          padding: '4px 12px', borderRadius: '6px', fontSize: '13px', fontWeight: '600',
                          background: stackSummary.passRate >= 80 ? 'rgba(76, 175, 80, 0.15)' : 
                                     stackSummary.passRate >= 50 ? 'rgba(255, 193, 7, 0.15)' : 'rgba(244, 67, 54, 0.15)',
                          color: stackSummary.passRate >= 80 ? 'var(--accent-green)' : 
                                 stackSummary.passRate >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)',
                          cursor: 'help'
                        }}
                        title={`${stackSummary.passRate}% = ${stackSummary.passed} passed / ${stackSummary.total} total runs`}
                      >
                        {stackSummary.passRate || 0}%
                      </div>
                    </div>
                  </div>

                  {/* Stack Content */}
                  {isStackExpanded && (
                    <div style={{ padding: '16px' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                            <th style={{ textAlign: 'left', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Pipeline</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Status</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Build #</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Duration</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Last Run</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>History</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pipelines.map(([pKey, pInfo], idx) => {
                            const latestBuild = pInfo.latestBuild;
                            const builds = pInfo.builds || [];
                            return (
                              <tr key={idx} style={{ borderBottom: '1px solid var(--border-color)' }}>
                                <td style={{ padding: '12px', fontSize: '13px', fontWeight: '500' }}>{pInfo.displayName}</td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  {pInfo.latestStatus === 'success' && <CheckCircle size={18} style={{ color: 'var(--accent-green)' }} />}
                                  {pInfo.latestStatus === 'failed' && <XCircle size={18} style={{ color: 'var(--accent-red)' }} />}
                                  {pInfo.latestStatus === 'unstable' && <AlertTriangle size={18} style={{ color: 'var(--accent-orange)' }} />}
                                  {pInfo.latestStatus === 'running' && <Loader size={18} style={{ color: 'var(--accent-blue)' }} className="spin" />}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  #{latestBuild?.buildNumber || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  {latestBuild?.duration || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  {latestBuild?.timestamp || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  <div style={{ display: 'flex', gap: '4px', justifyContent: 'center', flexWrap: 'wrap' }}>
                                    {builds.slice(0, 5).map((b, i) => (
                                      <div 
                                        key={i}
                                        style={{
                                          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
                                          padding: '4px', borderRadius: '4px',
                                          background: b.status === 'success' ? 'rgba(76, 175, 80, 0.15)' :
                                                     b.status === 'failed' ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 152, 0, 0.15)',
                                          border: `1px solid ${b.status === 'success' ? 'var(--accent-green)' :
                                                  b.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'}`,
                                          minWidth: '36px'
                                        }}
                                      >
                                        <div 
                                          style={{ 
                                            fontSize: '9px', fontWeight: '600', cursor: 'pointer',
                                            color: b.status === 'success' ? 'var(--accent-green)' :
                                                   b.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'
                                          }}
                                          title={`#${b.buildNumber} - ${b.status} - Click to open in Jenkins`}
                                          onClick={() => b.url && window.open(b.url, '_blank')}
                                        >
                                          #{b.buildNumber}
                                        </div>
                                        {(b.status === 'failed' || b.status === 'unstable' || b.status === 'aborted') && (
                                          <button
                                            onClick={(e) => { e.stopPropagation(); openTFA({ pipelineName: pInfo.displayName || pKey, ...b }, b.buildNumber); }}
                                            style={{
                                              padding: '2px 4px', borderRadius: '3px', border: 'none',
                                              background: 'rgba(244, 67, 54, 0.2)', color: 'var(--accent-red)',
                                              fontSize: '8px', fontWeight: '600', cursor: 'pointer',
                                              display: 'flex', alignItems: 'center', gap: '2px'
                                            }}
                                            title="Analyze test failures"
                                          >
                                            <Bug size={8} /> TFA
                                          </button>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      )}

      {/* ============ VIEW BY PIPELINE ============ */}
      {regressionGroupBy === 'pipeline' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {Object.entries(regressionByStack.byPipeline || {})
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([pipelineKey, pipelineData]) => {
              const isPipelineExpanded = expandedPipelines[pipelineKey] !== false;
              const stacks = Object.entries(pipelineData.stacks || {});
              const pipelineSummary = pipelineData.summary || {};
              
              return (
                <div key={pipelineKey} style={{ 
                  background: 'var(--bg-secondary)', borderRadius: '12px', 
                  border: `1px solid ${pipelineSummary.failingStacks > 0 ? 'rgba(244, 67, 54, 0.3)' : 'var(--border-color)'}`,
                  overflow: 'hidden'
                }}>
                  {/* Pipeline Header */}
                  <div 
                    onClick={() => setExpandedPipelines(prev => ({ ...prev, [pipelineKey]: !isPipelineExpanded }))}
                    style={{ 
                      padding: '14px 18px', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      background: pipelineSummary.failingStacks > 0 ? 'rgba(244, 67, 54, 0.05)' : 'var(--bg-tertiary)'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      {isPipelineExpanded ? <ChevronDown size={18} /> : <ChevronUp size={18} style={{ transform: 'rotate(180deg)' }} />}
                      <Layers size={18} style={{ color: 'var(--accent-blue)' }} />
                      <span style={{ fontSize: '16px', fontWeight: '600' }}>{pipelineData.displayName}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                        {pipelineSummary.passingStacks}/{pipelineSummary.totalStacks} Stacks Passing
                      </span>
                      <div 
                        style={{ 
                          padding: '4px 12px', borderRadius: '6px', fontSize: '13px', fontWeight: '600',
                          background: pipelineSummary.passRate >= 80 ? 'rgba(76, 175, 80, 0.15)' : 
                                     pipelineSummary.passRate >= 50 ? 'rgba(255, 193, 7, 0.15)' : 'rgba(244, 67, 54, 0.15)',
                          color: pipelineSummary.passRate >= 80 ? 'var(--accent-green)' : 
                                 pipelineSummary.passRate >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)',
                          cursor: 'help'
                        }}
                        title={`${pipelineSummary.passRate}% = ${pipelineSummary.passed || 0} passed / ${pipelineSummary.total || 0} total runs`}
                      >
                        {pipelineSummary.passRate || 0}%
                      </div>
                    </div>
                  </div>

                  {/* Pipeline Content */}
                  {isPipelineExpanded && (
                    <div style={{ padding: '16px' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                            <th style={{ textAlign: 'left', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Stack</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Status</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Build #</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Duration</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Last Run</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>History</th>
                          </tr>
                        </thead>
                        <tbody>
                          {stacks.map(([stackName, stackInfo], idx) => {
                            const latestBuild = stackInfo.latestBuild;
                            const builds = stackInfo.builds || [];
                            return (
                              <tr key={idx} style={{ borderBottom: '1px solid var(--border-color)' }}>
                                <td style={{ padding: '12px', fontSize: '13px', fontWeight: '600' }}>{formatStackName(stackName, regressionByStack?.byStack)}</td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  {stackInfo.latestStatus === 'success' && <CheckCircle size={18} style={{ color: 'var(--accent-green)' }} />}
                                  {stackInfo.latestStatus === 'failed' && <XCircle size={18} style={{ color: 'var(--accent-red)' }} />}
                                  {stackInfo.latestStatus === 'unstable' && <AlertTriangle size={18} style={{ color: 'var(--accent-orange)' }} />}
                                  {stackInfo.latestStatus === 'running' && <Loader size={18} style={{ color: 'var(--accent-blue)' }} className="spin" />}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  #{latestBuild?.buildNumber || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  {latestBuild?.duration || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  {latestBuild?.timestamp || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  <div style={{ display: 'flex', gap: '4px', justifyContent: 'center', flexWrap: 'wrap' }}>
                                    {builds.slice(0, 5).map((b, i) => (
                                      <div 
                                        key={i}
                                        style={{
                                          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
                                          padding: '4px', borderRadius: '4px',
                                          background: b.status === 'success' ? 'rgba(76, 175, 80, 0.15)' :
                                                     b.status === 'failed' ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 152, 0, 0.15)',
                                          border: `1px solid ${b.status === 'success' ? 'var(--accent-green)' :
                                                  b.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'}`,
                                          minWidth: '36px'
                                        }}
                                      >
                                        <div 
                                          style={{ 
                                            fontSize: '9px', fontWeight: '600', cursor: 'pointer',
                                            color: b.status === 'success' ? 'var(--accent-green)' :
                                                   b.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'
                                          }}
                                          title={`#${b.buildNumber} - ${b.status} - Click to open in Jenkins`}
                                          onClick={() => b.url && window.open(b.url, '_blank')}
                                        >
                                          #{b.buildNumber}
                                        </div>
                                        {(b.status === 'failed' || b.status === 'unstable' || b.status === 'aborted') && (
                                          <button
                                            onClick={(e) => { e.stopPropagation(); openTFA({ pipelineName: pipelineData.displayName || pipelineKey, ...b }, b.buildNumber); }}
                                            style={{
                                              padding: '2px 4px', borderRadius: '3px', border: 'none',
                                              background: 'rgba(244, 67, 54, 0.2)', color: 'var(--accent-red)',
                                              fontSize: '8px', fontWeight: '600', cursor: 'pointer',
                                              display: 'flex', alignItems: 'center', gap: '2px'
                                            }}
                                            title="Analyze test failures"
                                          >
                                            <Bug size={8} /> TFA
                                          </button>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      )}

      {/* TFA Modal - Using shared component */}
      <TfaModal
        isOpen={tfaModalOpen}
        onClose={closeTFA}
        loading={tfaLoading}
        data={tfaData}
        error={tfaError}
        selectedPipeline={selectedPipelineForTfa}
        buildNumber={selectedBuild?.buildNumber}
      />
    </div>
  );
};

export default JenkinsSection;
