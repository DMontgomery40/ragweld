import { useCallback, useEffect, useMemo, useState } from 'react';

type CardItem = {
  file_path: string;
  start_line?: number;
  purpose?: string;
  symbols?: string[];
  technical_details?: string;
  domain_concepts?: string[];
};

type CardsResponse = {
  cards?: CardItem[];
  last_build?: {
    started_at?: string;
    result?: {
      cards_written?: number;
      duration_s?: number;
    };
  };
};

type Props = {
  api: (path: string) => string;
};

declare global {
  interface Window {
    Cards?: {
      load?: () => Promise<void> | void;
      refresh?: () => Promise<void> | void;
      jumpToLine?: (filePath: string, lineNumber?: number) => void;
    };
  }
}

export function CardsViewer({ api }: Props) {
  const [baseCards, setBaseCards] = useState<CardItem[]>([]);
  const [visibleCards, setVisibleCards] = useState<CardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchValue, setSearchValue] = useState('');
  const [allCardsCache, setAllCardsCache] = useState<CardItem[] | null>(null);
  const [lastBuildLabel, setLastBuildLabel] = useState('—');
  const [rawModalOpen, setRawModalOpen] = useState(false);
  const [rawModalContent, setRawModalContent] = useState('');
  const [rawModalLoading, setRawModalLoading] = useState(false);

  const formatLastBuild = (payload?: CardsResponse['last_build']) => {
    if (!payload || !payload.started_at) return 'No builds yet';
    const when = new Date(payload.started_at).toLocaleString();
    const count =
      payload.result && typeof payload.result.cards_written === 'number'
        ? ` • ${payload.result.cards_written} updated`
        : '';
    const dur =
      payload.result && typeof payload.result.duration_s === 'number'
        ? ` • ${payload.result.duration_s}s`
        : '';
    return `Last build: ${when}${count}${dur}`;
  };

  const loadCards = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(api('cards'));
      if (!response.ok) {
        throw new Error(`Failed to load cards (${response.status})`);
      }
      const data: CardsResponse = await response.json();
      const cards = Array.isArray(data.cards) ? data.cards : [];
      setBaseCards(cards);
      setVisibleCards(cards);
      setLastBuildLabel(formatLastBuild(data.last_build));
      setSearchValue('');
      setAllCardsCache(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to load cards';
      setError(message);
      setBaseCards([]);
      setVisibleCards([]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    loadCards();
  }, [loadCards]);

  useEffect(() => {
    const refreshHandler = () => {
      loadCards();
    };
    window.addEventListener('agro:cards:refresh', refreshHandler);
    return () => window.removeEventListener('agro:cards:refresh', refreshHandler);
  }, [loadCards]);

  const ensureAllCards = useCallback(async () => {
    if (allCardsCache) {
      return allCardsCache;
    }
    try {
      const response = await fetch(api('cards/all'));
      if (!response.ok) {
        throw new Error(`Failed to load all cards (${response.status})`);
      }
      const data = await response.json();
      const cards = Array.isArray(data.cards) ? data.cards : [];
      setAllCardsCache(cards);
      return cards;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to load cards';
      setError(message);
      return [];
    }
  }, [api, allCardsCache]);

  const handleSearchChange = useCallback(
    async (value: string) => {
      setSearchValue(value);
      if (!value.trim()) {
        setVisibleCards(baseCards);
        return;
      }
      const dataset = await ensureAllCards();
      if (dataset.length === 0) {
        setVisibleCards([]);
        return;
      }
      const query = value.trim().toLowerCase();
      const filtered = dataset
        .filter((card) => {
          const haystack = [
            card.purpose || '',
            card.technical_details || '',
            Array.isArray(card.domain_concepts) ? card.domain_concepts.join(' ') : '',
            card.file_path || '',
            Array.isArray(card.symbols) ? card.symbols.join(' ') : '',
          ]
            .join(' ')
            .toLowerCase();
          return haystack.includes(query);
        })
        .slice(0, 100);
      setVisibleCards(filtered);
    },
    [baseCards, ensureAllCards]
  );

  const handleViewAll = useCallback(async () => {
    setRawModalOpen(true);
    setRawModalLoading(true);
    try {
      const response = await fetch(api('cards/raw-text'));
      if (!response.ok) {
        throw new Error(`Failed to load raw cards (${response.status})`);
      }
      const text = await response.text();
      setRawModalContent(text);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to load raw cards';
      setRawModalContent(`Error: ${message}`);
    } finally {
      setRawModalLoading(false);
    }
  }, [api]);

  const showNavigationToast = (filePath: string, lineNumber: number) => {
    const notification = document.createElement('div');
    notification.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: var(--bg-elev2);
      border: 1px solid var(--accent);
      padding: 12px 16px;
      border-radius: 6px;
      color: var(--fg);
      font-size: 13px;
      z-index: 10000;
      animation: slideInRight 0.3s ease;
    `;
    notification.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="color:var(--accent);">📍</span>
        <span>Navigate to: <strong style="color:var(--link);">${filePath}:${lineNumber}</strong></span>
      </div>
    `;
    document.body.appendChild(notification);
    setTimeout(() => {
      notification.remove();
    }, 3000);
  };

  const handleCardClick = useCallback(
    (card: CardItem) => {
      const line = card.start_line || 1;
      window.dispatchEvent(
        new CustomEvent('cardNavigation', {
          detail: { file: card.file_path, line },
        })
      );
      showNavigationToast(card.file_path || 'Unknown file', line);
    },
    []
  );

  const cardsContent = useMemo(() => {
    if (loading) {
      return (
        <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
          Loading cards...
        </div>
      );
    }
    if (error) {
      return (
        <div style={{ textAlign: 'center', padding: '24px', color: 'var(--err)' }}>{error}</div>
      );
    }
    if (visibleCards.length === 0) {
      return (
        <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
          No cards available
        </div>
      );
    }
    return (
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          gap: '16px',
        }}
      >
        {visibleCards.map((card) => (
          <button
            key={`${card.file_path || 'card'}-${card.start_line || 0}`}
            type="button"
            onClick={() => handleCardClick(card)}
            style={{
              textAlign: 'left',
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              padding: '16px',
              cursor: 'pointer',
              minHeight: '180px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              transition: 'all 0.2s ease',
            }}
          >
            <div>
              <h4 style={{ margin: '0 0 8px 0', color: 'var(--accent)', fontSize: '14px' }}>
                {(card.symbols && card.symbols[0]) ||
                  (card.file_path || '').split('/').slice(-1)[0] ||
                  'Unknown'}
              </h4>
              <p
                style={{
                  margin: 0,
                  color: 'var(--fg-muted)',
                  fontSize: '12px',
                  lineHeight: 1.4,
                  display: '-webkit-box',
                  WebkitLineClamp: 3,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                }}
              >
                {card.purpose || 'No description available'}
              </p>
            </div>
            <div style={{ fontSize: '10px', color: 'var(--fg-muted)', wordBreak: 'break-all' }}>
              <span style={{ color: 'var(--link)' }}>{card.file_path || 'Unknown file'}</span>
              {card.start_line ? ` : ${card.start_line}` : ''}
            </div>
          </button>
        ))}
      </div>
    );
  }, [loading, error, visibleCards, handleCardClick]);

  useEffect(() => {
    const viewAllHandler = () => {
      handleViewAll();
    };
    window.addEventListener('agro:cards:view-all', viewAllHandler);

    const shim = {
      load: () => loadCards(),
      refresh: () => loadCards(),
      jumpToLine: (filePath: string, lineNumber: number = 1) => showNavigationToast(filePath, lineNumber),
    };
    window.Cards = shim;

    return () => {
      window.removeEventListener('agro:cards:view-all', viewAllHandler);
      if (window.Cards === shim) {
        delete window.Cards;
      }
    };
  }, [handleViewAll, loadCards]);

  return (
    <div className="settings-section" id="cards-viewer-container">
      <div
        style={{
          display: 'flex',
          gap: '12px',
          alignItems: 'center',
          marginBottom: '12px',
        }}
      >
        <div>
          <h4 style={{ margin: 0 }}>Code Cards</h4>
          <div className="mono" style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
            {lastBuildLabel}
          </div>
        </div>
        <input
          type="search"
          value={searchValue}
          placeholder="Search cards..."
          onChange={(e) => handleSearchChange(e.target.value)}
          style={{
            flex: 1,
            minWidth: '200px',
            padding: '8px 12px',
            borderRadius: '6px',
            border: '1px solid var(--line)',
            background: 'var(--bg-elev1)',
            color: 'var(--fg)',
          }}
        />
      </div>
      <div
        id="cards-viewer"
        style={{
          maxHeight: '400px',
          overflowY: 'auto',
          fontFamily: "'SF Mono', monospace",
          fontSize: '12px',
        }}
      >
        {cardsContent}
      </div>

      {rawModalOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.8)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
            zIndex: 10000,
          }}
          onClick={() => setRawModalOpen(false)}
        >
          <div
            style={{
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              width: '100%',
              maxWidth: '90%',
              maxHeight: '85vh',
              display: 'flex',
              flexDirection: 'column',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                padding: '12px 16px',
                borderBottom: '1px solid var(--line)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                background: 'var(--bg-elev2)',
              }}
            >
              <strong style={{ color: 'var(--accent)' }}>📋 All Cards Raw Data</strong>
              <button
                type="button"
                onClick={() => setRawModalOpen(false)}
                style={{
                  padding: '4px 8px',
                  background: 'var(--accent)',
                  color: 'var(--code-bg)',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '11px',
                  fontWeight: 600,
                }}
              >
                Close
              </button>
            </div>
            <div
              style={{
                flex: 1,
                overflowY: 'auto',
                padding: '16px',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                fontFamily: "'SF Mono', monospace",
                color: 'var(--fg)',
                fontSize: '12px',
              }}
            >
              {rawModalLoading ? 'Loading raw cards...' : rawModalContent}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}


