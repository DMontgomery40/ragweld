// TriBridRAG - Help & Glossary Component
// Displays all RAG configuration parameters with search and filtering
// Dynamically reads from tooltips module - updates automatically when tooltips change

import { useMemo, useState } from 'react';
import './HelpGlossary.css';
import { useTooltips } from '@/hooks/useTooltips';

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

type GlossaryItem = TooltipData & {
  paramName: string;
  category: string;
  searchText: string;
};

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

export function HelpGlossary() {
  const [searchQuery, setSearchQuery] = useState('');
  const [currentFilter, setCurrentFilter] = useState('all');
  const { tooltips } = useTooltips();

  const allItems = useMemo((): GlossaryItem[] => {
    const items: GlossaryItem[] = [];

    for (const [paramName, html] of Object.entries(tooltips)) {
      const parsed = parseTooltipHTML(html);
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
    <div className="help-glossary-container">
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3 style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"></circle>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
          </svg>
          Help & Glossary
        </h3>
        <p style={{ color: 'var(--fg-muted)', marginBottom: '24px', lineHeight: '1.6' }}>
          Explore all RAG configuration parameters, their descriptions, and helpful links to documentation.
        </p>

        {/* Search and Filter Controls */}
        <div style={{ display: 'flex', gap: '12px', marginBottom: '24px', flexWrap: 'wrap' }}>
          <input
            type="search"
            className="glossary-search"
            placeholder="Search parameters..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <div className="glossary-category-filters">
            <button
              className={`category-filter-btn ${currentFilter === 'all' ? 'active' : ''}`}
              onClick={() => setCurrentFilter('all')}
            >
              All <span className="filter-count">{allItems.length}</span>
            </button>
            {Object.entries(CATEGORIES).map(([categoryId, category]) => {
              const count = categoryCounts[categoryId] || 0;
              if (count === 0) return null;
              return (
                <button
                  key={categoryId}
                  className={`category-filter-btn ${currentFilter === categoryId ? 'active' : ''}`}
                  onClick={() => setCurrentFilter(categoryId)}
                >
                  {category.icon} {category.title} <span className="filter-count">{count}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Glossary Grid */}
        {filteredItems.length === 0 ? (
          <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '60px 20px', color: 'var(--fg-muted)' }}>
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ margin: '0 auto 16px', opacity: 0.3 }}>
              <circle cx="11" cy="11" r="8"></circle>
              <path d="m21 21-4.35-4.35"></path>
            </svg>
            <p style={{ fontSize: '16px', marginBottom: '8px' }}>No parameters found</p>
            <p style={{ fontSize: '14px', opacity: 0.7 }}>Try a different search term or category filter</p>
          </div>
        ) : (
          <div className="glossary-grid">
            {filteredItems.map(item => {
              const categoryInfo = CATEGORIES[item.category as keyof typeof CATEGORIES] || CATEGORIES.advanced;
              return (
                <div key={item.paramName} className="glossary-card" data-category={item.category}>
                  <div className="glossary-card-header">
                    <div className="glossary-card-title">
                      <span className="glossary-icon">{categoryInfo.icon}</span>
                      <strong>{item.title}</strong>
                    </div>
                    <code className="glossary-param-name">{item.paramName}</code>
                  </div>
                  {item.badges.length > 0 && (
                    <div className="glossary-badges">
                      {item.badges.map((badge, idx) => (
                        <span key={idx} className={`glossary-badge ${badge.class}`}>
                          {badge.text}
                        </span>
                      ))}
                    </div>
                  )}
                  <p className="glossary-body">{item.body}</p>
                  {item.links.length > 0 && (
                    <div className="glossary-links">
                      {item.links.map((link, idx) => (
                        <a
                          key={idx}
                          href={link.href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="glossary-link"
                        >
                          {link.text}
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
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
      </div>
    </div>
  );
}
