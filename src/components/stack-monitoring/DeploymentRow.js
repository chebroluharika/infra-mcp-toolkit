import React, { useState } from 'react';
import { 
  CheckCircle,
  AlertTriangle,
  XCircle,
  Activity,
  RotateCcw,
  Terminal,
  ChevronRight,
  Copy,
  Check
} from 'lucide-react';

/**
 * DeploymentRow - Individual deployment item within a stack card
 */
const DeploymentRow = ({ 
  deployment, 
  stackId,
  onClick,
  onCopyKubectl
}) => {
  const [copied, setCopied] = useState(false);
  
  const getStatusIcon = (status) => {
    if (!status) return <Activity size={14} style={{ color: 'var(--text-muted)' }} />;
    
    const lowerStatus = status.toLowerCase();
    if (lowerStatus === 'healthy') {
      return <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />;
    }
    if (lowerStatus.includes('unhealthy') || lowerStatus.includes('error')) {
      return <XCircle size={14} style={{ color: 'var(--accent-red)' }} />;
    }
    return <AlertTriangle size={14} style={{ color: 'var(--accent-orange)' }} />;
  };
  
  const getStatusClass = (status) => {
    if (!status) return 'unknown';
    const lowerStatus = status.toLowerCase();
    if (lowerStatus === 'healthy') return 'healthy';
    if (lowerStatus.includes('unhealthy') || lowerStatus.includes('error')) return 'critical';
    return 'warning';
  };
  
  const handleCopy = (e) => {
    e.stopPropagation();
    if (onCopyKubectl) {
      onCopyKubectl(e);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };
  
  // Extract short deployment name for display
  const displayName = deployment.deployment?.split('/')[0] || deployment.deployment;
  
  // Format replicas display
  const replicasDisplay = deployment.replicas 
    ? `${deployment.replicas.ready || 0}/${deployment.replicas.desired || 0}`
    : '-';
  
  const hasIssues = deployment.crashLoop || 
    deployment.status?.includes('unhealthy') || 
    deployment.status?.includes('error') ||
    deployment.errorReason ||
    deployment.restartRateHigh;
  
  // Format error message for display
  const getErrorDisplay = () => {
    if (!deployment.errorReason) return null;
    
    // Shorten common error messages
    let shortMessage = deployment.errorReason;
    if (deployment.errorMessage) {
      // Extract key info from long messages
      if (deployment.errorMessage.includes('manifest')) {
        shortMessage = 'Image not found';
      } else if (deployment.errorMessage.includes('pulling image')) {
        shortMessage = 'Image pull failed';
      } else if (deployment.errorMessage.length > 50) {
        shortMessage = deployment.errorMessage.substring(0, 47) + '...';
      } else {
        shortMessage = deployment.errorMessage;
      }
    }
    return { reason: deployment.errorReason, message: shortMessage, full: deployment.errorMessage };
  };
  
  const errorInfo = getErrorDisplay();

  return (
    <div 
      className={`deployment-row status-${getStatusClass(deployment.status)} ${hasIssues ? 'has-issues' : ''}`}
      onClick={onClick}
    >
      <div className="deployment-main">
        {/* Status Indicator */}
        <div className="deployment-status">
          {getStatusIcon(deployment.status)}
        </div>
        
        {/* Deployment Info */}
        <div className="deployment-info">
          <div className="deployment-name">
            <span className="name" title={displayName}>{displayName}</span>
            {deployment.crashLoop && (
              <span className="crash-loop-badge">
                <RotateCcw size={10} /> CrashLoop
              </span>
            )}
            {errorInfo && !deployment.crashLoop && (
              <span 
                className="error-badge" 
                title={errorInfo.full || errorInfo.reason}
              >
                {errorInfo.reason}
              </span>
            )}
          </div>
          <div className="deployment-meta">
            <span className="namespace" title={deployment.namespace}>{deployment.namespace}</span>
            {deployment.version && deployment.version !== 'unknown' && deployment.version !== 'error' && (
              <>
                <span className="separator">•</span>
                <span className="version" title={`Version: ${deployment.version}`}>{deployment.version}</span>
              </>
            )}
            {errorInfo && (
              <>
                <span className="separator">•</span>
                <span className="error-message" title={errorInfo.full || errorInfo.message}>
                  {errorInfo.message}
                </span>
              </>
            )}
          </div>
        </div>
        
        {/* Metrics */}
        <div className="deployment-metrics">
          <span className="metric replicas" title="Ready/Desired replicas">
            {replicasDisplay}
          </span>
          {deployment.age && deployment.age !== 'unknown' && (
            <span className="metric age" title="Deployment age">
              {deployment.age}
            </span>
          )}
          {deployment.restarts > 0 && (
            <span 
              className={`metric restarts ${deployment.restartRateHigh ? 'high-rate' : ''}`} 
              title={`${deployment.restarts} total restarts${deployment.restartRateDisplay ? ` (${deployment.restartRateDisplay} per pod)` : ''}${deployment.restartRateHigh ? ' - HIGH RATE' : ''}`}
            >
              <RotateCcw size={10} />
              {deployment.restartRateDisplay || deployment.restarts}
            </span>
          )}
        </div>
        
        {/* Actions */}
        <div className="deployment-actions">
          <button 
            className={`action-btn copy ${copied ? 'copied' : ''}`}
            onClick={handleCopy}
            title="Copy kubectl command"
          >
            {copied ? <Check size={14} /> : <Terminal size={14} />}
          </button>
          <ChevronRight size={16} className="arrow" />
        </div>
      </div>
    </div>
  );
};

export default DeploymentRow;
