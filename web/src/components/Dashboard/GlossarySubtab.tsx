// AGRO - Glossary Subtab
// Searchable glossary of all RAG configuration parameters
// Uses useTooltips hook (Zustand) which loads from tooltips.js - SINGLE SOURCE OF TRUTH

import { useState, useMemo } from 'react';
import { useTooltips } from '@/hooks/useTooltips';
import './HelpGlossary.css';

// Category definitions for organizing tooltips
const CATEGORIES = {
  infrastructure: {
    title: 'Infrastructure',
    icon: '🔧',
    keywords: ['QDRANT', 'REDIS', 'REPO', 'COLLECTION', 'OUT_DIR', 'MCP', 'DOCKER']
  },
  models: {
    title: 'Models & Providers',
    icon: '🤖',
    keywords: ['MODEL', 'OPENAI', 'ANTHROPIC', 'GOOGLE', 'OLLAMA', 'VOYAGE', 'COHERE', 'API_KEY', 'EMBEDDING']
  },
  retrieval: {
    title: 'Retrieval & Search',
    icon: '🔍',
    keywords: ['TOPK', 'FINAL_K', 'HYBRID', 'ALPHA', 'BM25', 'DENSE', 'SEARCH', 'QUERY']
  },
  reranking: {
    title: 'Reranking',
    icon: '🎯',
    keywords: ['RERANK', 'CROSS_ENCODER', 'LEARNING_RANKER', 'TRAINING']
  },
  evaluation: {
    title: 'Evaluation',
    icon: '📊',
    keywords: ['EVAL', 'GOLDEN', 'BASELINE', 'METRICS']
  },
  advanced: {
    title: 'Advanced',
    icon: '⚙️',
    keywords: ['CUSTOM', 'BOOST', 'LAYER', 'CONTEXT', 'STOP_WORDS', 'MAX_QUERY_REWRITES']
  }
};

interface TooltipData {
  title: string;
  body: string;
  links: Array<{ text: string; href: string }>;
  badges: Array<{ text: string; class: string }>;
}

interface GlossaryItem extends TooltipData {
  paramName: string;
  category: string;
  searchText: string;
}

// Parse tooltip HTML to extract structured data
function parseTooltipHTML(html: string): TooltipData {
  const div = document.createElement('div');
  div.innerHTML = html;

  const titleEl = div.querySelector('.tt-title');
  const linksEl = div.querySelector('.tt-links');
  const badgesEl = div.querySelector('.tt-badges');

  // Get body text
  const cloned = div.cloneNode(true) as HTMLElement;
  cloned.querySelector('.tt-title')?.remove();
  cloned.querySelector('.tt-links')?.remove();
  cloned.querySelector('.tt-badges')?.remove();
  const body = cloned.textContent?.trim() || '';

  const links = linksEl
    ? Array.from(linksEl.querySelectorAll('a')).map(a => ({
        text: a.textContent || '',
        href: a.href
      }))
    : [];

  const badges = badgesEl
    ? Array.from(badgesEl.querySelectorAll('.tt-badge')).map(badge => ({
        text: badge.textContent || '',
        class: badge.className.replace('tt-badge', '').trim()
      }))
    : [];

  return {
    title: titleEl?.textContent || '',
    body,
    links,
    badges
  };
}

// Categorize tooltip based on parameter name
function categorizeTooltip(paramName: string): string {
  const upperName = paramName.toUpperCase();
  for (const [categoryId, category] of Object.entries(CATEGORIES)) {
    if (category.keywords.some(keyword => upperName.includes(keyword))) {
      return categoryId;
    }
  }
  return 'advanced'; // Default category
}

export function GlossarySubtab() {
  const [searchQuery, setSearchQuery] = useState('');
  const [currentFilter, setCurrentFilter] = useState('all');

  // SINGLE SOURCE OF TRUTH: useTooltips hook loads from Zustand store
  // which reads from window.Tooltips.buildTooltipMap() (tooltips.js)
  const { tooltips, loading } = useTooltips();

  // Build glossary items from tooltips
  const allItems = useMemo(() => {
    if (Object.keys(tooltips).length === 0) {
      return [];
    }

    const items: GlossaryItem[] = [];

    for (const [paramName, html] of Object.entries(tooltips)) {
      const parsed = parseTooltipHTML(html as string);
      const category = categorizeTooltip(paramName);

      items.push({
        paramName,
        category,
        ...parsed,
        searchText: `${paramName} ${parsed.title} ${parsed.body}`.toLowerCase()
      });
    }

    // Sort by category, then title
    items.sort((a, b) => {
      const catOrder = Object.keys(CATEGORIES);
      const catCompare = catOrder.indexOf(a.category) - catOrder.indexOf(b.category);
      if (catCompare !== 0) return catCompare;
      return a.title.localeCompare(b.title);
    });

    return items;
  }, [tooltips]);

  // Filter items
  const filteredItems = useMemo(() => {
    let items = allItems;

    // Apply category filter
    if (currentFilter !== 'all') {
      items = items.filter(item => item.category === currentFilter);
    }

    // Apply search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      items = items.filter(item => item.searchText.includes(query));
    }

    return items;
  }, [allItems, currentFilter, searchQuery]);

  // Calculate category counts
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    allItems.forEach(item => {
      counts[item.category] = (counts[item.category] || 0) + 1;
    });
    return counts;
  }, [allItems]);

  return (
    <div
      id="tab-dashboard-glossary"
      className="dashboard-subtab"
      style={{ display: 'flex', flexDirection: 'column' }}
    >
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3 style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
          </svg>
          Parameter Glossary
        </h3>
        <p style={{ color: 'var(--fg-muted)', marginBottom: '24px', lineHeight: '1.6' }}>
          Searchable reference for all RAG configuration parameters, their descriptions, and helpful links to documentation.
        </p>

        {loading ? (
          <div
            style={{
              padding: '60px',
              textAlign: 'center',
              color: 'var(--fg-muted)',
              background: 'var(--card-bg)',
              borderRadius: '8px',
              border: '1px solid var(--line)'
            }}
          >
            <div
              style={{
                width: '48px',
                height: '48px',
                border: '3px solid var(--line)',
                borderTopColor: 'var(--accent)',
                borderRadius: '50%',
                animation: 'spin 1s linear infinite',
                margin: '0 auto 16px'
              }}
            />
            Loading glossary...
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          </div>
        ) : allItems.length === 0 ? (
          <div
            style={{
              padding: '60px',
              textAlign: 'center',
              color: 'var(--fg-muted)',
              background: 'var(--card-bg)',
              borderRadius: '8px',
              border: '1px solid var(--line)'
            }}
          >
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>📚</div>
            <div style={{ fontSize: '14px' }}>
              Tooltips module not yet loaded. Glossary will appear when tooltips are available.
            </div>
          </div>
        ) : (
          <>
            {/* Search and Filter Controls */}
            <div style={{ display: 'flex', gap: '12px', marginBottom: '24px', flexWrap: 'wrap' }}>
              <input
                type="search"
                className="glossary-search"
                placeholder="Search parameters..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  flex: '1 1 300px',
                  padding: '10px 14px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '6px',
                  color: 'var(--fg)',
                  fontSize: '13px'
                }}
              />
              <div className="glossary-category-filters" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button
                  className={`category-filter-btn ${currentFilter === 'all' ? 'active' : ''}`}
                  onClick={() => setCurrentFilter('all')}
                  style={{
                    padding: '8px 14px',
                    background: currentFilter === 'all' ? 'var(--accent)' : 'var(--bg-elev2)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: currentFilter === 'all' ? 'var(--accent-contrast)' : 'var(--fg)',
                    fontSize: '12px',
                    fontWeight: '600',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease'
                  }}
                >
                  All <span className="filter-count">({allItems.length})</span>
                </button>
                {Object.entries(CATEGORIES).map(([categoryId, category]) => {
                  const count = categoryCounts[categoryId] || 0;
                  if (count === 0) return null;
                  return (
                    <button
                      key={categoryId}
                      className={`category-filter-btn ${currentFilter === categoryId ? 'active' : ''}`}
                      onClick={() => setCurrentFilter(categoryId)}
                      style={{
                        padding: '8px 14px',
                        background: currentFilter === categoryId ? 'var(--accent)' : 'var(--bg-elev2)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: currentFilter === categoryId ? 'var(--accent-contrast)' : 'var(--fg)',
                        fontSize: '12px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        transition: 'all 0.2s ease'
                      }}
                    >
                      {category.icon} {category.title} <span className="filter-count">({count})</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Glossary Grid */}
            {filteredItems.length === 0 ? (
              <div
                style={{
                  gridColumn: '1 / -1',
                  textAlign: 'center',
                  padding: '60px 20px',
                  color: 'var(--fg-muted)',
                  background: 'var(--card-bg)',
                  borderRadius: '8px',
                  border: '1px solid var(--line)'
                }}
              >
                <svg
                  width="64"
                  height="64"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  style={{ margin: '0 auto 16px', opacity: 0.3 }}
                >
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.35-4.35" />
                </svg>
                <p style={{ fontSize: '16px', marginBottom: '8px' }}>No parameters found</p>
                <p style={{ fontSize: '14px', opacity: 0.7 }}>Try a different search term or category filter</p>
              </div>
            ) : (
              <div className="glossary-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', gap: '16px' }}>
                {filteredItems.map(item => {
                  const categoryInfo = CATEGORIES[item.category as keyof typeof CATEGORIES] || CATEGORIES.advanced;
                  return (
                    <div
                      key={item.paramName}
                      className="glossary-card"
                      data-category={item.category}
                      style={{
                        background: 'var(--card-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '8px',
                        padding: '16px',
                        transition: 'all 0.2s ease'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = 'var(--accent)';
                        e.currentTarget.style.transform = 'translateY(-2px)';
                        e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.2)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = 'var(--line)';
                        e.currentTarget.style.transform = 'translateY(0)';
                        e.currentTarget.style.boxShadow = 'none';
                      }}
                    >
                      <div className="glossary-card-header" style={{ marginBottom: '12px' }}>
                        <div
                          className="glossary-card-title"
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            marginBottom: '8px'
                          }}
                        >
                          <span className="glossary-icon" style={{ fontSize: '20px' }}>
                            {categoryInfo.icon}
                          </span>
                          <strong style={{ fontSize: '14px', color: 'var(--accent)' }}>{item.title}</strong>
                        </div>
                        <code
                          className="glossary-param-name"
                          style={{
                            display: 'block',
                            fontSize: '11px',
                            color: 'var(--link)',
                            background: 'var(--code-bg)',
                            padding: '4px 8px',
                            borderRadius: '4px',
                            fontFamily: "'SF Mono', monospace"
                          }}
                        >
                          {item.paramName}
                        </code>
                      </div>
                      {item.badges.length > 0 && (
                        <div className="glossary-badges" style={{ display: 'flex', gap: '6px', marginBottom: '12px', flexWrap: 'wrap' }}>
                          {item.badges.map((badge, idx) => (
                            <span
                              key={idx}
                              className={`glossary-badge ${badge.class}`}
                              style={{
                                padding: '2px 8px',
                                fontSize: '9px',
                                fontWeight: '600',
                                borderRadius: '3px',
                                background: 'var(--warn)',
                                color: '#000',
                                textTransform: 'uppercase',
                                letterSpacing: '0.3px'
                              }}
                            >
                              {badge.text}
                            </span>
                          ))}
                        </div>
                      )}
                      <p className="glossary-body" style={{ margin: '0 0 12px 0', fontSize: '12px', lineHeight: '1.6', color: 'var(--fg-muted)' }}>
                        {item.body}
                      </p>
                      {item.links.length > 0 && (
                        <div className="glossary-links" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          {item.links.map((link, idx) => (
                            <a
                              key={idx}
                              href={link.href}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="glossary-link"
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '6px',
                                fontSize: '11px',
                                color: 'var(--link)',
                                textDecoration: 'none',
                                transition: 'color 0.2s ease'
                              }}
                              onMouseEnter={(e) => {
                                e.currentTarget.style.color = 'var(--accent)';
                              }}
                              onMouseLeave={(e) => {
                                e.currentTarget.style.color = 'var(--link)';
                              }}
                            >
                              {link.text}
                              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                                <polyline points="15 3 21 3 21 9" />
                                <line x1="10" y1="14" x2="21" y2="3" />
                              </svg>
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
