import React, { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Target,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Sparkles,
  ArrowRight,
  History,
  Zap,
  Shield,
  AlertCircle,
  Info
} from 'lucide-react';
import './RiskPredictorCard.css';

const API_BASE = '/api';

const RiskPredictorCard = ({ releaseId, onNavigate }) => {
  const [riskData, setRiskData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchRiskData = useCallback(async (isRetry = false) => {
    if (!releaseId) return;
    
    try {
      if (isRetry) {
        setLoading(true);
        setError(null);
      }
      setRefreshing(true);
      
      const response = await fetch(`${API_BASE}/release-risk/${releaseId}`);
      if (response.ok) {
        const data = await response.json();
        setRiskData(data);
        setError(null);
      } else {
        const errorData = await response.json();
        const detail = errorData.detail;
        
        if (typeof detail === 'object' && detail.error) {
          setError({
            type: detail.error,
            message: detail.message,
            action: detail.action
          });
        } else {
          setError({
            type: 'unknown',
            message: detail || 'Failed to load risk prediction',
            action: null
          });
        }
      }
    } catch (err) {
      setError({
        type: 'connection',
        message: 'Failed to connect to risk prediction service',
        action: 'Check if the backend server is running'
      });
      console.error('Risk prediction error:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [releaseId]);

  useEffect(() => {
    fetchRiskData();
  }, [fetchRiskData]);

  const getProbabilityColor = (probability) => {
    if (probability >= 75) return 'var(--color-success)';
    if (probability >= 50) return 'var(--color-warning)';
    return 'var(--color-danger)';
  };

  const getRiskLevelClass = (level) => {
    switch (level) {
      case 'low': return 'risk-low';
      case 'medium': return 'risk-medium';
      case 'high': return 'risk-high';
      default: return 'risk-medium';
    }
  };

  const getRiskLevelIcon = (level) => {
    switch (level) {
      case 'low': return <CheckCircle2 size={16} />;
      case 'medium': return <AlertCircle size={16} />;
      case 'high': return <AlertTriangle size={16} />;
      default: return <AlertCircle size={16} />;
    }
  };

  const getImpactClass = (impact) => {
    switch (impact) {
      case 'high': return 'impact-high';
      case 'medium': return 'impact-medium';
      case 'low': return 'impact-low';
      default: return 'impact-medium';
    }
  };

  if (loading) {
    return (
      <div className="risk-predictor-card loading">
        <div className="risk-card-header">
          <div className="risk-title">
            <Target size={20} />
            <span>Release Risk Predictor</span>
          </div>
        </div>
        <div className="risk-loading">
          <RefreshCw size={24} className="spin" />
          <span>Analyzing release risk...</span>
        </div>
      </div>
    );
  }

  if (error) {
    const isLLMError = error.type === 'llm_not_configured' || error.type === 'llm_error';
    
    return (
      <div className={`risk-predictor-card error ${isLLMError ? 'llm-required' : ''}`}>
        <div className="risk-card-header">
          <div className="risk-title">
            <Target size={20} />
            <span>Release Risk Predictor</span>
            <span className="ai-badge">
              <Sparkles size={12} />
              AI Required
            </span>
          </div>
        </div>
        <div className="risk-error">
          <div className="error-icon">
            {isLLMError ? <Sparkles size={24} /> : <AlertTriangle size={24} />}
          </div>
          <div className="error-content">
            <span className="error-title">
              {isLLMError ? 'Ollama LLM Required' : 'Error'}
            </span>
            <span className="error-message">{error.message}</span>
            {error.action && (
              <span className="error-action">{error.action}</span>
            )}
          </div>
          <button onClick={() => fetchRiskData(true)} className="retry-btn">
            <RefreshCw size={14} />
            Retry
          </button>
        </div>
        {isLLMError && (
          <div className="llm-info-banner">
            <Info size={14} />
            <span>
              This feature uses Llama 3.2 via Ollama for AI-powered risk analysis. 
              No fallback mode available.
            </span>
          </div>
        )}
      </div>
    );
  }

  if (!riskData) return null;

  const { prediction, current_metrics, historical_average, similar_releases, ai_insights } = riskData;
  const probability = prediction?.probability || 50;
  const riskLevel = prediction?.risk_level || 'medium';
  const confidence = prediction?.confidence || 'low';

  return (
    <div className={`risk-predictor-card ${getRiskLevelClass(riskLevel)}`}>
      <div className="risk-card-header">
        <div className="risk-title">
          <Target size={20} />
          <span>Release Risk Predictor</span>
          <span className="ai-badge">
            <Sparkles size={12} />
            AI
          </span>
        </div>
        <div className="risk-actions">
          <button 
            className="refresh-btn" 
            onClick={() => fetchRiskData(false)}
            disabled={refreshing}
            title="Refresh prediction"
          >
            <RefreshCw size={14} className={refreshing ? 'spin' : ''} />
          </button>
          <button 
            className="expand-btn"
            onClick={() => setExpanded(!expanded)}
            title={expanded ? 'Show less' : 'Show details'}
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      <div className="risk-main-content">
        <div className="probability-section">
          <div className="probability-gauge">
            <svg viewBox="0 0 120 120" className="gauge-svg">
              <circle
                cx="60"
                cy="60"
                r="50"
                fill="none"
                stroke="var(--border-color)"
                strokeWidth="10"
              />
              <circle
                cx="60"
                cy="60"
                r="50"
                fill="none"
                stroke={getProbabilityColor(probability)}
                strokeWidth="10"
                strokeDasharray={`${(probability / 100) * 314} 314`}
                strokeLinecap="round"
                transform="rotate(-90 60 60)"
                className="gauge-progress"
              />
            </svg>
            <div className="gauge-value">
              <span className="probability-number">{probability}%</span>
              <span className="probability-label">On-Time</span>
            </div>
          </div>
          
          <div className="risk-summary">
            <div className={`risk-level-badge ${getRiskLevelClass(riskLevel)}`}>
              {getRiskLevelIcon(riskLevel)}
              <span>{riskLevel.toUpperCase()} RISK</span>
            </div>
            <div className="milestone-info">
              <Clock size={14} />
              <span>{riskData.days_to_milestone} days to {riskData.milestone}</span>
            </div>
            <div className="confidence-info">
              <Shield size={14} />
              <span>{confidence} confidence</span>
            </div>
          </div>
        </div>

        {ai_insights?.summary && (
          <div className="ai-summary">
            <div className="ai-summary-header">
              <Sparkles size={14} />
              <span>AI Analysis</span>
            </div>
            <p>{ai_insights.summary}</p>
          </div>
        )}
      </div>

      {expanded && (
        <div className="risk-details">
          <div className="risk-factors-section">
            <div className="factors-column">
              <h4>
                <AlertTriangle size={14} />
                Risk Factors
              </h4>
              <ul className="factors-list risk">
                {ai_insights?.risk_factors?.map((factor, idx) => (
                  <li key={idx}>{factor}</li>
                ))}
              </ul>
            </div>
            
            <div className="factors-column">
              <h4>
                <CheckCircle2 size={14} />
                Positive Factors
              </h4>
              <ul className="factors-list positive">
                {ai_insights?.positive_factors?.map((factor, idx) => (
                  <li key={idx}>{factor}</li>
                ))}
              </ul>
            </div>
          </div>

          {ai_insights?.action_items && ai_insights.action_items.length > 0 && (
            <div className="action-items-section">
              <h4>
                <Zap size={14} />
                Recommended Actions
              </h4>
              <div className="action-items-list">
                {ai_insights.action_items.map((item, idx) => (
                  <div key={idx} className={`action-item ${getImpactClass(item.impact)}`}>
                    <span className="action-priority">#{item.priority}</span>
                    <span className="action-text">{item.action}</span>
                    <span className={`action-impact ${getImpactClass(item.impact)}`}>
                      {item.impact}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="comparison-section">
            <div className="metrics-comparison">
              <h4>
                <TrendingUp size={14} />
                Current vs Historical Average
              </h4>
              <div className="metrics-grid">
                <div className="metric-row">
                  <span className="metric-label">P1 Bugs</span>
                  <span className="metric-current">{current_metrics?.p1_bugs || 0}</span>
                  <span className="metric-vs">vs</span>
                  <span className="metric-avg">{historical_average?.p1_bugs || 'N/A'}</span>
                  {historical_average?.p1_bugs && (
                    <span className={`metric-diff ${(current_metrics?.p1_bugs || 0) > historical_average.p1_bugs ? 'worse' : 'better'}`}>
                      {(current_metrics?.p1_bugs || 0) > historical_average.p1_bugs ? (
                        <TrendingUp size={12} />
                      ) : (
                        <TrendingDown size={12} />
                      )}
                    </span>
                  )}
                </div>
                <div className="metric-row">
                  <span className="metric-label">Total Open</span>
                  <span className="metric-current">{current_metrics?.total_open || 0}</span>
                  <span className="metric-vs">vs</span>
                  <span className="metric-avg">{historical_average?.total_open || 'N/A'}</span>
                  {historical_average?.total_open && (
                    <span className={`metric-diff ${(current_metrics?.total_open || 0) > historical_average.total_open ? 'worse' : 'better'}`}>
                      {(current_metrics?.total_open || 0) > historical_average.total_open ? (
                        <TrendingUp size={12} />
                      ) : (
                        <TrendingDown size={12} />
                      )}
                    </span>
                  )}
                </div>
                <div className="metric-row">
                  <span className="metric-label">Velocity</span>
                  <span className="metric-current">{current_metrics?.velocity_per_day?.toFixed(1) || 0}/day</span>
                  <span className="metric-vs">vs</span>
                  <span className="metric-avg">{historical_average?.velocity_per_day?.toFixed(1) || 'N/A'}/day</span>
                  {historical_average?.velocity_per_day && (
                    <span className={`metric-diff ${(current_metrics?.velocity_per_day || 0) < historical_average.velocity_per_day ? 'worse' : 'better'}`}>
                      {(current_metrics?.velocity_per_day || 0) >= historical_average.velocity_per_day ? (
                        <TrendingUp size={12} />
                      ) : (
                        <TrendingDown size={12} />
                      )}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {similar_releases && similar_releases.length > 0 && (
              <div className="similar-releases">
                <h4>
                  <History size={14} />
                  Similar Past Releases
                </h4>
                <div className="similar-list">
                  {similar_releases.map((release, idx) => (
                    <div key={idx} className="similar-release-item">
                      <span className="release-name">{release.release}</span>
                      <span className="similarity">{Math.round(release.similarity * 100)}% match</span>
                      <span className={`outcome ${release.outcome === 'on_time' ? 'success' : 'warning'}`}>
                        {release.outcome === 'on_time' ? 'On-time' : release.outcome.replace(/_/g, ' ')}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {ai_insights?.similar_release_analysis && (
            <div className="similar-analysis">
              <Info size={14} />
              <p>{ai_insights.similar_release_analysis}</p>
            </div>
          )}

          {ai_insights?.probability_reasoning && (
            <div className="probability-reasoning">
              <h4>
                <Info size={14} />
                Probability Reasoning
              </h4>
              <p>{ai_insights.probability_reasoning}</p>
            </div>
          )}

          {riskData.llm_model && (
            <div className="model-info">
              <Sparkles size={12} />
              <span>
                Powered by {riskData.llm_model}
                {riskData.llm_latency_ms && (
                  <span className="latency"> • {riskData.llm_latency_ms}ms</span>
                )}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default RiskPredictorCard;
