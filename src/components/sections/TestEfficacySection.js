/**
 * TestEfficacySection - Test Efficacy Dashboard
 * 
 * Currently disabled - shows Coming Soon placeholder.
 * Will be implemented with test efficacy metrics from JIRA dashboard.
 * Reference: https://your-org.atlassian.net/jira/dashboards/58613
 */
import React from 'react';
import { Target, Clock } from 'lucide-react';

const TestEfficacySection = () => {
  return (
    <div className="test-efficacy-section">
      <div className="section-page-header">
        <div className="header-left">
          <h1><Target size={24} /> Test Efficacy</h1>
          <p>Measure test effectiveness and defect detection capabilities</p>
        </div>
      </div>

      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '100px 40px',
        textAlign: 'center',
        background: 'var(--bg-card)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-color)'
      }}>
        <div style={{
          width: '80px',
          height: '80px',
          borderRadius: '50%',
          background: 'linear-gradient(135deg, #7c5cdb 0%, #9b7ee8 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '24px'
        }}>
          <Clock size={40} style={{ color: 'white' }} />
        </div>
        
        <h2 style={{ 
          fontSize: '28px', 
          fontWeight: '700', 
          color: 'var(--text-primary)',
          margin: '0 0 12px 0'
        }}>
          Coming Soon
        </h2>
        
        <p style={{ 
          fontSize: '16px', 
          color: 'var(--text-muted)',
          maxWidth: '400px',
          lineHeight: '1.6'
        }}>
          Test Efficacy dashboard is under development. 
          This section will display test effectiveness metrics, 
          defect detection rates, and quality trend analysis.
        </p>
        
        <div style={{
          marginTop: '32px',
          padding: '16px 24px',
          background: 'var(--bg-tertiary)',
          borderRadius: 'var(--radius-md)',
          fontSize: '13px',
          color: 'var(--text-secondary)'
        }}>
          <strong>Data Source:</strong> JIRA Test Efficacy Dashboard
        </div>
      </div>
    </div>
  );
};

export default TestEfficacySection;
