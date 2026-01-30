/**
 * KeywordsService - Discriminative Keywords Management
 * Converted from /web/src/modules/keywords.js
 *
 * Handles loading and managing keyword catalogs
 */

export interface KeywordsCatalog {
  keywords: string[];
  [key: string]: any;
}

export class KeywordsService {
  private apiBase: string;

  constructor(apiBase: string) {
    this.apiBase = apiBase;
  }

  /**
   * Load keywords catalog
   */
  async loadKeywords(): Promise<KeywordsCatalog> {
    const response = await fetch(`${this.apiBase}/api/keywords`);
    if (!response.ok) {
      throw new Error('Failed to load keywords');
    }
    return await response.json();
  }

  /**
   * Filter keywords by category and search term
   */
  filterKeywords(
    catalog: KeywordsCatalog,
    category: string = 'all',
    filter: string = '',
    excludeSet: Set<string> = new Set()
  ): string[] {
    let base = category === 'all' ? (catalog.keywords || []) : (catalog[category] || []);
    const f = filter.toLowerCase();

    return base
      .filter(k => !excludeSet.has(k) && (!f || k.toLowerCase().includes(f)))
      .slice(0, 500);
  }
}
