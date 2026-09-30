/**
 * Shared Pipeline Components
 * 
 * Reusable components for pipeline monitoring across Dev, PDV, and Regression sections.
 * Reduces code duplication and ensures consistent UI/UX.
 */
import React, { useState } from 'react';
import {
  CheckCircle,
  XCircle,
  AlertCircle,
  AlertTriangle,
  Clock,
  Loader,
  X,
  Zap,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  FileText,
  ExternalLink,
  Layers
} from 'lucide-react';

/**
 * Parse recommendations into clean bullet points
 * Handles cases where recommendations come as a single string with embedded numbering
 */
const parseRecommendations = (recommendations) => {
  if (!recommendations) return [];
  
  // If already an array, process each item
  if (Array.isArray(recommendations)) {
    const parsed = [];
    recommendations.forEach(rec => {
      // If a single recommendation is very long (>200 chars) and contains numbered items, split it
      if (typeof rec === 'string' && rec.length > 200 && /\d+\.\s*\*?\*?[A-Z]/.test(rec)) {
        // Split by numbered patterns like "1. ", "2) ", etc.
        const parts = rec.split(/(?=\d+\.\s*\*?\*?[A-Z])|(?=\d+\)\s*[A-Z])/).filter(p => p.trim());
        parts.forEach(part => {
          const cleaned = cleanRecommendation(part);
          if (cleaned) parsed.push(cleaned);
        });
      } else {
        const cleaned = cleanRecommendation(rec);
        if (cleaned) parsed.push(cleaned);
      }
    });
    return parsed.slice(0, 10); // Limit to 10 items
  }
  
  // If it's a single string, try to split it
  if (typeof recommendations === 'string') {
    const parts = recommendations.split(/(?=\d+\.\s*\*?\*?)|(?=\d+\)\s*)|\n+/).filter(p => p.trim());
    return parts.map(cleanRecommendation).filter(Boolean).slice(0, 10);
  }
  
  return [];
};

/**
 * Clean a single recommendation string
 */
const cleanRecommendation = (rec) => {
  if (!rec || typeof rec !== 'string') return '';
  
  let cleaned = rec.trim();
  
  // Remove leading numbering like "1. ", "1) ", "- ", "* "
  cleaned = cleaned.replace(/^\d+[\.\)]\s*/, '');
  cleaned = cleaned.replace(/^[-*•]\s*/, '');
  
  // Remove markdown bold markers
  cleaned = cleaned.replace(/\*\*([^*]+)\*\*/g, '$1');
  
  // Remove leading/trailing colons
  cleaned = cleaned.replace(/^:\s*/, '').replace(/\s*:$/, '');
  
  // Skip very short or header-only items
  if (cleaned.length < 5) return '';
  if (/^(fix|steps?|recommendations?|solution)$/i.test(cleaned)) return '';
  
  // Capitalize first letter
  if (cleaned && cleaned[0] === cleaned[0].toLowerCase()) {
    cleaned = cleaned[0].toUpperCase() + cleaned.slice(1);
  }
  
  return cleaned;
};

/**
 * Get status info (icon, color, label) for a pipeline/build status
 */
export const getStatusInfo = (status) => {
  switch (status) {
    case 'success':
    case 'SUCCESS':
      return { icon: <CheckCircle size={16} />, color: 'var(--accent-green)', label: 'Success' };
    case 'failed':
    case 'FAILURE':
      return { icon: <XCircle size={16} />, color: 'var(--accent-red)', label: 'Failed' };
    case 'unstable':
    case 'UNSTABLE':
      return { icon: <AlertTriangle size={16} />, color: 'var(--accent-orange)', label: 'Unstable' };
    case 'running':
    case 'RUNNING':
      return { icon: <Loader size={16} className="spin" />, color: 'var(--accent-blue)', label: 'Running' };
    case 'aborted':
    case 'ABORTED':
      return { icon: <AlertCircle size={16} />, color: 'var(--text-muted)', label: 'Aborted' };
    default:
      return { icon: <Clock size={16} />, color: 'var(--text-muted)', label: 'Unknown' };
  }
};

/**
 * Status Badge Component
 */
export const StatusBadge = ({ status, size = 'medium' }) => {
  const statusInfo = getStatusInfo(status);
  const padding = size === 'small' ? '4px 8px' : '6px 12px';
  const fontSize = size === 'small' ? '11px' : '13px';
  
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      padding,
      borderRadius: '6px',
      background: `${statusInfo.color}20`,
      color: statusInfo.color,
      fontSize,
      fontWeight: '600'
    }}>
      {statusInfo.icon}
      <span>{statusInfo.label}</span>
    </div>
  );
};

/**
 * Build History Squares Component
 * Displays recent builds as clickable colored squares with inline analyze buttons for failed builds
 */
export const BuildHistory = ({ 
  builds = [], 
  maxBuilds = 10, 
  onBuildClick,
  onAnalyzeClick,
  showTfaHint = true 
}) => {
  return (
    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
      {builds.slice(0, maxBuilds).map((build, idx) => {
        const canAnalyze = build.status === 'failed' || build.status === 'unstable';
        const statusInfo = getStatusInfo(build.status);
        
        return (
          <div
            key={`${build.buildNumber}-${idx}`}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '3px'
            }}
          >
            {/* Build Square */}
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '4px',
                cursor: 'pointer',
                background: statusInfo.color,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '10px',
                color: 'white',
                fontWeight: '600',
                border: canAnalyze ? '2px solid rgba(255,255,255,0.4)' : 'none',
                boxShadow: canAnalyze ? '0 0 8px rgba(0,0,0,0.3)' : 'none',
                transition: 'transform 0.1s ease'
              }}
              title={`#${build.buildNumber} - ${build.status?.toUpperCase()}\n${build.timestamp || ''}\nDuration: ${build.duration || 'N/A'}\nClick to open in Jenkins`}
              onClick={(e) => onBuildClick && onBuildClick(build, canAnalyze, e)}
              onMouseOver={(e) => e.currentTarget.style.transform = 'scale(1.1)'}
              onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1)'}
            >
              {build.status === 'running' ? '...' :
               build.status === 'success' ? '✓' :
               build.status === 'failed' ? '✗' : '!'}
            </div>
            {/* Small Analyze Button for failed/unstable builds */}
            {canAnalyze && onAnalyzeClick && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onAnalyzeClick(build);
                }}
                style={{
                  padding: '2px 6px',
                  borderRadius: '3px',
                  border: 'none',
                  background: 'linear-gradient(135deg, #9c27b0, #7b1fa2)',
                  color: 'white',
                  fontSize: '8px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '2px',
                  boxShadow: '0 1px 3px rgba(156, 39, 176, 0.3)'
                }}
                title={`Analyze build #${build.buildNumber}`}
              >
                <Zap size={8} /> TFA
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
};

/**
 * Analyze Button Component
 */
export const AnalyzeButton = ({ onClick, size = 'medium', disabled = false, isCached = false }) => {
  const padding = size === 'small' ? '4px 10px' : '6px 12px';
  const fontSize = size === 'small' ? '11px' : '12px';
  const iconSize = size === 'small' ? 12 : 14;
  
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        padding,
        borderRadius: '6px',
        border: 'none',
        background: disabled ? 'var(--bg-tertiary)' : 'linear-gradient(135deg, var(--accent-purple), #8b5cf6)',
        color: disabled ? 'var(--text-muted)' : 'white',
        fontSize,
        fontWeight: '600',
        cursor: disabled ? 'not-allowed' : 'pointer',
        boxShadow: disabled ? 'none' : '0 2px 8px rgba(139, 92, 246, 0.3)',
        transition: 'transform 0.1s ease, box-shadow 0.1s ease'
      }}
      title={isCached ? "Analysis ready - instant load" : "Run Test Failure Analysis"}
      onMouseOver={(e) => !disabled && (e.currentTarget.style.transform = 'translateY(-1px)')}
      onMouseOut={(e) => !disabled && (e.currentTarget.style.transform = 'translateY(0)')}
    >
      <Zap size={iconSize} /> Analyze
      {isCached && (
        <span style={{
          fontSize: '9px',
          padding: '1px 4px',
          borderRadius: '3px',
          background: 'rgba(255,255,255,0.25)',
          marginLeft: '2px'
        }}>⚡</span>
      )}
    </button>
  );
};

/**
 * Get severity color for TFA results
 */
export const getSeverityColor = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'high':
    case 'critical':
      return 'var(--accent-red)';
    case 'medium':
      return 'var(--accent-orange)';
    case 'low':
      return 'var(--accent-yellow)';
    default:
      return 'var(--text-muted)';
  }
};

/**
 * TFA Modal Component
 * Reusable modal for displaying Test Failure Analysis results
 */
export const TfaModal = ({
  isOpen,
  onClose,
  loading,
  error,
  data,
  selectedBuild, // { jobName, buildNumber, displayName } - from useTfa hook
  selectedPipeline, // Alternative: pipeline object - for backward compatibility
  buildNumber // Alternative: build number - for backward compatibility
}) => {
  const [expandedTests, setExpandedTests] = useState({});
  
  // Normalize the build info - support both prop patterns
  const buildInfo = selectedBuild || {
    displayName: selectedPipeline?.name || selectedPipeline?.displayName || selectedPipeline?.pipelineName,
    jobName: selectedPipeline?.fullName || selectedPipeline?.name,
    buildNumber: buildNumber || selectedPipeline?.buildNumber
  };

  const toggleTestExpand = (testName) => {
    setExpandedTests(prev => ({
      ...prev,
      [testName]: !prev[testName]
    }));
  };

  if (!isOpen) return null;

  return (
    <div 
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '20px'
      }}
      onClick={onClose}
    >
      <div 
        style={{
          background: 'var(--bg-primary)',
          borderRadius: '16px',
          border: '1px solid var(--border-color)',
          maxWidth: '900px',
          width: '100%',
          maxHeight: '85vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-secondary)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <Zap size={24} style={{ color: 'var(--accent-purple)' }} />
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <h2 style={{ margin: 0, fontSize: '18px', color: 'var(--text-primary)' }}>
                  Test Failure Analysis (TFA)
                </h2>
                {data?.cached && (
                  <span style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: 'rgba(76, 175, 80, 0.15)',
                    color: 'var(--accent-green)',
                    fontWeight: '600',
                    textTransform: 'uppercase'
                  }}>
                    Cached
                  </span>
                )}
              </div>
              <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                {buildInfo?.displayName || buildInfo?.jobName || data?.job} - Build #{buildInfo?.buildNumber || data?.buildNumber}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: '8px',
              borderRadius: '8px',
              display: 'flex',
              color: 'var(--text-muted)'
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Modal Body */}
        <div style={{ flex: 1, overflow: 'auto', padding: '24px' }}>
          {loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '40px 20px' }}>
              <div style={{ 
                width: '64px', 
                height: '64px', 
                borderRadius: '50%',
                background: 'linear-gradient(135deg, rgba(124, 92, 219, 0.15), rgba(124, 92, 219, 0.05))',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '20px'
              }}>
                <Loader size={32} className="spin" style={{ color: 'var(--accent-purple)' }} />
              </div>
              <p style={{ 
                margin: '0 0 8px 0', 
                fontSize: '16px',
                fontWeight: '600',
                color: 'var(--text-primary)', 
                textAlign: 'center' 
              }}>
                Analyzing Build Failures
              </p>
              <p style={{ 
                margin: '0 0 24px 0', 
                fontSize: '13px', 
                color: 'var(--text-muted)', 
                textAlign: 'center' 
              }}>
                This may take 10-30 seconds for AI analysis
              </p>
              
              {/* Progress Steps */}
              <div style={{ 
                display: 'flex', 
                flexDirection: 'column', 
                gap: '12px',
                width: '100%',
                maxWidth: '300px'
              }}>
                <div className="tfa-loading-step active" style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '10px 14px',
                  background: 'rgba(124, 92, 219, 0.08)',
                  borderRadius: '8px',
                  border: '1px solid rgba(124, 92, 219, 0.2)'
                }}>
                  <div style={{ 
                    width: '20px', 
                    height: '20px', 
                    borderRadius: '50%', 
                    background: 'var(--accent-purple)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}>
                    <Loader size={12} className="spin" style={{ color: 'white' }} />
                  </div>
                  <span style={{ fontSize: '13px', color: 'var(--text-primary)' }}>Fetching build data & console output</span>
                </div>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '10px 14px',
                  background: 'var(--bg-secondary)',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  opacity: 0.6
                }}>
                  <div style={{ 
                    width: '20px', 
                    height: '20px', 
                    borderRadius: '50%', 
                    background: 'var(--bg-tertiary)',
                    border: '2px solid var(--border)'
                  }} />
                  <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Searching knowledge base</span>
                </div>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '10px 14px',
                  background: 'var(--bg-secondary)',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  opacity: 0.6
                }}>
                  <div style={{ 
                    width: '20px', 
                    height: '20px', 
                    borderRadius: '50%', 
                    background: 'var(--bg-tertiary)',
                    border: '2px solid var(--border)'
                  }} />
                  <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Running AI analysis</span>
                </div>
              </div>
              
              <p style={{ 
                marginTop: '24px', 
                fontSize: '11px', 
                color: 'var(--text-muted)', 
                textAlign: 'center',
                fontStyle: 'italic'
              }}>
                💡 Tip: Results are cached for faster access next time
              </p>
            </div>
          )}

          {error && (
            <div style={{
              background: 'rgba(244, 67, 54, 0.1)',
              border: '1px solid rgba(244, 67, 54, 0.3)',
              borderRadius: '8px',
              padding: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '12px'
            }}>
              <AlertCircle size={20} style={{ color: 'var(--accent-red)' }} />
              <span style={{ color: 'var(--accent-red)' }}>{error}</span>
            </div>
          )}

          {data && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {/* Test Summary - hide for Dev pipelines (build_changes) since they have no tests */}
              {data.analysisType !== 'build_changes' && (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: '12px'
                }}>
                  <SummaryCard label="Total Tests" value={data.summary?.totalTests || 0} />
                  <SummaryCard label="Passed" value={data.summary?.passed || 0} color="var(--accent-green)" />
                  <SummaryCard label="Failed" value={data.summary?.failed || 0} color="var(--accent-red)" />
                  <SummaryCard label="Skipped" value={data.summary?.skipped || 0} />
                </div>
              )}

              {/* Failure Clusters - Grouped view of failures by category */}
              {data.failureClusters && data.failureClusters.length > 0 && (
                <div>
                  <h3 style={{ 
                    fontSize: '14px', 
                    fontWeight: '600', 
                    color: 'var(--text-secondary)',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}>
                    <Layers size={16} style={{ color: 'var(--accent-purple)' }} />
                    Failure Clusters
                    <span style={{ 
                      fontSize: '11px', 
                      color: 'var(--text-muted)', 
                      fontWeight: '400',
                      marginLeft: '4px'
                    }}>
                      ({data.failureClusters.length} {data.failureClusters.length === 1 ? 'pattern' : 'patterns'} detected)
                    </span>
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {data.failureClusters.map((cluster, idx) => (
                      <FailureClusterCard 
                        key={idx} 
                        cluster={cluster} 
                        isExpanded={expandedTests[`cluster-${idx}`]}
                        onToggle={() => toggleTestExpand(`cluster-${idx}`)}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Root Causes - Only show if no clusters (fallback) */}
              {(!data.failureClusters || data.failureClusters.length === 0) && data.rootCauses && data.rootCauses.length > 0 && (
                <div>
                  <h3 style={{ 
                    fontSize: '14px', 
                    fontWeight: '600', 
                    color: 'var(--text-secondary)',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}>
                    <AlertTriangle size={16} style={{ color: 'var(--accent-orange)' }} />
                    Root Causes Identified
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {data.rootCauses.map((cause, idx) => (
                      <RootCauseCard key={idx} cause={cause} />
                    ))}
                  </div>
                </div>
              )}

              {/* Recommendations */}
              {data.recommendations && data.recommendations.length > 0 && (
                <div>
                  <h3 style={{ 
                    fontSize: '14px', 
                    fontWeight: '600', 
                    color: 'var(--text-secondary)',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}>
                    <CheckCircle size={16} style={{ color: 'var(--accent-green)' }} />
                    Recommendations
                  </h3>
                  <div style={{
                    background: 'linear-gradient(135deg, rgba(76, 175, 80, 0.08), rgba(76, 175, 80, 0.03))',
                    borderRadius: '10px',
                    padding: '16px',
                    border: '1px solid rgba(76, 175, 80, 0.2)'
                  }}>
                    {data.recommendations.map((rec, idx) => {
                      // Parse recommendation text - handle markdown-style numbered lists
                      const lines = rec.split(/\n/).filter(l => l.trim());
                      const parsedItems = [];
                      
                      lines.forEach((line, lineIdx) => {
                        // Clean up markdown formatting
                        let cleanLine = line
                          .replace(/^\d+\.\s*\*\*([^*]+)\*\*:?\s*/g, '$1: ') // "1. **Text**:" -> "Text: "
                          .replace(/\*\*([^*]+)\*\*/g, '$1') // Remove **bold** markers
                          .replace(/^\s*[-•]\s*/, '') // Remove bullet points
                          .replace(/^\d+\.\s*/, '') // Remove numbered list markers
                          .trim();
                        
                        if (cleanLine) {
                          parsedItems.push(cleanLine);
                        }
                      });
                      
                      // If parsing resulted in multiple items, show them as sub-points
                      if (parsedItems.length > 1) {
                        return (
                          <div key={idx} style={{ marginBottom: idx < data.recommendations.length - 1 ? '12px' : 0 }}>
                            {parsedItems.map((item, itemIdx) => (
                              <div 
                                key={itemIdx}
                                style={{
                                  display: 'flex',
                                  alignItems: 'flex-start',
                                  gap: '10px',
                                  padding: '8px 12px',
                                  background: itemIdx % 2 === 0 ? 'rgba(255,255,255,0.5)' : 'transparent',
                                  borderRadius: '6px',
                                  marginBottom: '4px'
                                }}
                              >
                                <span style={{
                                  minWidth: '20px',
                                  height: '20px',
                                  borderRadius: '50%',
                                  background: 'var(--accent-green)',
                                  color: 'white',
                                  fontSize: '11px',
                                  fontWeight: '600',
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  flexShrink: 0
                                }}>
                                  {itemIdx + 1}
                                </span>
                                <span style={{ 
                                  color: 'var(--text-primary)', 
                                  fontSize: '13px', 
                                  lineHeight: '1.5' 
                                }}>
                                  {item}
                                </span>
                              </div>
                            ))}
                          </div>
                        );
                      }
                      
                      // Single item recommendation
                      return (
                        <div 
                          key={idx}
                          style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '10px',
                            padding: '8px 12px',
                            background: idx % 2 === 0 ? 'rgba(255,255,255,0.5)' : 'transparent',
                            borderRadius: '6px',
                            marginBottom: idx < data.recommendations.length - 1 ? '4px' : 0
                          }}
                        >
                          <span style={{
                            minWidth: '20px',
                            height: '20px',
                            borderRadius: '50%',
                            background: 'var(--accent-green)',
                            color: 'white',
                            fontSize: '11px',
                            fontWeight: '600',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            flexShrink: 0
                          }}>
                            {idx + 1}
                          </span>
                          <span style={{ 
                            color: 'var(--text-primary)', 
                            fontSize: '13px', 
                            lineHeight: '1.5' 
                          }}>
                            {parsedItems[0] || rec}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Build Changes (commits/files) - shown when no test report */}
              {data.buildChanges && data.buildChanges.commits && data.buildChanges.commits.length > 0 && (
                <div>
                  <h3 style={{ 
                    fontSize: '14px', 
                    fontWeight: '600', 
                    color: 'var(--text-secondary)',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}>
                    <FileText size={16} style={{ color: 'var(--accent-blue)' }} />
                    Recent Commits ({data.buildChanges.totalCommits})
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '400' }}>
                      ({data.buildChanges.totalFilesChanged} files changed)
                    </span>
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {data.buildChanges.commits.map((commit, idx) => (
                      <CommitCard 
                        key={idx} 
                        commit={commit}
                        expanded={expandedTests[commit.id]}
                        onToggle={() => toggleTestExpand(commit.id)}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Error Lines from Console - shown when no test report */}
              {data.errorLines && data.errorLines.length > 0 && (
                <div>
                  <h3 style={{ 
                    fontSize: '14px', 
                    fontWeight: '600', 
                    color: 'var(--text-secondary)',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}>
                    <AlertCircle size={16} style={{ color: 'var(--accent-red)' }} />
                    Error Messages from Console
                  </h3>
                  <div style={{
                    background: 'var(--bg-tertiary)',
                    borderRadius: '8px',
                    padding: '12px',
                    border: '1px solid rgba(244, 67, 54, 0.2)'
                  }}>
                    {data.errorLines.map((line, idx) => (
                      <div key={idx} style={{
                        fontFamily: 'monospace',
                        fontSize: '12px',
                        color: 'var(--accent-red)',
                        padding: '4px 0',
                        borderBottom: idx < data.errorLines.length - 1 ? '1px solid var(--border-color)' : 'none',
                        wordBreak: 'break-word'
                      }}>
                        {line}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Failed Tests Details */}
              {data.failedTests && data.failedTests.length > 0 && (
                <div>
                  <h3 style={{ 
                    fontSize: '14px', 
                    fontWeight: '600', 
                    color: 'var(--text-secondary)',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}>
                    <FileText size={16} style={{ color: 'var(--accent-red)' }} />
                    Failed Tests ({data.failedTests.length})
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {data.failedTests.map((test, idx) => (
                      <FailedTestCard 
                        key={idx} 
                        test={test} 
                        expanded={expandedTests[test.name]}
                        onToggle={() => toggleTestExpand(test.name)}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Analysis Info */}
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '12px 16px',
                background: 'var(--bg-secondary)',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                fontSize: '12px',
                color: 'var(--text-muted)'
              }}>
                {data.analysisEngine === 'unavailable' || data.analysisType === 'error' ? (
                  <span style={{ color: 'var(--accent-red)', fontWeight: '600' }}>
                    ⚠️ LLM Analysis Unavailable - Check Ollama Gateway
                  </span>
                ) : (
                  <span>
                    Analysis: {data.analysisType || 'llm_rag'} | 
                    Engine: {data.analysisEngine || 'unknown'}
                  </span>
                )}
                <span>
                  Source: {data.dataSource || 'jenkins'}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// Helper components for TFA Modal
const SummaryCard = ({ label, value, color }) => (
  <div style={{
    background: color ? `linear-gradient(135deg, ${color}15, ${color}08)` : 'var(--bg-secondary)',
    borderRadius: '10px',
    padding: '16px',
    textAlign: 'center',
    border: `1px solid ${color ? `${color}30` : 'var(--border-color)'}`
  }}>
    <div style={{ fontSize: '24px', fontWeight: '700', color: color || 'var(--text-primary)' }}>
      {value}
    </div>
    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>{label}</div>
  </div>
);

const RootCauseCard = ({ cause }) => {
  // Clean up markdown formatting from description
  const cleanDescription = (text) => {
    if (!text) return '';
    return text
      .replace(/\*\*([^*]+)\*\*/g, '$1') // Remove **bold** markers
      .replace(/^\s*[-•]\s*/gm, '') // Remove bullet points
      .trim();
  };
  
  return (
    <div 
      style={{
        background: 'var(--bg-secondary)',
        borderRadius: '10px',
        padding: '14px 16px',
        border: '1px solid var(--border-color)',
        borderLeft: `4px solid ${getSeverityColor(cause.severity)}`
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
        <span style={{
          fontSize: '11px',
          fontWeight: '600',
          padding: '3px 8px',
          borderRadius: '4px',
          background: `${getSeverityColor(cause.severity)}20`,
          color: getSeverityColor(cause.severity),
          textTransform: 'uppercase'
        }}>
          {cause.severity || 'Medium'}
        </span>
        <span style={{
          fontSize: '11px',
          padding: '3px 8px',
          borderRadius: '4px',
          background: 'var(--bg-tertiary)',
          color: 'var(--text-muted)'
        }}>
          {cause.type || 'Unknown'}
        </span>
      </div>
      <p style={{ margin: 0, fontSize: '14px', color: 'var(--text-primary)', lineHeight: '1.5' }}>
        {cleanDescription(cause.description)}
      </p>
    </div>
  );
};

const FailureClusterCard = ({ cluster, isExpanded, onToggle }) => {
  const categoryColors = {
    connection: 'var(--accent-orange)',
    timeout: 'var(--accent-orange)',
    assertion: 'var(--accent-red)',
    configuration: 'var(--accent-purple)',
    infrastructure: 'var(--accent-blue)',
    authentication: 'var(--accent-red)',
    permission: 'var(--accent-red)',
    resource: 'var(--accent-orange)',
    dependency: 'var(--accent-purple)',
    build_error: 'var(--accent-red)',
    test_error: 'var(--accent-orange)',
    unknown: 'var(--text-muted)',
  };

  const color = categoryColors[cluster.category] || 'var(--accent-orange)';
  
  // Clean up root cause text
  const cleanRootCause = (text) => {
    if (!text) return 'Unknown error';
    return text
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/^\s*[-•]\s*/gm, '')
      .substring(0, 200) + (text.length > 200 ? '...' : '');
  };

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      borderRadius: '12px',
      border: '1px solid var(--border-color)',
      borderLeft: `4px solid ${color}`,
      overflow: 'hidden'
    }}>
      {/* Cluster Header */}
      <div 
        onClick={onToggle}
        style={{
          padding: '16px',
          cursor: 'pointer',
          background: isExpanded ? 'var(--bg-tertiary)' : 'transparent',
          transition: 'background 0.2s'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <AlertTriangle size={18} style={{ color }} />
            <span style={{ 
              fontSize: '15px', 
              fontWeight: '600', 
              color: 'var(--text-primary)' 
            }}>
              {cluster.label}
            </span>
            <span style={{
              fontSize: '12px',
              fontWeight: '600',
              padding: '4px 10px',
              borderRadius: '12px',
              background: `${color}20`,
              color: color
            }}>
              {cluster.count} {cluster.count === 1 ? 'test' : 'tests'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{
              fontSize: '10px',
              fontWeight: '600',
              padding: '3px 8px',
              borderRadius: '4px',
              background: `${getSeverityColor(cluster.severity)}15`,
              color: getSeverityColor(cluster.severity),
              textTransform: 'uppercase'
            }}>
              {cluster.severity}
            </span>
            {isExpanded ? 
              <ChevronUp size={18} style={{ color: 'var(--text-muted)' }} /> : 
              <ChevronDown size={18} style={{ color: 'var(--text-muted)' }} />
            }
          </div>
        </div>
        
        {/* Root Cause Summary */}
        <p style={{ 
          margin: 0, 
          fontSize: '13px', 
          color: 'var(--text-secondary)', 
          lineHeight: '1.5',
          paddingLeft: '28px'
        }}>
          {cleanRootCause(cluster.rootCause)}
        </p>
        
        {/* Product Context Badge */}
        {cluster.productContext && (
          <div style={{ 
            marginTop: '8px', 
            paddingLeft: '28px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span style={{
              fontSize: '11px',
              fontWeight: '600',
              padding: '3px 8px',
              borderRadius: '4px',
              background: 'rgba(124, 92, 219, 0.15)',
              color: 'var(--accent-purple)',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}>
              📦 {cluster.productContext.component}
            </span>
            {cluster.productContext.owner && (
              <span style={{
                fontSize: '10px',
                color: 'var(--text-muted)'
              }}>
                Owner: {cluster.productContext.owner}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div style={{ 
          padding: '0 16px 16px', 
          borderTop: '1px solid var(--border-color)',
          background: 'var(--bg-tertiary)'
        }}>
          {/* Product-Specific Recommendations */}
          {cluster.productRecommendations && cluster.productRecommendations.length > 0 && (
            <div style={{ marginTop: '12px' }}>
              <div style={{ 
                fontSize: '12px', 
                fontWeight: '600', 
                color: 'var(--accent-purple)', 
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}>
                📦 Product-Specific Tips
              </div>
              <div style={{ 
                background: 'rgba(124, 92, 219, 0.08)', 
                borderRadius: '8px', 
                padding: '10px 12px',
                border: '1px solid rgba(124, 92, 219, 0.15)'
              }}>
                {cluster.productRecommendations.map((rec, idx) => (
                  <div key={idx} style={{ 
                    display: 'flex', 
                    alignItems: 'flex-start', 
                    gap: '8px',
                    marginBottom: idx < cluster.productRecommendations.length - 1 ? '6px' : 0
                  }}>
                    <span style={{
                      minWidth: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      background: 'var(--accent-purple)',
                      marginTop: '6px'
                    }} />
                    <span style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: '1.4' }}>
                      {rec.replace(/^\[[^\]]+\]\s*/, '')}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* General Recommendations */}
          {cluster.recommendations && cluster.recommendations.length > 0 && (
            <div style={{ marginTop: '12px' }}>
              <div style={{ 
                fontSize: '12px', 
                fontWeight: '600', 
                color: 'var(--text-muted)', 
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}>
                <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />
                Recommendations
              </div>
              <div style={{ 
                background: 'rgba(76, 175, 80, 0.08)', 
                borderRadius: '8px', 
                padding: '10px 12px',
                border: '1px solid rgba(76, 175, 80, 0.15)'
              }}>
                {cluster.recommendations.slice(0, 3).map((rec, idx) => (
                  <div key={idx} style={{ 
                    display: 'flex', 
                    alignItems: 'flex-start', 
                    gap: '8px',
                    marginBottom: idx < 2 ? '6px' : 0
                  }}>
                    <span style={{
                      minWidth: '18px',
                      height: '18px',
                      borderRadius: '50%',
                      background: 'var(--accent-green)',
                      color: 'white',
                      fontSize: '10px',
                      fontWeight: '600',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}>
                      {idx + 1}
                    </span>
                    <span style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: '1.4' }}>
                      {rec.replace(/^\d+\.\s*/, '').substring(0, 150)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Affected Tests */}
          <div style={{ marginTop: '12px' }}>
            <div style={{ 
              fontSize: '12px', 
              fontWeight: '600', 
              color: 'var(--text-muted)', 
              marginBottom: '8px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              <XCircle size={14} style={{ color: 'var(--accent-red)' }} />
              Affected Tests ({cluster.tests.length})
            </div>
            <div style={{ 
              background: 'var(--bg-secondary)', 
              borderRadius: '8px', 
              padding: '8px',
              border: '1px solid var(--border-color)',
              maxHeight: '200px',
              overflowY: 'auto'
            }}>
              {cluster.tests.slice(0, 10).map((test, idx) => (
                <div key={idx} style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '8px',
                  padding: '6px 8px',
                  borderRadius: '6px',
                  background: idx % 2 === 0 ? 'rgba(0,0,0,0.02)' : 'transparent'
                }}>
                  <XCircle size={12} style={{ color: 'var(--accent-red)', flexShrink: 0 }} />
                  <span style={{ 
                    fontSize: '12px', 
                    color: 'var(--text-primary)',
                    fontFamily: 'monospace'
                  }}>
                    {test.name}
                  </span>
                </div>
              ))}
              {cluster.tests.length > 10 && (
                <div style={{ 
                  padding: '8px', 
                  textAlign: 'center', 
                  fontSize: '11px', 
                  color: 'var(--text-muted)' 
                }}>
                  ... and {cluster.tests.length - 10} more tests
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const FailedTestCard = ({ test, expanded, onToggle }) => (
  <div 
    style={{
      background: 'var(--bg-secondary)',
      borderRadius: '10px',
      border: '1px solid var(--border-color)',
      overflow: 'hidden'
    }}
  >
    <div 
      style={{
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        cursor: 'pointer',
        background: expanded ? 'var(--bg-tertiary)' : 'transparent'
      }}
      onClick={onToggle}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {expanded ? 
          <ChevronDown size={16} style={{ color: 'var(--text-muted)' }} /> : 
          <ChevronRight size={16} style={{ color: 'var(--text-muted)' }} />
        }
        <XCircle size={14} style={{ color: 'var(--accent-red)' }} />
        <span style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-primary)' }}>
          {test.name || 'Unknown Test'}
        </span>
      </div>
      <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
        {test.className}
      </span>
    </div>
    {expanded && (
      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-color)' }}>
        {test.analysis?.root_cause && (
          <div style={{ marginBottom: '12px' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>
              Analysis
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: '1.5' }}>
              {test.analysis.root_cause}
            </div>
          </div>
        )}
        {test.errorMessage && (
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>
              Error Message
            </div>
            <pre style={{
              margin: 0,
              padding: '10px',
              background: 'var(--bg-tertiary)',
              borderRadius: '6px',
              fontSize: '12px',
              color: 'var(--accent-red)',
              overflow: 'auto',
              maxHeight: '150px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word'
            }}>
              {test.errorMessage}
            </pre>
          </div>
        )}
      </div>
    )}
  </div>
);

// CommitCard component for displaying git commits
const CommitCard = ({ commit, expanded, onToggle }) => (
  <div 
    style={{
      background: 'var(--bg-secondary)',
      borderRadius: '10px',
      border: '1px solid var(--border-color)',
      overflow: 'hidden'
    }}
  >
    <div 
      style={{
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        cursor: 'pointer',
        background: expanded ? 'var(--bg-tertiary)' : 'transparent'
      }}
      onClick={onToggle}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
        {expanded ? 
          <ChevronDown size={16} style={{ color: 'var(--text-muted)', flexShrink: 0 }} /> : 
          <ChevronRight size={16} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
        }
        <span style={{
          fontSize: '11px',
          fontFamily: 'monospace',
          padding: '2px 6px',
          borderRadius: '4px',
          background: 'var(--accent-blue)20',
          color: 'var(--accent-blue)',
          flexShrink: 0
        }}>
          {commit.id}
        </span>
        <span style={{ 
          fontSize: '13px', 
          fontWeight: '500', 
          color: 'var(--text-primary)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}>
          {commit.message}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0 }}>
        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          {commit.author}
        </span>
        <span style={{
          fontSize: '11px',
          padding: '2px 6px',
          borderRadius: '4px',
          background: 'var(--bg-tertiary)',
          color: 'var(--text-muted)'
        }}>
          {commit.totalFiles || commit.files?.length || 0} files
        </span>
      </div>
    </div>
    {expanded && commit.files && commit.files.length > 0 && (
      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-color)' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px', textTransform: 'uppercase' }}>
          Changed Files
        </div>
        <div style={{
          background: 'var(--bg-tertiary)',
          borderRadius: '6px',
          padding: '8px 12px',
          maxHeight: '200px',
          overflow: 'auto'
        }}>
          {commit.files.map((file, idx) => (
            <div key={idx} style={{
              fontFamily: 'monospace',
              fontSize: '12px',
              color: 'var(--text-primary)',
              padding: '3px 0',
              borderBottom: idx < commit.files.length - 1 ? '1px solid var(--border-color)' : 'none'
            }}>
              {file}
            </div>
          ))}
          {commit.totalFiles > commit.files.length && (
            <div style={{
              fontSize: '11px',
              color: 'var(--text-muted)',
              paddingTop: '8px',
              fontStyle: 'italic'
            }}>
              ... and {commit.totalFiles - commit.files.length} more files
            </div>
          )}
        </div>
      </div>
    )}
  </div>
);

/**
 * Pipeline Card Component
 * Reusable card for displaying pipeline status
 */
export const PipelineCard = ({
  pipeline,
  onAnalyze,
  onBuildClick,
  renderIcon,
  showAnalyzeButton = true,
  isTfaCached = false
}) => {
  const recentBuilds = pipeline.recentBuilds || [];

  return (
    <div
      style={{
        background: 'var(--bg-secondary)',
        borderRadius: '12px',
        border: `1px solid ${pipeline.status === 'failed' ? 'rgba(244, 67, 54, 0.3)' : 
                            pipeline.status === 'unstable' ? 'rgba(255, 193, 7, 0.3)' : 'var(--border-color)'}`,
        overflow: 'hidden'
      }}
    >
      {/* Header */}
      <div style={{
        padding: '16px 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: pipeline.status === 'failed' ? 'rgba(244, 67, 54, 0.05)' :
                   pipeline.status === 'unstable' ? 'rgba(255, 193, 7, 0.05)' : 'var(--bg-tertiary)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {renderIcon && renderIcon(pipeline)}
          <div>
            <div style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-primary)' }}>
              {pipeline.displayName || pipeline.name}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              {pipeline.description || pipeline.name}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <StatusBadge status={pipeline.status} />
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: '16px 20px' }}>
        {/* Last Build Info */}
        {pipeline.lastBuild && (
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '16px',
            padding: '12px',
            background: 'var(--bg-tertiary)',
            borderRadius: '8px'
          }}>
            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>Latest Build</div>
              <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>
                #{pipeline.lastBuild.buildNumber}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>Duration</div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)' }}>
                {pipeline.lastBuild.duration || 'N/A'}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>When</div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)' }}>
                {pipeline.lastBuild.timestamp || 'N/A'}
              </div>
            </div>
          </div>
        )}

        {/* Recent Builds */}
        {recentBuilds.length > 0 && (
          <div>
            <div style={{ 
              display: 'flex', 
              justifyContent: 'space-between', 
              alignItems: 'center',
              marginBottom: '8px'
            }}>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '500' }}>
                Recent Builds
              </span>
            </div>
            <BuildHistory 
              builds={recentBuilds} 
              onBuildClick={(build, buildCanAnalyze, event) => {
                // Open Jenkins URL (default action for all builds)
                if (build.url) {
                  window.open(build.url, '_blank');
                }
              }}
              onAnalyzeClick={(build) => {
                // Trigger TFA analysis for this specific build
                if (onBuildClick) {
                  onBuildClick(pipeline, build);
                }
              }}
              showTfaHint={false}
            />
          </div>
        )}

        {/* Jenkins Link */}
        {pipeline.url && (
          <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'flex-end' }}>
            <a
              href={pipeline.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '12px',
                color: 'var(--accent-blue)',
                textDecoration: 'none'
              }}
            >
              View in Jenkins <ExternalLink size={12} />
            </a>
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * Custom hook for TFA functionality
 */
export const useTfa = () => {
  const [tfaModalOpen, setTfaModalOpen] = useState(false);
  const [tfaLoading, setTfaLoading] = useState(false);
  const [tfaData, setTfaData] = useState(null);
  const [tfaError, setTfaError] = useState(null);
  const [selectedBuild, setSelectedBuild] = useState(null);

  const fetchTfa = async (jobName, buildNumber, displayName, source = 'main') => {
    setTfaLoading(true);
    setTfaError(null);
    setTfaData(null);
    setSelectedBuild({ jobName, buildNumber, displayName });
    setTfaModalOpen(true);

    try {
      // Encode job name to handle special characters (e.g., slashes in multibranch pipelines)
      const encodedJobName = encodeURIComponent(jobName);
      const response = await fetch(`/api/jenkins/tfa/${encodedJobName}/${buildNumber}?source=${source}`);
      if (response.ok) {
        const data = await response.json();
        setTfaData(data);
      } else {
        const errorData = await response.json().catch(() => ({}));
        setTfaError(errorData.detail || 'Failed to fetch test analysis');
      }
    } catch (err) {
      console.error('TFA fetch error:', err);
      setTfaError('Cannot connect to analysis service');
    } finally {
      setTfaLoading(false);
    }
  };

  const closeTfaModal = () => {
    setTfaModalOpen(false);
    setTfaData(null);
    setTfaError(null);
    setSelectedBuild(null);
  };

  return {
    tfaModalOpen,
    tfaLoading,
    tfaData,
    tfaError,
    selectedBuild,
    fetchTfa,
    closeTfaModal
  };
};

/**
 * Legend Component for build status colors
 */
export const BuildLegend = ({ showTfaHint = true }) => (
  <div style={{
    display: 'flex',
    gap: '20px',
    padding: '12px 16px',
    background: 'var(--bg-secondary)',
    borderRadius: '8px',
    border: '1px solid var(--border-color)',
    fontSize: '12px',
    color: 'var(--text-muted)',
    flexWrap: 'wrap'
  }}>
    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span style={{ width: '12px', height: '12px', borderRadius: '2px', background: 'var(--accent-green)' }}></span> Success
    </span>
    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span style={{ width: '12px', height: '12px', borderRadius: '2px', background: 'var(--accent-red)' }}></span> Failed
    </span>
    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span style={{ width: '12px', height: '12px', borderRadius: '2px', background: 'var(--accent-orange)' }}></span> Unstable
    </span>
    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span style={{ width: '12px', height: '12px', borderRadius: '2px', background: 'var(--accent-blue)' }}></span> Running
    </span>
    {showTfaHint && (
      <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '6px' }}>
        <Zap size={12} style={{ color: 'var(--accent-purple)' }} /> Click failed/unstable builds for TFA
      </span>
    )}
  </div>
);

const PipelineComponents = {
  getStatusInfo,
  getSeverityColor,
  StatusBadge,
  BuildHistory,
  AnalyzeButton,
  TfaModal,
  PipelineCard,
  BuildLegend,
  useTfa
};

export default PipelineComponents;
