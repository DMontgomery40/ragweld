import { useCallback, useEffect, useRef } from 'react';
import { useGlobalSearch } from '@/hooks/useGlobalSearch';

export function GlobalSearch() {
  const {
    isOpen,
    setIsOpen,
    query,
    results,
    indexError,
    cursor: selectedIndex,
    setCursor,
    search,
    navigateToResult,
    handleKeyDown
  } = useGlobalSearch();

  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);

  // Focus input when modal opens; hand focus back to the trigger when it closes, so a
  // keyboard user is not dropped at the top of the document (M-136).
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
      wasOpen.current = true;
      return;
    }
    if (!isOpen && wasOpen.current) {
      wasOpen.current = false;
      triggerRef.current?.focus();
    }
  }, [isOpen]);

  // Focus trap. Tabbing used to walk straight out of the open dialog and light up the
  // sidebar behind it; nothing brought focus back (M-136).
  const trapFocus = useCallback((e: React.KeyboardEvent) => {
    if (e.key !== 'Tab') return;
    const root = modalRef.current;
    if (!root) return;
    const focusable = Array.from(
      root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
    ).filter((el) => el.offsetParent !== null || el === document.activeElement);
    e.preventDefault();
    if (focusable.length === 0) return;
    const current = focusable.indexOf(document.activeElement as HTMLElement);
    const next = e.shiftKey
      ? (current <= 0 ? focusable.length - 1 : current - 1)
      : (current === -1 || current === focusable.length - 1 ? 0 : current + 1);
    focusable[next]?.focus();
  }, []);

  const activeOptionId = results[selectedIndex]
    ? `global-search-option-${selectedIndex}`
    : undefined;

  const highlightText = (text: string, query: string) => {
    if (!query) return text;
    const safe = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${safe})`, 'gi');
    const parts = text.split(regex);
    return parts.map((part, i) =>
      i % 2 === 1 ? (
        <span key={i} style={{ background: 'var(--accent)', color: 'white', padding: '0 2px', borderRadius: '2px' }}>
          {part}
        </span>
      ) : (
        part
      )
    );
  };

  return (
    <>
      {/* Topbar trigger input (keeps the old layout, opens the modal) */}
      <input
        ref={triggerRef}
        id="global-search"
        type="search"
        placeholder="Search settings (Ctrl+K)"
        value={query}
        readOnly
        // Deliberately NOT onFocus: tabbing across the top bar used to pop the modal open
        // the moment this box received focus, which made the top bar untraversable by
        // keyboard (M-136). It opens on a click, on Enter/Space, and on Ctrl+K.
        onClick={() => setIsOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsOpen(true);
          }
        }}
        style={{ cursor: 'pointer' }}
        aria-label="Open global search"
        aria-haspopup="dialog"
      />

      {isOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Global search"
          onClick={() => setIsOpen(false)}
          style={{
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
          }}
        >
          <div
            ref={modalRef}
            className="global-search-modal"
            onKeyDown={trapFocus}
            onClick={(e) => e.stopPropagation()}
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
                  onKeyDown={handleKeyDown as any}
                  role="combobox"
                  aria-label="Search all settings"
                  aria-expanded={results.length > 0}
                  // Only while the listbox exists: an empty query renders none, and a
                  // dangling reference is worse than no reference.
                  aria-controls={results.length > 0 ? 'global-search-listbox' : undefined}
                  aria-activedescendant={activeOptionId}
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
          <>
            <div
              data-testid="global-search-count"
              aria-live="polite"
              style={{
                padding: '8px 20px',
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--fg-muted)',
                borderBottom: '1px solid var(--line)',
              }}
            >
              {results.length === 1 ? '1 result' : `${results.length} results`}
            </div>
          <div
            id="global-search-listbox"
            role="listbox"
            aria-label="Search results"
            style={{
            maxHeight: '400px',
            overflowY: 'auto'
          }}>
            {results.map((result, index) => (
              <div
                key={`${result.kind}:${result.id}`}
                id={`global-search-option-${index}`}
                role="option"
                aria-selected={index === selectedIndex}
                onClick={() => navigateToResult(result)}
                onMouseEnter={() => setCursor(index)}
                data-testid="global-search-result"
                data-kind={result.kind}
                data-path={result.path}
                style={{
                  padding: '12px 20px',
                  borderBottom: '1px solid var(--line)',
                  cursor: 'pointer',
                  background: index === selectedIndex ? 'var(--bg-elev1)' : 'transparent',
                  transition: 'background 0.15s'
                }}
              >
                <div
                  data-testid="global-search-result-title"
                  style={{
                  fontSize: '14px',
                  fontWeight: 600,
                  marginBottom: '4px',
                  color: 'var(--fg)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  {highlightText(result.label, query)}
                  <span style={{
                    fontSize: '11.5px',
                    fontWeight: 700,
                    color: 'var(--fg-muted)',
                    border: '1px solid var(--line)',
                    borderRadius: '999px',
                    padding: '1px 7px',
                    letterSpacing: '0.04em',
                    textTransform: 'uppercase'
                  }}>
                    {result.kind === 'control' ? 'on this page' : 'config'}
                  </span>
                </div>
                <div style={{
                  fontSize: '12.5px',
                  color: 'var(--fg-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  flexWrap: 'wrap'
                }}>
                  <span>{highlightText(result.location, query)}</span>
                  {result.path && result.path !== result.label ? (
                    <>
                      <span>•</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                        {highlightText(result.path, query)}
                      </span>
                    </>
                  ) : null}
                </div>
                {result.description ? (
                  <div style={{ fontSize: '12.5px', color: 'var(--fg-muted)', marginTop: '4px', lineHeight: 1.4 }}>
                    {highlightText(result.description.length > 160 ? `${result.description.slice(0, 157)}…` : result.description, query)}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
          </>
        )}

        {indexError ? (
          <div style={{ padding: '10px 20px', fontSize: '12.5px', color: 'var(--err)' }} role="alert">
            Config registry unavailable: {indexError}
          </div>
        ) : null}

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
      )}
    </>
  );
}
