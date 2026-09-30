import React, { useState } from 'react';
import { 
  AlertTriangle, 
  CheckCircle, 
  XCircle,
  Info
} from 'lucide-react';

/**
 * HealthScoreCard - Displays health score based on stack status distribution
 * 
 * Formula: Score = (Healthy × 100 + Warning × 50 + Critical × 0) / Total Stacks
 */
const HealthScoreCard = ({ healthScore, stackData, onStatClick }) => {
  const { score, healthy, warning, critical, total } = healthScore;
  const [showFormula, setShowFormula] = useState(false);
  
  const getScoreColor = (score) => {
    if (score >= 90) return 'var(--accent-green)';
    if (score >= 70) return 'var(--accent-orange)';
    if (score >= 50) return '#ff9800';
    return 'var(--accent-red)';
  };
  
  const getScoreLabel = (score) => {
    if (score >= 90) return 'Healthy';
    if (score >= 70) return 'Attention Needed';
    if (score >= 50) return 'Degraded';
    return 'Critical';
  };

  const formulaNumerator = total > 0
    ? `(${healthy} × 100) + (${warning} × 50) + (${critical} × 0)`
    : null;
  const formulaResult = total > 0
    ? `${healthy * 100 + warning * 50} / ${total} = ${score}`
    : null;

  return (
    <div className="health-score-card">
      {/* Main Score Circle */}
      <div className="health-score-main">
        <div 
          className="health-score-circle"
          onMouseEnter={() => setShowFormula(true)}
          onMouseLeave={() => setShowFormula(false)}
        >
          {/* Formula tooltip on hover */}
          {showFormula && (
            <div className="formula-tooltip">
              <div className="formula-title">
                <Info size={14} />
                <span>Health Score</span>
              </div>
              <div className="formula-generic">
                <span className="formula-label">Formula</span>
                <code>(Healthy × 100 + Warning × 50 + Critical × 0) ÷ Total</code>
              </div>
              {formulaNumerator && (
                <div className="formula-calculation">
                  <span className="formula-label">Calculation</span>
                  <code>{formulaNumerator}</code>
                  <code className="formula-result">= {formulaResult}</code>
                </div>
              )}
            </div>
          )}
          
          <svg viewBox="0 0 100 100">
            {/* Background circle */}
            <circle
              cx="50" cy="50" r="42"
              fill="none"
              stroke="var(--border-color)"
              strokeWidth="8"
            />
            {/* Progress circle */}
            <circle
              cx="50" cy="50" r="42"
              fill="none"
              stroke={getScoreColor(score)}
              strokeWidth="8"
              strokeDasharray={`${score * 2.64} 264`}
              strokeLinecap="round"
              style={{ transform: 'rotate(-90deg)', transformOrigin: 'center' }}
            />
          </svg>
          <div className="health-score-value">
            <span className="score-number" style={{ color: getScoreColor(score) }}>
              {score}
            </span>
            <span className="score-label">{getScoreLabel(score)}</span>
          </div>
          
          {/* Small info icon indicator */}
          <div className="score-info-hint">
            <Info size={12} />
          </div>
        </div>
        
        {/* Quick Stats - Clickable to filter/expand stacks */}
        <div className="health-quick-stats">
          <div 
            className={`quick-stat ${healthy > 0 ? 'clickable' : ''}`}
            onClick={() => healthy > 0 && onStatClick && onStatClick('healthy')}
            title={healthy > 0 ? 'Click to filter healthy stacks' : ''}
          >
            <CheckCircle size={16} style={{ color: 'var(--accent-green)' }} />
            <span className="stat-value">{healthy}</span>
            <span className="stat-label">Healthy</span>
          </div>
          <div 
            className={`quick-stat ${warning > 0 ? 'clickable' : ''}`}
            onClick={() => warning > 0 && onStatClick && onStatClick('warning')}
            title={warning > 0 ? 'Click to filter warning stacks' : ''}
          >
            <AlertTriangle size={16} style={{ color: 'var(--accent-orange)' }} />
            <span className="stat-value">{warning}</span>
            <span className="stat-label">Warning</span>
          </div>
          <div 
            className={`quick-stat ${critical > 0 ? 'clickable' : ''}`}
            onClick={() => critical > 0 && onStatClick && onStatClick('critical')}
            title={critical > 0 ? 'Click to view critical stack details' : ''}
          >
            <XCircle size={16} style={{ color: 'var(--accent-red)' }} />
            <span className="stat-value">{critical}</span>
            <span className="stat-label">Critical</span>
          </div>
        </div>
      </div>
      
      {/* Status Summary */}
      <div className="health-summary">
        <CheckCircle size={16} style={{ color: score >= 70 ? 'var(--accent-green)' : 'var(--accent-orange)' }} />
        <span className="summary-text">
          {score >= 90 
            ? 'All systems operational' 
            : score >= 70 
              ? `${warning + critical} stack${warning + critical !== 1 ? 's' : ''} need attention`
              : `${critical} critical, ${warning} warning`
          }
        </span>
      </div>
    </div>
  );
};

export default HealthScoreCard;
