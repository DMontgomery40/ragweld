/**
 * ModelPicker - Model dropdown from models.json
 *
 * Uses useModels hook to load models filtered by component type (EMB/GEN/RERANK).
 * When `provider` is given, shows models for that provider only.
 * When `provider` is omitted, shows all providers grouped via <optgroup>.
 */

import { useState, useMemo } from 'react';
import { useModels, type Model } from '@/hooks';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

interface ModelPickerProps {
  /** Component type filter */
  componentType: 'EMB' | 'GEN' | 'RERANK';
  /** Optional runtime selection role filter */
  selectionRole?: 'generation' | 'embedding_provider' | 'reranker_cloud';
  /** Provider to filter models by. When omitted, all providers shown grouped. */
  provider?: string;
  /** Current selected model name */
  value: string;
  /** Called when selection changes */
  onChange: (model: string) => void;
  /** Tooltip key from tooltips.js */
  tooltipKey?: string;
  /** Label text */
  label: string;
  /** Allow custom model input */
  allowCustom?: boolean;
  /** Disabled state */
  disabled?: boolean;
}

export function ModelPicker({
  componentType,
  selectionRole,
  provider,
  value,
  onChange,
  tooltipKey,
  label,
  allowCustom = false,
  disabled = false,
}: ModelPickerProps) {
  const { models, loading, error, providers, getModelsForProvider } = useModels(componentType, { selectionRole });
  const [customMode, setCustomMode] = useState(false);
  const [customValue, setCustomValue] = useState('');

  // When provider is given, filter to that provider; otherwise use all models
  const providerModels = useMemo(() => {
    if (provider) return getModelsForProvider(provider);
    return models;
  }, [getModelsForProvider, provider, models]);

  // Grouped models by provider (used when provider is omitted)
  const groupedModels = useMemo(() => {
    if (provider) return null;
    const groups: Array<{ provider: string; models: Model[] }> = [];
    for (const p of providers) {
      const pModels = getModelsForProvider(p);
      if (pModels.length > 0) groups.push({ provider: p, models: pModels });
    }
    return groups;
  }, [provider, providers, getModelsForProvider]);

  // Check if current value is in the list (for custom detection)
  const isValueCustom = useMemo(() => {
    if (!value || providerModels.length === 0) return false;
    return !providerModels.some(m => m.model === value);
  }, [value, providerModels]);

  // Handle select change
  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newValue = e.target.value;
    if (newValue === '__custom__' && allowCustom) {
      setCustomMode(true);
      setCustomValue(value);
    } else {
      setCustomMode(false);
      onChange(newValue);
    }
  };

  // Handle custom input
  const handleCustomChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setCustomValue(e.target.value);
  };

  const handleCustomBlur = () => {
    if (customValue.trim()) {
      onChange(customValue.trim());
    }
  };

  const handleCustomKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleCustomBlur();
    }
  };

  // Cancel custom mode
  const cancelCustom = () => {
    setCustomMode(false);
    setCustomValue('');
  };

  if (loading) {
    return (
      <div className="setting-row">
        <label>
          {label}
          {tooltipKey && <TooltipIcon name={tooltipKey} />}
        </label>
        <span style={{ color: 'var(--fg-muted)', fontSize: '13px' }}>Loading models...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="setting-row">
        <label>
          {label}
          {tooltipKey && <TooltipIcon name={tooltipKey} />}
        </label>
        <span style={{ color: 'var(--error)', fontSize: '13px' }}>{error}</span>
      </div>
    );
  }

  return (
    <div className="setting-row">
      <label>
        {label}
        {tooltipKey && <TooltipIcon name={tooltipKey} />}
      </label>

      {customMode ? (
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="text"
            value={customValue}
            onChange={handleCustomChange}
            onBlur={handleCustomBlur}
            onKeyDown={handleCustomKeyDown}
            placeholder="Enter model name"
            disabled={disabled}
            style={{ flex: 1 }}
            autoFocus
          />
          <button
            type="button"
            onClick={cancelCustom}
            style={{
              padding: '4px 8px',
              fontSize: '12px',
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
        </div>
      ) : (
        <select
          value={isValueCustom ? '__custom__' : value}
          onChange={handleSelectChange}
          disabled={disabled}
        >
          {groupedModels ? (
            // No provider given: show all grouped by provider
            groupedModels.length === 0 ? (
              <option value="">No models available</option>
            ) : (
              groupedModels.map(g => (
                <optgroup key={g.provider} label={g.provider}>
                  {g.models.map(m => (
                    <option key={`${g.provider}::${m.model}`} value={m.model}>
                      {m.model}
                      {m.dimensions && ` (${m.dimensions}d)`}
                    </option>
                  ))}
                </optgroup>
              ))
            )
          ) : providerModels.length === 0 ? (
            <option value="">No models for {provider}</option>
          ) : (
            providerModels.map(m => (
              <option key={m.model} value={m.model}>
                {m.model}
                {m.dimensions && ` (${m.dimensions}d)`}
              </option>
            ))
          )}
          {allowCustom && (
            <option value="__custom__">
              {isValueCustom ? `Custom: ${value}` : 'Enter custom...'}
            </option>
          )}
        </select>
      )}

      {/* Show model info if available */}
      {!customMode && value && (
        <ModelInfo model={providerModels.find(m => m.model === value)} />
      )}
    </div>
  );
}

/**
 * ModelInfo - Shows additional model details
 */
function ModelInfo({ model }: { model?: Model }) {
  if (!model) return null;

  return (
    <div
      style={{
        fontSize: '11px',
        color: 'var(--fg-muted)',
        marginTop: '4px',
        display: 'flex',
        gap: '12px',
      }}
    >
      {model.dimensions && <span>Dimensions: {model.dimensions}</span>}
      {model.context && <span>Context: {model.context.toLocaleString()} tokens</span>}
      {model.embed_per_1k != null && (
        <span>Cost: ${model.embed_per_1k.toFixed(5)}/1k tokens</span>
      )}
    </div>
  );
}
