import type { ChatModelInfo } from '@/types/generated';
import { chatModelDetail, chatModelName, groupChatModels } from '@/components/Chat/modelLabel';

type ModelPickerProps = {
  value: string;
  onChange: (modelOverride: string) => void;
  models: ChatModelInfo[];
  valueMode?: 'override' | 'id';
  allowEmpty?: boolean;
  disabled?: boolean;
  ariaDescribedBy?: string;
};

function toOptionValue(model: ChatModelInfo, valueMode: 'override' | 'id'): string {
  return String(valueMode === 'id' ? model.id : model.override || model.id || '');
}

export function ModelPicker({
  value,
  onChange,
  models,
  valueMode = 'override',
  allowEmpty = false,
  disabled = false,
  ariaDescribedBy,
}: ModelPickerProps) {
  const gatewayModels = models.filter((model) => model.source === 'litellm');
  const hasModels = gatewayModels.length > 0;
  const currentValueAvailable = !value
    ? allowEmpty
    : gatewayModels.some((model) => toOptionValue(model, valueMode) === value);
  const groups = groupChatModels(gatewayModels);

  return (
    <select
      data-testid="model-picker"
      value={hasModels ? value : ''}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled || !hasModels}
      aria-describedby={ariaDescribedBy}
      aria-invalid={!currentValueAvailable}
      style={{
        width: '100%',
        padding: '10px 12px',
        background: 'var(--input-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        color: 'var(--fg)',
        fontSize: '13px',
      }}
    >
      {!hasModels ? <option value="">No models available</option> : null}
      {hasModels && value && !currentValueAvailable ? (
        <option value={value} disabled>Unavailable alias: {value}</option>
      ) : null}
      {hasModels && allowEmpty ? <option value="">Use default alias</option> : null}
      {groups.map(({ group, models: groupModels }) => (
        <optgroup key={group} label={`${group} (${groupModels.length})`} data-testid={`model-picker-group-${group}`}>
          {groupModels.map((model) => {
            const optionValue = toOptionValue(model, valueMode);
            return (
              <option key={optionValue} value={optionValue} title={chatModelDetail(model)}>
                {chatModelName(model)}
              </option>
            );
          })}
        </optgroup>
      ))}
    </select>
  );
}
