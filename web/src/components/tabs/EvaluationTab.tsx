import React, { useState } from 'react';
import { EvaluationRunner } from '@/components/Evaluation/EvaluationRunner';
import { QuestionManager } from '@/components/Evaluation/QuestionManager';
import { HistoryViewer } from '@/components/Evaluation/HistoryViewer';
import { TraceViewer } from '@/components/Evaluation/TraceViewer';
import { FeedbackPanel } from '@/components/Evaluation/FeedbackPanel';

type SubTab = 'runner' | 'questions' | 'history' | 'trace' | 'feedback';

export const EvaluationTab: React.FC = () => {
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('runner');

  const subTabs: Array<{ id: SubTab; label: string; description: string }> = [
    { id: 'runner', label: 'Run Evaluation', description: 'Execute evaluations and view results' },
    { id: 'questions', label: 'Golden Questions', description: 'Manage test questions' },
    { id: 'history', label: 'History', description: 'View past evaluation runs' },
    { id: 'trace', label: 'Trace Viewer', description: 'Inspect latest trace data' },
    { id: 'feedback', label: 'Feedback', description: 'Share your feedback' }
  ];

  return (
    <div className="evaluation-tab" style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden'
    }}>
      {/* Header */}
      <div style={{
        padding: '20px 24px',
        borderBottom: '1px solid var(--line)',
        background: 'var(--bg)'
      }}>
        <h2 style={{
          fontSize: '20px',
          fontWeight: 700,
          color: 'var(--fg)',
          margin: 0,
          marginBottom: '8px'
        }}>
          Evaluation System
        </h2>
        <p style={{
          fontSize: '13px',
          color: 'var(--fg-muted)',
          margin: 0
        }}>
          Test and measure RAG retrieval performance with eval dataset
        </p>
      </div>

      {/* Sub-Tab Navigation */}
      <div style={{
        display: 'flex',
        gap: '4px',
        padding: '12px 24px',
        background: 'var(--bg-elev1)',
        borderBottom: '1px solid var(--line)',
        overflowX: 'auto',
        flexShrink: 0
      }}>
        {subTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id)}
            style={{
              background: activeSubTab === tab.id ? 'var(--accent)' : 'var(--bg-elev2)',
              color: activeSubTab === tab.id ? 'var(--accent-contrast)' : 'var(--fg)',
              border: activeSubTab === tab.id ? 'none' : '1px solid var(--line)',
              padding: '8px 16px',
              borderRadius: '6px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              transition: 'all 0.2s ease',
              opacity: activeSubTab === tab.id ? 1 : 0.85
            }}
            title={tab.description}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content Area */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        padding: '24px'
      }}>
        {activeSubTab === 'runner' && <EvaluationRunner />}
        {activeSubTab === 'questions' && <QuestionManager />}
        {activeSubTab === 'history' && <HistoryViewer />}
        {activeSubTab === 'trace' && <TraceViewer />}
        {activeSubTab === 'feedback' && <FeedbackPanel />}
      </div>
    </div>
  );
};
