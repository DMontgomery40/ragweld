/**
 * EmbeddingMismatchWarning Component
 * 
 * CRITICAL: Displays when current embedding config doesn't match the index.
 * This causes search to return completely irrelevant results because vectors
 * exist in incompatible mathematical spaces.
 * 
 * Variants:
 * - full: Large educational panel with visual comparison and action buttons
 * - compact: Small alert for sidepanel/headers
 * - inline: Medium-sized inline warning for forms/subtabs
 * 
 * Must be displayed in:
 * - App.tsx (bottom action bar) - global visibility
 * - Sidepanel.tsx (compact) - always visible
 * - RAG/IndexingSubtab.tsx - near index button
 * - RAG/RetrievalSubtab.tsx - near embedding config
 * - Chat/ChatInterface.tsx - before results
 * - Dashboard areas
 */

import React from 'react';
import { useEmbeddingStatus, EmbeddingStatus } from '@/hooks/useEmbeddingStatus';

interface EmbeddingMismatchWarningProps {
  variant?: 'full' | 'compact' | 'inline';
  showActions?: boolean;
  onNavigateToIndex?: () => void;
}

const APP_ROUTE_SEGMENTS = new Set<string>([
  '/start',
  '/dashboard',
  '/chat',
  '/grafana',
  '/benchmark',
  '/rag',
  '/eval',
  '/infrastructure',
  '/admin',
  '/docker',
  '/d',
]);

function resolveRouterBasePath(): string {
  const pathname = String(window.location.pathname || '/');
  const normalized = pathname.replace(/\/+$/, '') || '/';
  const segments = normalized.split('/').filter(Boolean);
  if (segments.length === 0) return '';

  // BrowserRouter basename can be multi-segment (e.g. /tools/ragweld/web).
  // Find the first known app route segment and keep everything before it.
  const routeIndex = segments.findIndex((segment) => APP_ROUTE_SEGMENTS.has(`/${segment}`));
  if (routeIndex === 0) return '';
  if (routeIndex > 0) return `/${segments.slice(0, routeIndex).join('/')}`;

  // If we're on the basename root itself (no known route segment yet), use the full path.
  return normalized === '/' ? '' : normalized;
}

function navigateToRag(params: URLSearchParams): void {
  const base = resolveRouterBasePath();
  const query = params.toString();
  const href = `${base}/rag${query ? `?${query}` : ''}`;
  window.location.assign(href);
}

/**
 * Navigate to indexing page with current embedding config pre-filled
 */
const navigateToReindex = () => {
  const params = new URLSearchParams(window.location.search || '');
  params.set('subtab', 'indexing');
  params.set('action', 'reindex');
  navigateToRag(params);
};

/**
 * Navigate to retrieval config to change embedding type
 */
const navigateToConfig = (indexType: string | null) => {
  const params = new URLSearchParams(window.location.search || '');
  params.set('subtab', 'retrieval');
  if (indexType) {
    params.set('restore_embedding', indexType);
  } else {
    params.delete('restore_embedding');
  }
  navigateToRag(params);
};

// Compact version for sidepanel/headers
const CompactWarning: React.FC<{ status: EmbeddingStatus }> = ({ status }) => (
  <div
    role="alert"
    aria-live="assertive"
    onClick={navigateToReindex}
    style={{
      background: 'linear-gradient(135deg, var(--err) 0%, #cc3333 100%)',
      color: 'white',
      padding: '8px 12px',
      borderRadius: '6px',
      fontSize: '12px',
      fontWeight: 600,
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      cursor: 'pointer',
      boxShadow: '0 2px 8px rgba(255, 107, 107, 0.3)',
      transition: 'all 0.2s ease',
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.transform = 'translateY(-1px)';
      e.currentTarget.style.boxShadow = '0 4px 12px rgba(255, 107, 107, 0.4)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.transform = 'translateY(0)';
      e.currentTarget.style.boxShadow = '0 2px 8px rgba(255, 107, 107, 0.3)';
    }}
    title={`Config: ${status.configType}/${status.configModel} (${status.configDim}d) ≠ Index: ${status.indexProvider || 'unknown'}/${status.indexType} (${status.indexDim}d). Click to fix.`}
  >
    <span style={{ fontSize: '14px' }}>⚠️</span>
    <span>Embedding Mismatch!</span>
  </div>
);

// Inline version for forms/subtabs
const InlineWarning: React.FC<{ status: EmbeddingStatus; showActions: boolean }> = ({ status, showActions }) => (
  <div
    role="alert"
    aria-live="assertive"
    style={{
      background: 'linear-gradient(135deg, rgba(255, 107, 107, 0.1) 0%, rgba(255, 107, 107, 0.05) 100%)',
      border: '1px solid var(--err)',
      borderRadius: '8px',
      padding: '12px 16px',
      marginBottom: '16px',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
      <span style={{ fontSize: '20px', flexShrink: 0 }}>⚠️</span>
      <div style={{ flex: 1 }}>
        <div style={{ 
          fontWeight: 600, 
          color: 'var(--err)', 
          fontSize: '13px',
          marginBottom: '4px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          Embedding Mismatch Detected
          <span 
            className="help-icon" 
            data-tooltip="EMBEDDING_MISMATCH"
            style={{ 
              cursor: 'help',
              fontSize: '11px',
              background: 'var(--bg-elev2)',
              borderRadius: '50%',
              width: '16px',
              height: '16px',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            ?
          </span>
        </div>
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
          Config:{' '}
          <code style={{ background: 'var(--code-bg)', padding: '1px 4px', borderRadius: '3px' }}>
            {status.configType}/{status.configModel}
          </code>{' '}
          ({status.configDim}d) ≠ Index:{' '}
          <code style={{ background: 'var(--code-bg)', padding: '1px 4px', borderRadius: '3px' }}>
            {(status.indexProvider || 'unknown')}/{status.indexType}
          </code>{' '}
          ({status.indexDim}d)
          <div style={{ marginTop: '6px', display: 'flex', gap: '10px', flexWrap: 'wrap', fontSize: '11px' }}>
            <span style={{ color: 'var(--fg-muted)' }}>Config strategy: {status.configStrategy}</span>
            {status.indexStrategy && <span style={{ color: 'var(--fg-muted)' }}>Index strategy: {status.indexStrategy}</span>}
          </div>
        </div>
        {showActions && (
          <div style={{ marginTop: '10px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <button
              onClick={navigateToReindex}
              style={{
                padding: '6px 12px',
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                border: 'none',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Re-index with {status.configType}/{status.configModel}
            </button>
            <button
              onClick={() => navigateToConfig(status.indexType)}
              style={{
                padding: '6px 12px',
                background: 'transparent',
                color: 'var(--fg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Revert to {(status.indexProvider || 'unknown')}/{status.indexType}
            </button>
          </div>
        )}
      </div>
    </div>
  </div>
);

// Full version for prominent display
const FullWarning: React.FC<{ status: EmbeddingStatus; showActions: boolean }> = ({ status, showActions }) => (
  <div
    role="alert"
    aria-live="assertive"
    aria-label="Critical embedding configuration mismatch warning"
    style={{
      background: 'linear-gradient(135deg, rgba(255, 107, 107, 0.08) 0%, rgba(255, 170, 0, 0.05) 100%)',
      border: '2px solid var(--err)',
      borderRadius: '12px',
      padding: '20px',
      marginBottom: '20px',
      boxShadow: '0 4px 20px rgba(255, 107, 107, 0.15)',
    }}
  >
    {/* Header */}
    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
      <div style={{
        width: '44px',
        height: '44px',
        borderRadius: '50%',
        background: 'rgba(255, 107, 107, 0.15)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: '22px',
        animation: 'pulse 2s ease-in-out infinite',
      }}>
        ⚠️
      </div>
      <div>
        <h3 style={{ 
          margin: 0, 
          color: 'var(--err)',
          fontSize: '16px',
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          Critical: Embedding Configuration Mismatch
          <span 
            className="help-icon" 
            data-tooltip="EMBEDDING_MISMATCH"
            style={{ 
              cursor: 'help',
              fontSize: '11px',
              color: 'var(--fg-muted)',
              background: 'var(--bg-elev2)',
              borderRadius: '50%',
              width: '18px',
              height: '18px',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 400,
            }}
          >
            ?
          </span>
        </h3>
        <p style={{ margin: '4px 0 0', color: 'var(--warn)', fontSize: '12px' }}>
          Search results will be completely wrong until this is fixed
        </p>
      </div>
    </div>

    {/* Comparison */}
    <div style={{
      background: 'var(--bg-elev1)',
      borderRadius: '8px',
      padding: '16px',
      marginBottom: '16px',
    }}>
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: '1fr auto 1fr',
        gap: '16px',
        alignItems: 'center',
      }}>
        {/* Current Config */}
        <div style={{
          background: 'rgba(255, 107, 107, 0.1)',
          border: '1px solid rgba(255, 107, 107, 0.3)',
          borderRadius: '8px',
          padding: '12px',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: '10px', color: 'var(--err)', marginBottom: '6px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            CURRENT CONFIG
          </div>
          <div style={{ 
            fontSize: '15px', 
            fontWeight: 700, 
            color: 'var(--fg)',
            fontFamily: 'var(--font-mono)',
          }}>
            {status.configType}/{status.configModel}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
            {status.configDim} dimensions
          </div>
        </div>

        {/* Mismatch indicator */}
        <div style={{ 
          fontSize: '24px',
          color: 'var(--err)',
          fontWeight: 700,
        }}>
          ≠
        </div>

        {/* Index */}
        <div style={{
          background: 'rgba(91, 157, 255, 0.1)',
          border: '1px solid rgba(91, 157, 255, 0.3)',
          borderRadius: '8px',
          padding: '12px',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: '10px', color: 'var(--link)', marginBottom: '6px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            YOUR INDEX
          </div>
          <div style={{ 
            fontSize: '15px', 
            fontWeight: 700, 
            color: 'var(--fg)',
            fontFamily: 'var(--font-mono)',
          }}>
            {(status.indexProvider || 'unknown')}/{status.indexType || 'unknown'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
            {status.indexDim ?? '?'} dimensions
          </div>
        </div>
      </div>

      <p style={{ 
        margin: '16px 0 0', 
        color: 'var(--fg-muted)',
        fontSize: '12px',
        lineHeight: 1.6,
      }}>
        <strong>Why this matters:</strong> Your index was created using {status.indexProvider || 'unknown'}/{status.indexType} embeddings
        ({status.indexDim} dimensions), but queries are now being embedded with {status.configType}/{status.configModel}
        ({status.configDim} dimensions). These vectors exist in incompatible mathematical spaces —
        like searching a French dictionary using Spanish words.
      </p>
    </div>

    {/* Actions */}
    {showActions && (
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        <button
          onClick={navigateToReindex}
          style={{
            flex: 1,
            minWidth: '180px',
            padding: '12px 16px',
            background: 'linear-gradient(135deg, var(--accent) 0%, #00cc66 100%)',
            border: 'none',
            borderRadius: '6px',
            color: 'var(--accent-contrast)',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.transform = 'translateY(-2px)';
            e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 255, 136, 0.3)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.transform = 'translateY(0)';
            e.currentTarget.style.boxShadow = 'none';
          }}
        >
          <span>🔄</span>
          Re-index with {status.configType}/{status.configModel}
          <span style={{ 
            fontSize: '10px', 
            opacity: 0.8,
            background: 'rgba(0,0,0,0.15)',
            padding: '2px 6px',
            borderRadius: '3px',
          }}>
            Recommended
          </span>
        </button>

        <button
          onClick={() => navigateToConfig(status.indexType)}
          style={{
            flex: 1,
            minWidth: '180px',
            padding: '12px 16px',
            background: 'var(--bg-elev2)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            color: 'var(--fg)',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'var(--bg-elev1)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'var(--bg-elev2)';
          }}
        >
          <span>↩️</span>
          Revert config to {(status.indexProvider || 'unknown')}/{status.indexType}
        </button>
      </div>
    )}

    {/* Pulse animation */}
    <style>{`
      @keyframes pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.8; transform: scale(1.05); }
      }
    `}</style>
  </div>
);

/**
 * Main EmbeddingMismatchWarning component
 * 
 * Only renders when there's an actual mismatch - returns null otherwise.
 * This ensures no false positives (per user requirement).
 */
export function EmbeddingMismatchWarning({
  variant = 'full',
  showActions = true,
  onNavigateToIndex: _onNavigateToIndex,
}: EmbeddingMismatchWarningProps) {
  const { status, loading, error, refresh } = useEmbeddingStatus();

  // Don't show anything while loading
  if (loading) {
    return null;
  }

  // Do not fail silently; unknown compatibility state is blocking.
  if (error) {
    return (
      <div
        role="alert"
        aria-live="assertive"
        style={{
          background: 'rgba(255, 170, 0, 0.1)',
          border: '1px solid var(--warn)',
          borderRadius: '8px',
          padding: '12px 16px',
          marginBottom: '16px',
          color: 'var(--fg)',
          fontSize: '12px',
        }}
      >
        <div style={{ fontWeight: 700, color: 'var(--warn)', marginBottom: '6px' }}>
          Compatibility check failed
        </div>
        <div style={{ color: 'var(--fg-muted)', marginBottom: '10px' }}>
          Retrieval/index compatibility could not be verified: {error}
        </div>
        <button
          type="button"
          onClick={() => { void refresh(); }}
          style={{
            padding: '6px 12px',
            background: 'var(--bg-elev2)',
            border: '1px solid var(--line)',
            borderRadius: '4px',
            color: 'var(--fg)',
            fontSize: '11px',
            cursor: 'pointer',
          }}
        >
          Retry check
        </button>
      </div>
    );
  }

  // CRITICAL: Only show if there's a real mismatch
  // This prevents false positives which would "explode GitHub issues"
  if (!status || !status.isMismatched) {
    return null;
  }

  // Don't show if there's no index (nothing to mismatch against)
  if (!status.hasIndex) {
    return null;
  }

  switch (variant) {
    case 'compact':
      return <CompactWarning status={status} />;
    case 'inline':
      return <InlineWarning status={status} showActions={showActions} />;
    case 'full':
    default:
      return <FullWarning status={status} showActions={showActions} />;
  }
}

/**
 * EmbeddingMatchIndicator - Shows embedding status next to Index button
 * 
 * Three states:
 * 1. No index exists → Shows "No Index" with info icon
 * 2. Embeddings match → Shows green checkmark "Embeddings OK"
 * 3. Embeddings mismatch → Handled by EmbeddingMismatchWarning (full/inline)
 */
export function EmbeddingMatchIndicator() {
  const { status, loading } = useEmbeddingStatus();

  if (loading) {
    return (
      <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
        Checking...
      </span>
    );
  }

  if (!status) {
    return null;
  }

  // No index exists yet - show helpful message for new users
  if (!status.hasIndex || status.totalChunks === 0) {
    return (
      <span
        title="No index found. Click INDEX NOW to create one."
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
          color: 'var(--fg-muted)',
          fontSize: '12px',
        }}
      >
        <span style={{ fontSize: '14px' }}>ℹ️</span>
        <span>No index yet</span>
      </span>
    );
  }

  // Mismatch is handled by the full warning component
  if (status.isMismatched) {
    return null;
  }

  // Embeddings match - show green checkmark
  return (
    <span
      data-tooltip="EMBEDDING_MATCH"
      title={`Embeddings match: ${status.configModel} (${status.configDim}d)`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        color: 'var(--ok)',
        fontSize: '12px',
        fontWeight: 600,
      }}
    >
      <span style={{ fontSize: '14px' }}>✓</span>
      <span>Embeddings OK</span>
    </span>
  );
}

export default EmbeddingMismatchWarning;
