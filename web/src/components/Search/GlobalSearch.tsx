import React, { useEffect, useRef } from 'react';
import { useGlobalSearch } from '@/hooks/useGlobalSearch';

export function GlobalSearch() {
  const {
    isOpen,
    query,
    results,
    selectedIndex,
    search,
    navigateToResult
  } = useGlobalSearch();

  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input when modal opens
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  if (!isOpen) {
    return null;
  }

  const highlightText = (text: string, query: string) => {
    if (!query) return text;
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    const parts = text.split(regex);
    return parts.map((part, i) =>
      regex.test(part) ? (
        <span key={i} style={{ background: 'var(--accent)', color: 'white', padding: '0 2px', borderRadius: '2px' }}>
          {part}
        </span>
      ) : (
        part
      )
    );
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.6)',
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'center',
      padding: '10vh 20px',
      zIndex: 9999
    }}>
      <div
        className="global-search-modal"
        style={{
          width: '100%',
          maxWidth: '600px',
          background: 'var(--bg-elev2)',
          borderRadius: '12px',
          boxShadow: '0 20px 60px rgba(0, 0, 0, 0.4)',
          overflow: 'hidden',
          border: '1px solid var(--line)'
        }}
      >
        {/* Search Input */}
        <div style={{ padding: '20px', borderBottom: '1px solid var(--line)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--fg-muted)' }}>
              <circle cx="11" cy="11" r="8"></circle>
              <path d="m21 21-4.35-4.35"></path>
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => search(e.target.value)}
              placeholder="Search all settings... (Ctrl+K)"
              style={{
                flex: 1,
                border: 'none',
                outline: 'none',
                background: 'transparent',
                color: 'var(--fg)',
                fontSize: '16px',
                fontFamily: 'inherit'
              }}
            />
            <kbd style={{
              padding: '4px 8px',
              background: 'var(--bg-elev1)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              fontSize: '11px',
              color: 'var(--fg-muted)',
              fontFamily: 'monospace'
            }}>
              ESC
            </kbd>
          </div>
        </div>

        {/* Results */}
        {results.length > 0 && (
          <div style={{
            maxHeight: '400px',
            overflowY: 'auto'
          }}>
            {results.map((result, index) => (
              <div
                key={`${result.name}-${index}`}
                onClick={() => navigateToResult(result)}
                style={{
                  padding: '12px 20px',
                  borderBottom: '1px solid var(--line)',
                  cursor: 'pointer',
                  background: index === selectedIndex ? 'var(--bg-elev1)' : 'transparent',
                  transition: 'background 0.15s'
                }}
                onMouseEnter={() => {
                  // Update selected index on hover for keyboard navigation
                }}
              >
                <div style={{
                  fontSize: '14px',
                  fontWeight: 500,
                  marginBottom: '4px',
                  color: 'var(--fg)'
                }}>
                  {highlightText(result.label || result.name, query)}
                </div>
                <div style={{
                  fontSize: '12px',
                  color: 'var(--fg-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  {result.title && (
                    <>
                      <span>{highlightText(result.title, query)}</span>
                      <span>•</span>
                    </>
                  )}
                  {result.name && result.name !== result.label && (
                    <span style={{ fontFamily: 'monospace', fontSize: '11px' }}>
                      {highlightText(result.name, query)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {query && results.length === 0 && (
          <div style={{
            padding: '40px 20px',
            textAlign: 'center',
            color: 'var(--fg-muted)',
            fontSize: '14px'
          }}>
            <div style={{ marginBottom: '8px', fontSize: '32px' }}>🔍</div>
            <div>No results found for "{query}"</div>
            <div style={{ fontSize: '12px', marginTop: '8px' }}>
              Try searching for a different term
            </div>
          </div>
        )}

        {/* Help Text */}
        {!query && (
          <div style={{
            padding: '20px',
            color: 'var(--fg-muted)',
            fontSize: '13px',
            textAlign: 'center'
          }}>
            <div style={{ marginBottom: '12px' }}>
              Search through all 600+ settings
            </div>
            <div style={{ display: 'flex', justifyContent: 'center', gap: '12px', fontSize: '11px' }}>
              <div>
                <kbd style={{
                  padding: '2px 6px',
                  background: 'var(--bg-elev1)',
                  border: '1px solid var(--line)',
                  borderRadius: '3px',
                  fontFamily: 'monospace'
                }}>↑</kbd>
                <kbd style={{
                  padding: '2px 6px',
                  background: 'var(--bg-elev1)',
                  border: '1px solid var(--line)',
                  borderRadius: '3px',
                  fontFamily: 'monospace',
                  marginLeft: '2px'
                }}>↓</kbd>
                {' '}navigate
              </div>
              <div>
                <kbd style={{
                  padding: '2px 6px',
                  background: 'var(--bg-elev1)',
                  border: '1px solid var(--line)',
                  borderRadius: '3px',
                  fontFamily: 'monospace'
                }}>↵</kbd>
                {' '}select
              </div>
              <div>
                <kbd style={{
                  padding: '2px 6px',
                  background: 'var(--bg-elev1)',
                  border: '1px solid var(--line)',
                  borderRadius: '3px',
                  fontFamily: 'monospace'
                }}>ESC</kbd>
                {' '}close
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
