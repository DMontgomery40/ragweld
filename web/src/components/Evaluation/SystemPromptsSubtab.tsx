import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useActiveRepo } from '@/stores';
import { useUIHelpers } from '@/hooks/useUIHelpers';
import { confirmDialog } from '@/components/ui/confirmDialog';
import { promptsApi } from '@/api';
import type { PromptMetadata, PromptsResponse } from '@/types/generated';

type SystemPromptsSubtabProps = {
  className?: string;
};

const CATEGORY_COLORS: Record<string, string> = {
  chat: 'var(--accent)',
  retrieval: 'var(--warn)',
  indexing: 'var(--info)',
  evaluation: 'var(--success)',
};

export const SystemPromptsSubtab: React.FC<SystemPromptsSubtabProps> = ({ className = '' }) => {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [metadata, setMetadata] = useState<Record<string, PromptMetadata>>({});
  const [editingPrompt, setEditingPrompt] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const { showToast } = useUIHelpers();
  const activeRepo = useActiveRepo();
  const navigate = useNavigate();

  const fetchPrompts = useCallback(async () => {
    setIsLoading(true);
    try {
      const data: PromptsResponse = await promptsApi.list();
      setPrompts(data.prompts || {});
      setMetadata(data.metadata || {});
    } catch (error) {
      console.error('Failed to load prompts:', error);
      showToast('Failed to load system prompts', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [showToast]);

  // Fetch prompts on mount + when active corpus changes
  useEffect(() => {
    void fetchPrompts();
  }, [activeRepo, fetchPrompts]);

  // Optional deep link support (?prompt=<prompt_key>)
  useEffect(() => {
    if (isLoading) return;
    try {
      const key = new URLSearchParams(window.location.search).get('prompt');
      if (!key) return;
      const el = document.getElementById(`prompt-card-${key}`);
      if (el) {
        // Cards are collapsed <details> now: a deep link must reveal the
        // prompt, not just scroll to a closed card.
        (el as HTMLDetailsElement).open = true;
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch {
      // ignore
    }
  }, [isLoading, metadata]);

  const isEditable = (promptKey: string) => metadata[promptKey]?.editable !== false;

  const handleEdit = (promptKey: string) => {
    if (!isEditable(promptKey)) return;
    setEditingPrompt(promptKey);
    setEditValue(prompts[promptKey] || '');
  };

  const handleCancel = () => {
    setEditingPrompt(null);
    setEditValue('');
  };

  const handleSave = async () => {
    if (!editingPrompt || !editValue.trim()) {
      showToast('Prompt cannot be empty', 'error');
      return;
    }
    if (!isEditable(editingPrompt)) {
      showToast('This prompt is edited elsewhere', 'error');
      return;
    }

    setIsSaving(true);
    try {
      await promptsApi.update(editingPrompt, editValue);

      // Update local state
      setPrompts(prev => ({ ...prev, [editingPrompt]: editValue }));
      setEditingPrompt(null);
      setEditValue('');
      showToast('Prompt saved successfully', 'success');
    } catch (error) {
      console.error('Failed to save prompt:', error);
      showToast(`Failed to save: ${error instanceof Error ? error.message : 'Unknown error'}`, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async (promptKey: string) => {
    if (!isEditable(promptKey)) {
      showToast('This prompt is edited elsewhere', 'error');
      return;
    }
    const proceed = await confirmDialog({
      title: 'Reset prompt',
      message: `Reset "${metadata[promptKey]?.label || promptKey}" to default?`,
      confirmLabel: 'Reset',
    });
    if (!proceed) {
      return;
    }

    setIsSaving(true);
    try {
      await promptsApi.reset(promptKey);

      // Refresh prompts to get the default value
      await fetchPrompts();
      showToast('Prompt reset to default', 'success');
    } catch (error) {
      console.error('Failed to reset prompt:', error);
      showToast(`Failed to reset: ${error instanceof Error ? error.message : 'Unknown error'}`, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  // Group prompts by category
  const groupedPrompts = Object.entries(metadata).reduce<Record<string, string[]>>((acc, [key, meta]) => {
    const category = meta.category;
    if (!acc[category]) acc[category] = [];
    acc[category].push(key);
    return acc;
  }, {});

  if (isLoading) {
    return (
      <div className={className} style={{ padding: '24px', textAlign: 'center' }}>
        <span style={{ color: 'var(--fg-muted)' }}>Loading system prompts...</span>
      </div>
    );
  }

  return (
    <div className={className} style={{ padding: '16px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{
          fontSize: '18px',
          fontWeight: 600,
          color: 'var(--fg)',
          marginBottom: '8px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <span style={{ fontSize: '20px' }}>&#x1F4DD;</span>
          System Prompts
        </h2>
        <p style={{
          fontSize: '13px',
          color: 'var(--fg-muted)',
          lineHeight: 1.5
        }}>
          Edit LLM system prompts that affect RAG pipeline behavior. Changes are saved to tribrid_config.json (or per-corpus config) and take effect immediately.
        </p>
      </div>

      {/* Prompts by category */}
      {Object.entries(groupedPrompts).map(([category, promptKeys]) => (
        <div key={category} style={{ marginBottom: '24px' }}>
          <h3 style={{
            fontSize: '14px',
            fontWeight: 600,
            color: CATEGORY_COLORS[category] || 'var(--fg)',
            textTransform: 'capitalize',
            marginBottom: '12px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: CATEGORY_COLORS[category] || 'var(--fg-muted)',
            }} />
            {category}
          </h3>

          {promptKeys.map(promptKey => {
            const meta = metadata[promptKey];
            const value = prompts[promptKey] || '';
            const editable = meta?.editable !== false;
            const isEditing = editable && editingPrompt === promptKey;
            const linkRoute = meta?.link_route;
            const linkLabel = meta?.link_label || 'Open';

            return (
              <details
                key={promptKey}
                id={`prompt-card-${promptKey}`}
                data-testid="system-prompt-card"
                open={isEditing || undefined}
                style={{
                  background: 'var(--card-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '8px',
                  marginBottom: '12px',
                }}
              >
                {/* Prompt header — collapsed by default; expand to read/edit */}
                <summary
                  onClick={(e) => {
                    // While a prompt is being edited, collapsing the card would
                    // hide the live editor — keep the disclosure pinned open.
                    if (isEditing) e.preventDefault();
                  }}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    gap: '12px',
                    padding: '14px 16px',
                    cursor: 'pointer',
                    listStyle: 'none',
                  }}>
                  <span style={{ minWidth: 0 }}>
                    <span style={{
                      display: 'block',
                      fontSize: '14px',
                      fontWeight: 600,
                      color: 'var(--fg)',
                      marginBottom: '4px'
                    }}>
                      {meta?.label || promptKey}
                    </span>
                    <span style={{
                      display: 'block',
                      fontSize: '12px',
                      color: 'var(--fg-muted)',
                    }}>
                      {meta?.description}
                    </span>
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--fg-muted)', whiteSpace: 'nowrap' }}>
                    {value.length} chars
                  </span>
                </summary>
                <div style={{ padding: '0 16px 16px' }}>
                <div style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  marginBottom: '12px'
                }}>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    {!isEditing && editable && (
                      <>
                        <button
                          onClick={() => handleEdit(promptKey)}
                          title="Edit prompt"
                          style={{
                            padding: '6px 12px',
                            fontSize: '12px',
                            background: 'var(--accent)',
                            color: 'white',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                          }}
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => handleReset(promptKey)}
                          title="Reset to default"
                          style={{
                            padding: '6px 12px',
                            fontSize: '12px',
                            background: 'transparent',
                            color: 'var(--fg-muted)',
                            border: '1px solid var(--line)',
                            borderRadius: '4px',
                            cursor: 'pointer',
                          }}
                        >
                          Reset
                        </button>
                      </>
                    )}
                    {!isEditing && !editable && linkRoute && (
                      <button
                        onClick={() => navigate(linkRoute)}
                        title={linkLabel}
                        style={{
                          padding: '6px 12px',
                          fontSize: '12px',
                          background: 'transparent',
                          color: 'var(--accent-text)',
                          border: '1px solid var(--accent)',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontWeight: 700,
                        }}
                      >
                        {linkLabel}
                      </button>
                    )}
                  </div>
                </div>

                {/* Prompt content */}
                {isEditing ? (
                  <div>
                    <textarea
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      style={{
                        width: '100%',
                        minHeight: '200px',
                        padding: '12px',
                        fontSize: '13px',
                        fontFamily: "'SF Mono', 'Consolas', monospace",
                        background: 'var(--code-bg)',
                        border: '1px solid var(--accent)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        resize: 'vertical',
                        lineHeight: 1.5,
                      }}
                      autoFocus
                    />
                    <div style={{
                      display: 'flex',
                      justifyContent: 'flex-end',
                      gap: '8px',
                      marginTop: '12px'
                    }}>
                      <button
                        onClick={handleCancel}
                        style={{
                          padding: '8px 16px',
                          fontSize: '13px',
                          background: 'transparent',
                          color: 'var(--fg)',
                          border: '1px solid var(--line)',
                          borderRadius: '4px',
                          cursor: 'pointer',
                        }}
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleSave}
                        disabled={isSaving}
                        style={{
                          padding: '8px 16px',
                          fontSize: '13px',
                          background: 'var(--accent)',
                          color: 'white',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: isSaving ? 'not-allowed' : 'pointer',
                          opacity: isSaving ? 0.7 : 1,
                        }}
                      >
                        {isSaving ? 'Saving...' : 'Save Changes'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{
                    background: 'var(--code-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    padding: '12px',
                    maxHeight: '400px',
                    overflow: 'auto',
                  }}>
                    <pre style={{
                      fontSize: '12px',
                      fontFamily: "'SF Mono', 'Consolas', monospace",
                      color: 'var(--fg-muted)',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      margin: 0,
                      lineHeight: 1.5,
                    }}>
                      {value || '(empty)'}
                    </pre>
                  </div>
                )}

                {/* Character count */}
                <div style={{
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginTop: '8px',
                  textAlign: 'right'
                }}>
                  {isEditing ? editValue.length : value.length} characters
                </div>
                </div>
              </details>
            );
          })}
        </div>
      ))}
    </div>
  );
};

export default SystemPromptsSubtab;
