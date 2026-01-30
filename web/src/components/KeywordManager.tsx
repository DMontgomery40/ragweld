import { useState, useEffect, useMemo } from 'react';
import { useConfigStore } from '@/stores';
import type { Repository } from '@web/types';

interface KeywordManagerProps {
  repo: Repository;
}

export function KeywordManager({ repo }: KeywordManagerProps) {
  const { keywordsCatalog, loadKeywords, addKeyword, updateRepo } = useConfigStore();

  const [filterText, setFilterText] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'all' | 'discriminative' | 'semantic' | 'llm' | 'repos'>('all');
  const [selectedAvailable, setSelectedAvailable] = useState<string[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string[]>([]);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newKeyword, setNewKeyword] = useState('');
  const [newKeywordCategory, setNewKeywordCategory] = useState<'' | 'discriminative' | 'semantic'>('');

  // Load keywords catalog on mount
  useEffect(() => {
    if (!keywordsCatalog) {
      loadKeywords();
    }
  }, [keywordsCatalog, loadKeywords]);

  // Current repo keywords
  const repoKeywords = useMemo(() => repo.keywords || [], [repo.keywords]);

  // Available keywords (filtered and excluding repo keywords)
  const availableKeywords = useMemo(() => {
    if (!keywordsCatalog) return [];

    const repoKeywordSet = new Set(repoKeywords);

    let baseList: string[] = [];
    if (sourceFilter === 'all') {
      baseList = keywordsCatalog.keywords || [];
    } else {
      baseList = keywordsCatalog[sourceFilter] || [];
    }

    // Filter out keywords already in repo
    let filtered = baseList.filter(kw => !repoKeywordSet.has(kw));

    // Apply text filter
    if (filterText) {
      const searchLower = filterText.toLowerCase();
      filtered = filtered.filter(kw => kw.toLowerCase().includes(searchLower));
    }

    // Limit to 500 for performance
    return filtered.slice(0, 500);
  }, [keywordsCatalog, sourceFilter, filterText, repoKeywords]);

  const handleAddToRepo = async () => {
    if (selectedAvailable.length === 0) return;

    const updatedKeywords = Array.from(new Set([...repoKeywords, ...selectedAvailable]));
    await updateRepo(repo.name, { keywords: updatedKeywords });
    setSelectedAvailable([]);
  };

  const handleRemoveFromRepo = async () => {
    if (selectedRepo.length === 0) return;

    const removeSet = new Set(selectedRepo);
    const updatedKeywords = repoKeywords.filter(kw => !removeSet.has(kw));
    await updateRepo(repo.name, { keywords: updatedKeywords });
    setSelectedRepo([]);
  };

  const handleAddNewKeyword = async () => {
    if (!newKeyword.trim()) return;

    try {
      await addKeyword(newKeyword.trim(), newKeywordCategory || undefined);
      setShowAddDialog(false);
      setNewKeyword('');
      setNewKeywordCategory('');
    } catch (error) {
      console.error('Failed to add keyword:', error);
      alert(`Failed to add keyword: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  return (
    <div className="input-group full-width" style={{ marginTop: '12px' }}>
      <label>Keyword Manager</label>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '8px', alignItems: 'center' }}>
        {/* Available Keywords Panel */}
        <div>
          <div style={{ display: 'flex', gap: '6px', marginBottom: '6px' }}>
            <input
              type="text"
              placeholder="filter..."
              style={{ width: '60%' }}
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
            />
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value as any)}
            >
              <option value="all">All</option>
              <option value="discriminative">Discriminative</option>
              <option value="semantic">Semantic</option>
              <option value="llm">LLM</option>
              <option value="repos">Repo</option>
            </select>
            <button
              className="small-button"
              onClick={() => setShowAddDialog(true)}
              style={{
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                padding: '4px 8px',
                fontSize: '11px',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
              }}
              title="Add New Keyword"
            >
              +
            </button>
          </div>
          <select
            multiple
            size={8}
            style={{ width: '100%' }}
            value={selectedAvailable}
            onChange={(e) => {
              const selected = Array.from(e.target.selectedOptions).map(opt => opt.value);
              setSelectedAvailable(selected);
            }}
          >
            {availableKeywords.map(kw => (
              <option key={kw} value={kw}>{kw}</option>
            ))}
          </select>
        </div>

        {/* Transfer Buttons */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <button
            className="small-button"
            onClick={handleAddToRepo}
            disabled={selectedAvailable.length === 0}
            style={{ padding: '4px 8px', fontSize: '12px' }}
          >
            &gt;&gt;
          </button>
          <button
            className="small-button"
            onClick={handleRemoveFromRepo}
            disabled={selectedRepo.length === 0}
            style={{ padding: '4px 8px', fontSize: '12px' }}
          >
            &lt;&lt;
          </button>
        </div>

        {/* Repo Keywords Panel */}
        <div>
          <div className="small" style={{ marginBottom: '6px' }}>Repo Keywords</div>
          <select
            multiple
            size={8}
            style={{ width: '100%' }}
            value={selectedRepo}
            onChange={(e) => {
              const selected = Array.from(e.target.selectedOptions).map(opt => opt.value);
              setSelectedRepo(selected);
            }}
          >
            {repoKeywords.map(kw => (
              <option key={kw} value={kw}>{kw}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Add Keyword Dialog */}
      {showAddDialog && (
        <>
          <div
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              background: 'rgba(0,0,0,0.5)',
              zIndex: 9999,
            }}
            onClick={() => setShowAddDialog(false)}
          />
          <div
            style={{
              position: 'fixed',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              background: 'var(--card-bg)',
              border: '1px solid var(--accent)',
              borderRadius: '8px',
              padding: '20px',
              zIndex: 10000,
              minWidth: '300px',
              boxShadow: '0 8px 24px rgba(0,0,0,0.8)',
            }}
          >
            <h4 style={{ color: 'var(--accent)', marginBottom: '16px' }}>Add New Keyword</h4>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ display: 'block', color: 'var(--fg-muted)', fontSize: '11px', marginBottom: '4px' }}>
                Keyword
              </label>
              <input
                type="text"
                value={newKeyword}
                onChange={(e) => setNewKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAddNewKeyword();
                  if (e.key === 'Escape') setShowAddDialog(false);
                }}
                style={{
                  width: '100%',
                  background: 'var(--bg-elev2)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px',
                  borderRadius: '4px',
                }}
                placeholder="Enter keyword..."
                autoFocus
              />
            </div>
            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', color: 'var(--fg-muted)', fontSize: '11px', marginBottom: '4px' }}>
                Category (optional)
              </label>
              <select
                value={newKeywordCategory}
                onChange={(e) => setNewKeywordCategory(e.target.value as any)}
                style={{
                  width: '100%',
                  background: 'var(--bg-elev2)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px',
                  borderRadius: '4px',
                }}
              >
                <option value="">None (appears in All only)</option>
                <option value="discriminative">Discriminative</option>
                <option value="semantic">Semantic</option>
              </select>
            </div>
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowAddDialog(false)}
                style={{
                  background: 'var(--bg-elev2)',
                  color: 'var(--fg-muted)',
                  border: '1px solid var(--line)',
                  padding: '6px 16px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleAddNewKeyword}
                style={{
                  background: 'var(--accent)',
                  color: 'var(--accent-contrast)',
                  border: 'none',
                  padding: '6px 16px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontWeight: 600,
                }}
              >
                Add
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
