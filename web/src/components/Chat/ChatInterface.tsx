import type React from 'react';
import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import {
  AssistantRuntimeProvider,
  AuiIf,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useExternalStoreRuntime,
} from '@assistant-ui/react';
import { ChatHistorySidebar } from '@/components/Chat/ChatHistorySidebar';
import { ModelPicker } from '@/components/Chat/ModelPicker';
import { SourceDropdown } from '@/components/Chat/SourceDropdown';
import { SourceList } from '@/components/Chat/SourceList';
import { StatusBar } from '@/components/Chat/StatusBar';
import {
  clampChatHistory,
  createAssistantThreadMessage,
  createChatSession,
  createConversationId,
  createUserThreadMessage,
  defaultChatSources,
  getMessageCustom,
  getMessageImages,
  getMessageText,
  LEGACY_CHAT_HISTORY_STORAGE_KEY,
  LEGACY_CHAT_SESSIONS_STORAGE_KEY,
  loadChatSessionsFromStorage,
  persistChatSessions as persistChatSessionsToStorage,
  setMessageCustom,
  upsertChatSession,
} from '@/components/Chat/chatSessions';
import type { RagweldMessageCustom } from '@/components/Chat/chatSessions';
import {
  ChatRequestFailedError,
  sendRagweldChat,
  toAbortReason,
} from '@/components/Chat/chatTransport';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { confirmDialog } from '@/components/ui/confirmDialog';
import { useAPI, useConfig, useConfigField, useEmbeddingStatus } from '@/hooks';
import { useUIHelpers } from '@/hooks/useUIHelpers';
import { useRepoStore } from '@/stores/useRepoStore';
import type {
  ActiveSources,
  ChatModelInfo,
  ChatModelsResponse,
  ChatMultimodalConfig,
  ChunkMatch,
  ImageAttachment,
  RecallIntensity,
  RecallPlan,
  RerankDebugInfo,
  TriBridConfig,
} from '@/types/generated';
import type {
  AppendMessage,
  MessageStatus,
  ThreadAssistantMessage,
  ThreadMessage,
  ThreadUserMessage,
} from '@assistant-ui/react';

const CHAT_REQUEST_ABORT_TIMEOUT = 'timeout';
const DEFAULT_CHAT_REQUEST_TIMEOUT_MS = 600_000;
const MAX_CHAT_SESSIONS = 50;

const WELCOME_PROMPTS = [
  'Where is auth token validation implemented?',
  'Summarize the retrieval and recall pipeline.',
  'Show me the operator-facing observability surfaces.',
];

export interface TraceStep {
  step: string;
  duration: number;
  details: unknown;
}

interface ChatInterfaceProps {
  traceOpen?: boolean;
  onTraceUpdate?: (steps: TraceStep[], open: boolean, source?: 'config' | 'response' | 'clear') => void;
}

function emitRunComplete(runId?: string, startedAtMs?: number, endedAtMs?: number): void {
  try {
    window.dispatchEvent(
      new CustomEvent('tribrid:chat:run-complete', {
        detail: {
          run_id: runId,
          started_at_ms: startedAtMs,
          ended_at_ms: endedAtMs,
        },
      }),
    );
  } catch {
    // ignore event dispatch failures
  }
}

const AssistantMarkdown = memo(function AssistantMarkdown({ content }: { content: string }) {
  return (
    <div className="chat-markdown" style={{ fontSize: '13px', lineHeight: '1.7' }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ inline, className, children, ...props }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
            const match = /language-(\w+)/.exec(className || '');
            const codeString = String(children).replace(/\n$/, '');
            return !inline && match ? (
              <div style={{ margin: '12px 0', borderRadius: '8px', overflow: 'hidden' }}>
                <div
                  style={{
                    background: '#1e1e2e',
                    padding: '6px 12px',
                    fontSize: '10px',
                    color: '#888',
                    borderBottom: '1px solid #333',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <span>{match[1]}</span>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(codeString)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#888',
                      cursor: 'pointer',
                      fontSize: '10px',
                    }}
                  >
                    Copy
                  </button>
                </div>
                <SyntaxHighlighter
                  style={oneDark as any}
                  language={match[1]}
                  PreTag="div"
                  customStyle={{
                    margin: 0,
                    padding: '12px',
                    fontSize: '12px',
                    background: '#1e1e2e',
                  }}
                  {...props}
                >
                  {codeString}
                </SyntaxHighlighter>
              </div>
            ) : (
              <code
                style={{
                  background: 'rgba(0,0,0,0.3)',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '12px',
                  fontFamily: 'monospace',
                }}
                {...props}
              >
                {children}
              </code>
            );
          },
          p({ children }) {
            return <p style={{ margin: '0 0 12px 0' }}>{children}</p>;
          },
          ul({ children }) {
            return <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>{children}</ul>;
          },
          ol({ children }) {
            return <ol style={{ margin: '8px 0', paddingLeft: '20px' }}>{children}</ol>;
          },
          li({ children }) {
            return <li style={{ marginBottom: '4px' }}>{children}</li>;
          },
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--link)', textDecoration: 'underline' }}>
                {children}
              </a>
            );
          },
          blockquote({ children }) {
            return (
              <blockquote
                style={{
                  borderLeft: '3px solid var(--accent)',
                  margin: '12px 0',
                  padding: '8px 16px',
                  background: 'rgba(0,0,0,0.2)',
                  borderRadius: '0 8px 8px 0',
                  fontStyle: 'italic',
                }}
              >
                {children}
              </blockquote>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});

type ChatComposerProps = {
  blockedReason?: string | null;
  multimodal: ChatMultimodalConfig | null;
  onCancel?: () => void;
  onSend: (text: string, images: ImageAttachment[]) => void;
  sending: boolean;
};

const ChatComposer = memo(function ChatComposer({ blockedReason, multimodal, onCancel, onSend, sending }: ChatComposerProps) {
  const { showToast } = useUIHelpers();
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ImageAttachment[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canSend = draft.trim().length > 0 && !sending && !blockedReason;
  const visionEnabled = Boolean(multimodal?.vision_enabled ?? true);
  const maxImages = Math.max(1, Math.min(10, Number(multimodal?.max_images_per_message ?? 5)));
  const maxImageSizeMb = Math.max(1, Math.min(50, Number(multimodal?.max_image_size_mb ?? 20)));
  const supportedFormats = (multimodal?.supported_formats ?? []).map((f) => String(f).trim().toLowerCase()).filter(Boolean);

  const fileToBase64NoPrefix = useCallback(async (file: File): Promise<string> => {
    const dataUrl: string = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('Failed to read image'));
      reader.readAsDataURL(file);
    });
    const comma = dataUrl.indexOf(',');
    if (comma < 0) return '';
    return dataUrl.slice(comma + 1);
  }, []);

  const addFiles = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      if (!visionEnabled) {
        showToast('Vision is disabled by config.', 'error');
        return;
      }

      const imageFiles = files.filter((file) => file && typeof file.type === 'string' && file.type.startsWith('image/'));
      if (!imageFiles.length) return;

      const room = Math.max(0, maxImages - attachments.length);
      if (room <= 0) {
        showToast(`Max ${maxImages} images per message.`, 'error');
        return;
      }

      const selected = imageFiles.slice(0, room);
      const maxBytes = maxImageSizeMb * 1024 * 1024;
      const next: ImageAttachment[] = [];
      for (const file of selected) {
        const mime = String(file.type || 'image/png');
        const ext = (mime.split('/', 2)[1] || '').toLowerCase();
        const normalizedExt = ext === 'jpg' ? 'jpeg' : ext;
        if (supportedFormats.length) {
          const allowed = new Set<string>(supportedFormats);
          if (allowed.has('jpg')) allowed.add('jpeg');
          if (allowed.has('jpeg')) allowed.add('jpg');
          if (normalizedExt && !allowed.has(normalizedExt)) {
            showToast(`Unsupported image type: ${mime}`, 'error');
            continue;
          }
        }
        if (typeof file.size === 'number' && file.size > maxBytes) {
          showToast(`Image too large (max ${maxImageSizeMb} MB).`, 'error');
          continue;
        }
        const base64 = await fileToBase64NoPrefix(file);
        if (!base64) {
          showToast('Failed to read image.', 'error');
          continue;
        }
        next.push({ base64, mime_type: mime });
      }
      if (imageFiles.length > selected.length) {
        showToast(`Only the first ${room} images were attached.`, 'info');
      }
      if (next.length) setAttachments((prev) => [...prev, ...next]);
    },
    [attachments.length, fileToBase64NoPrefix, maxImageSizeMb, maxImages, showToast, supportedFormats, visionEnabled],
  );

  const handleSend = useCallback(() => {
    const trimmed = draft.trim();
    if (!trimmed || sending || blockedReason) return;
    onSend(trimmed, attachments);
    setDraft('');
    setAttachments([]);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [attachments, blockedReason, draft, onSend, sending]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handlePaste = useCallback(
    (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const items = Array.from(event.clipboardData?.items || []);
      const imageFiles = items
        .filter((item) => item.kind === 'file' && (item.type || '').startsWith('image/'))
        .map((item) => item.getAsFile())
        .filter(Boolean) as File[];
      if (!imageFiles.length) return;
      event.preventDefault();
      void addFiles(imageFiles);
    },
    [addFiles],
  );

  return (
    <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {attachments.length > 0 && (
          <div
            data-testid="chat-attachments"
            style={{
              display: 'flex',
              gap: '8px',
              flexWrap: 'wrap',
              padding: '8px',
              border: '1px solid var(--line)',
              borderRadius: '10px',
              background: 'var(--bg-elev2)',
            }}
          >
            {attachments.map((attachment, index) => (
              <div
                key={index}
                data-testid={`chat-attachment-${index}`}
                style={{
                  position: 'relative',
                  width: '56px',
                  height: '56px',
                  borderRadius: '8px',
                  overflow: 'hidden',
                  border: '1px solid var(--line)',
                  background: 'var(--bg-elev1)',
                }}
              >
                <img
                  src={`data:${attachment.mime_type};base64,${attachment.base64}`}
                  alt={`Attachment ${index + 1}`}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
                <button
                  type="button"
                  onClick={() => setAttachments((prev) => prev.filter((_, current) => current !== index))}
                  aria-label="Remove image"
                  data-testid={`chat-attachment-remove-${index}`}
                  style={{
                    position: 'absolute',
                    top: '4px',
                    right: '4px',
                    width: '18px',
                    height: '18px',
                    borderRadius: '999px',
                    border: '1px solid var(--line)',
                    background: 'rgba(0,0,0,0.55)',
                    color: '#fff',
                    fontSize: '12px',
                    lineHeight: '16px',
                    cursor: 'pointer',
                  }}
                >
                  x
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          id="chat-input"
          ref={textareaRef}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Ask ragweld about your codebase..."
          disabled={sending || Boolean(blockedReason)}
          style={{
            flex: 1,
            background: 'var(--input-bg)',
            border: '1px solid var(--line)',
            color: 'var(--fg)',
            padding: '14px 16px',
            borderRadius: '14px',
            fontSize: '14px',
            fontFamily: 'inherit',
            resize: 'none',
            minHeight: '70px',
            maxHeight: '140px',
          }}
          rows={2}
          aria-label="Chat input"
        />
      </div>

      <input
        ref={fileInputRef}
        data-testid="chat-image-input"
        type="file"
        accept="image/*"
        multiple
        onChange={(event) => {
          const files = Array.from(event.target.files || []);
          event.target.value = '';
          void addFiles(files);
        }}
        style={{ display: 'none' }}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={sending || Boolean(blockedReason) || !visionEnabled || attachments.length >= maxImages}
          data-testid="chat-attach-button"
          style={{
            background: 'var(--bg-elev1)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '10px 12px',
            borderRadius: '12px',
            fontSize: '13px',
            fontWeight: 700,
            cursor: sending || Boolean(blockedReason) || !visionEnabled || attachments.length >= maxImages ? 'not-allowed' : 'pointer',
            opacity: sending || Boolean(blockedReason) || !visionEnabled || attachments.length >= maxImages ? 0.5 : 1,
          }}
          aria-label="Attach image"
        >
          Attach
        </button>
        <button
          id="chat-send"
          type="button"
          onClick={sending ? onCancel : handleSend}
          disabled={Boolean(blockedReason) || (!canSend && !sending)}
          style={{
            background: sending ? 'var(--warn)' : canSend ? 'var(--accent)' : 'var(--bg-elev2)',
            color: sending ? '#111' : canSend ? 'var(--accent-contrast)' : 'var(--fg-muted)',
            border: 'none',
            padding: '12px 18px',
            borderRadius: '12px',
            fontSize: '13px',
            fontWeight: 700,
            cursor: Boolean(blockedReason) || (!canSend && !sending) ? 'not-allowed' : 'pointer',
          }}
          aria-label={sending ? 'Stop generation' : 'Send message'}
        >
          {sending ? 'Stop' : 'Send'}
        </button>
      </div>
    </div>
  );
});

type AssistantThreadMessageProps = {
  messageFeedback: Record<string, { type: string; rating?: number }>;
  onCopy: (content: string) => void;
  onSendFeedback: (message: ThreadMessage, signal: string) => void;
  onViewTraceAndLogs: (message: ThreadMessage) => void;
  renderAssistantContent: (content: string) => React.ReactNode;
  showCitations: boolean;
  showConfidence: boolean;
  showDebugFooter: boolean;
  showRecallGateSignals: boolean;
};

function formatConfidence(value?: number | null): string | null {
  if (value === undefined || value === null || Number.isNaN(value)) return null;
  const percent = value <= 1 ? value * 100 : value;
  return `${percent.toFixed(1)}%`;
}

function StructuredErrorCard({ error }: { error: NonNullable<RagweldMessageCustom['structuredError']> }) {
  const action = error.required_action || error.operator_hint || '';
  const detailEntries: [string, unknown][] = [];
  if (error.operation) detailEntries.push(['operation', error.operation]);
  if (error.corpus_id) detailEntries.push(['corpus', error.corpus_id]);
  if (error.dependency) detailEntries.push(['dependency', error.dependency]);
  if (typeof error.http_status === 'number') detailEntries.push(['http status', error.http_status]);
  if (typeof error.retryable === 'boolean') detailEntries.push(['retryable', String(error.retryable)]);
  if (error.alias) detailEntries.push(['alias', error.alias]);
  if (typeof error.context_window === 'number') detailEntries.push(['context window', error.context_window]);
  if (typeof error.max_tokens === 'number') detailEntries.push(['output allowance', error.max_tokens]);
  if (typeof error.prompt_tokens === 'number') detailEntries.push(['prompt tokens', error.prompt_tokens]);
  if (error.expected_contract) detailEntries.push(['expected contract', error.expected_contract]);
  if (error.current_contract) detailEntries.push(['current contract', error.current_contract]);

  return (
    <div
      data-testid="chat-structured-error-card"
      style={{
        marginTop: '10px',
        padding: '12px 14px',
        borderRadius: '10px',
        background: 'rgba(214, 79, 79, 0.12)',
        border: '1px solid rgba(214, 79, 79, 0.4)',
        color: 'var(--fg)',
        fontSize: '12.5px',
        lineHeight: 1.55,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '6px' }}>
        <span
          style={{
            fontFamily: 'var(--font-mono, monospace)',
            fontWeight: 700,
            color: 'var(--err)',
            fontSize: '12px',
          }}
        >
          {error.code}
        </span>
        {error.leg ? (
          <span
            data-testid="chat-structured-error-leg"
            style={{
              padding: '1px 8px',
              borderRadius: '999px',
              border: '1px solid rgba(214, 79, 79, 0.5)',
              fontSize: '11px',
              fontWeight: 700,
              textTransform: 'uppercase',
            }}
          >
            {error.leg} leg
          </span>
        ) : null}
      </div>
      {error.message ? <div style={{ marginBottom: action ? '6px' : 0 }}>{error.message}</div> : null}
      {action ? (
        <div data-testid="chat-structured-error-action" style={{ marginBottom: '6px' }}>
          <span style={{ fontWeight: 700 }}>Required action: </span>
          {action}
        </div>
      ) : null}
      <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: detailEntries.length ? '6px' : 0 }}>
        Generation did not run for this request.
      </div>
      {detailEntries.length > 0 ? (
        <details>
          <summary style={{ cursor: 'pointer', fontSize: '12px', color: 'var(--fg-muted)' }}>Details</summary>
          <dl style={{ margin: '8px 0 0', display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '4px 12px' }}>
            {detailEntries.map(([key, value]) => (
              <Fragment key={key}>
                <dt style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{key}</dt>
                <dd style={{ margin: 0 }}>
                  {typeof value === 'object' ? (
                    <pre
                      style={{
                        margin: 0,
                        fontSize: '11.5px',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      }}
                    >
                      {JSON.stringify(value, null, 2)}
                    </pre>
                  ) : (
                    String(value)
                  )}
                </dd>
              </Fragment>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  );
}

function AssistantThreadMessage(props: AssistantThreadMessageProps) {
  const message = useAuiState((state) => state.message) as ThreadMessage;
  const custom = getMessageCustom(message);
  const text = getMessageText(message);
  const images = getMessageImages(message);
  const providerName = String(custom.debug?.provider?.provider_name || custom.providerMeta?.backend || '').trim();
  const messageStatus = (message as ThreadAssistantMessage).status as MessageStatus | undefined;
  const isAssistantError = message.role === 'assistant' && messageStatus?.type === 'incomplete';
  const sources = Array.isArray(custom.sources) ? custom.sources : [];
  const legacyCitations = Array.isArray(custom.legacyCitations) ? custom.legacyCitations : [];
  const webGrounding = custom.webGrounding;
  const webCitations = Array.isArray(webGrounding?.citations) ? webGrounding.citations : [];
  const recallSignals = custom.debug?.recall_plan?.signals;

  return (
    <MessagePrimitive.Root
      data-role={message.role}
      style={{
        marginBottom: '16px',
        display: 'flex',
        justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start',
      }}
    >
      <div
        style={{
          maxWidth: message.role === 'user' ? '72%' : '88%',
          background:
            message.role === 'user'
              ? 'linear-gradient(135deg, var(--accent) 0%, var(--link) 100%)'
              : 'linear-gradient(180deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0.01) 100%), var(--bg-elev1)',
          color: message.role === 'user' ? 'var(--accent-contrast)' : 'var(--fg)',
          padding: message.role === 'user' ? '12px 16px' : '16px 18px',
          borderRadius: message.role === 'user' ? '18px 18px 6px 18px' : '18px 18px 18px 6px',
          border: message.role === 'assistant' ? '1px solid var(--line)' : 'none',
          boxShadow:
            message.role === 'user'
              ? '0 8px 22px rgba(0,0,0,0.18)'
              : '0 14px 32px rgba(0,0,0,0.16)',
        }}
      >
        <div
          style={{
            fontSize: '11px',
            opacity: 0.72,
            marginBottom: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            flexWrap: 'wrap',
          }}
        >
          <span>{message.role === 'user' ? 'You' : 'Assistant'}</span>
          <span>{message.createdAt.toLocaleTimeString()}</span>
          {providerName ? <span style={{ color: 'var(--fg-muted)' }}>{providerName}</span> : null}
          {message.role === 'assistant' && messageStatus?.type === 'running' ? (
            <span style={{ color: 'var(--accent-text)', fontWeight: 700 }}>Streaming</span>
          ) : null}
          {message.role === 'assistant' && webGrounding?.web_requested ? (
            <span
              data-testid="chat-web-grounding-badge"
              style={{
                color: webGrounding.web_grounded ? 'var(--ok)' : 'var(--fg-muted)',
                fontWeight: 700,
              }}
            >
              {webGrounding.web_grounded
                ? `Web grounded · ${webCitations.length} citation${webCitations.length === 1 ? '' : 's'}`
                : 'Web requested · no validated citations'}
            </span>
          ) : null}
        </div>

        {message.role === 'assistant' && props.showConfidence && custom.confidence !== undefined && (
          <div
            style={{
              display: 'inline-block',
              background:
                custom.confidence > 0.7
                  ? 'var(--success)'
                  : custom.confidence > 0.4
                    ? 'var(--warn)'
                    : 'var(--err)',
              color: '#111',
              padding: '3px 8px',
              borderRadius: '999px',
              fontSize: '10px',
              fontWeight: 700,
              marginBottom: '10px',
            }}
          >
            Confidence {formatConfidence(custom.confidence)}
          </div>
        )}

        {message.role === 'assistant' ? (
          <>
            {props.renderAssistantContent(text)}
            {custom.structuredError ? (
              <StructuredErrorCard error={custom.structuredError} />
            ) : isAssistantError ? (
              <div
                style={{
                  marginTop: '10px',
                  padding: '10px 12px',
                  borderRadius: '10px',
                  background: 'rgba(214, 79, 79, 0.12)',
                  border: '1px solid rgba(214, 79, 79, 0.35)',
                  color: 'var(--fg)',
                  fontSize: '12px',
                }}
              >
                Generation ended with an error.
              </div>
            ) : null}
          </>
        ) : (
          <div>
            {text ? (
              <div
                style={{
                  fontSize: '13px',
                  lineHeight: '1.6',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {text}
              </div>
            ) : null}
            {images.length > 0 && (
              <div
                data-testid="chat-message-images"
                style={{
                  marginTop: text ? '10px' : '0',
                  display: 'flex',
                  gap: '8px',
                  flexWrap: 'wrap',
                }}
              >
                {images.map((image, index) => (
                  <img
                    key={index}
                    src={image}
                    alt={`Sent image ${index + 1}`}
                    style={{
                      width: '88px',
                      height: '88px',
                      objectFit: 'cover',
                      borderRadius: '10px',
                      border: '1px solid rgba(255,255,255,0.25)',
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {props.showCitations && (sources.length > 0 || legacyCitations.length > 0 || webCitations.length > 0) && (
          <SourceList sources={sources} legacyCitations={legacyCitations} webCitations={webCitations} />
        )}

        <div
          style={{
            marginTop: '10px',
            fontSize: '10px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '10px',
            opacity: 0.78,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <button
              type="button"
              onClick={() => props.onCopy(text)}
              style={{
                background: 'none',
                border: 'none',
                color: 'inherit',
                cursor: 'pointer',
                padding: '0',
                fontSize: '10px',
              }}
            >
              Copy
            </button>
            {message.role === 'assistant' && (custom.runId || custom.eventId) ? (
              <button
                type="button"
                onClick={() => props.onViewTraceAndLogs(message)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'inherit',
                  cursor: 'pointer',
                  padding: '0',
                  fontSize: '10px',
                }}
              >
                Trace
              </button>
            ) : null}
          </div>

          {message.role === 'assistant' ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: 'auto' }}>
              {props.messageFeedback[message.id] ? (
                <span style={{ color: 'var(--success)' }}>Feedback saved</span>
              ) : (
                <>
                  <button
                    type="button"
                    data-testid="chat-feedback-thumbsup"
                    onClick={() => props.onSendFeedback(message, 'thumbsup')}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px', padding: 0 }}
                  >
                    Helpful
                  </button>
                  <button
                    type="button"
                    data-testid="chat-feedback-thumbsdown"
                    onClick={() => props.onSendFeedback(message, 'thumbsdown')}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px', padding: 0 }}
                  >
                    Not helpful
                  </button>
                </>
              )}
            </div>
          ) : null}
        </div>

        {message.role === 'assistant' && props.showDebugFooter && custom.debug && (
          <div
            style={{
              marginTop: '12px',
              paddingTop: '12px',
              borderTop: '1px dashed var(--line)',
              fontSize: '11px',
              color: 'var(--fg-muted)',
              display: 'grid',
              gap: '4px',
            }}
          >
            <div>run_id: {custom.runId || 'n/a'}</div>
            <div>provider_response_id: {custom.providerResponseId || 'n/a'}</div>
            <div>trace_id: {custom.traceId || 'n/a'}</div>
            <div>correlation_id: {custom.correlationId || 'n/a'}</div>
            <div>llm_used: {String(custom.debug.llm_used)}</div>
            {custom.debug.llm_error ? <div>llm_error: {custom.debug.llm_error}</div> : null}
            {props.showRecallGateSignals && recallSignals ? (
              <div>
                recall_signals:
                {' '}
                {JSON.stringify(recallSignals)}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </MessagePrimitive.Root>
  );
}

const ThreadWelcome = memo(function ThreadWelcome({ onPromptSelect }: { onPromptSelect: (prompt: string) => void }) {
  return (
    <div
      style={{
        display: 'grid',
        gap: '18px',
        padding: '28px 12px 18px 12px',
        marginBottom: '10px',
      }}
    >
      <div style={{ maxWidth: '620px' }}>
        <div style={{ fontSize: '11px', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent-text)' }}>
          assistant-ui rebuild
        </div>
        <h2 style={{ margin: '8px 0 10px 0', fontSize: '26px', lineHeight: 1.1 }}>
          Chat stays grounded in recall, sources, and session continuity.
        </h2>
        <p style={{ margin: 0, fontSize: '14px', color: 'var(--fg-muted)', lineHeight: 1.6 }}>
          This surface now runs on assistant-ui while keeping ragweld&apos;s corpus controls, recall gate,
          citations, and trace-linked metadata.
        </p>
      </div>

      <div style={{ display: 'grid', gap: '10px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        {WELCOME_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => onPromptSelect(prompt)}
            style={{
              textAlign: 'left',
              padding: '14px 16px',
              borderRadius: '16px',
              border: '1px solid var(--line)',
              background: 'linear-gradient(180deg, var(--bg-elev1) 0%, var(--bg-elev2) 100%)',
              color: 'var(--fg)',
              cursor: 'pointer',
            }}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
});

export function ChatInterface({ onTraceUpdate }: ChatInterfaceProps) {
  const { api } = useAPI();
  const { config } = useConfig();
  const { showToast } = useUIHelpers();
  const { status: embeddingStatus, loading: embeddingStatusLoading, error: embeddingStatusError } = useEmbeddingStatus();
  const { repos, loadRepos, initialized, activeRepo, deleteUnindexedCorpora } = useRepoStore();

  const [chatSessions, setChatSessions] = useState<ReturnType<typeof createChatSession>[]>([]);
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [conversationId, setConversationId] = useState<string>(() => createConversationId());
  const [modelOverride, setModelOverride] = useState('');
  const [activeSources, setActiveSources] = useState<ActiveSources>(defaultChatSources());
  const [includeVector, setIncludeVector] = useState(true);
  const [includeSparse, setIncludeSparse] = useState(true);
  const [includeGraph, setIncludeGraph] = useState(false);
  const [webEnabled, setWebEnabled] = useState(false);
  const [recallIntensity, setRecallIntensity] = useState<RecallIntensity | null>(null);
  const [chatModels, setChatModels] = useState<ChatModelInfo[]>([]);
  const [sending, setSending] = useState(false);
  const [lastMatches, setLastMatches] = useState<ChunkMatch[]>([]);
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);
  const [lastRecallPlan, setLastRecallPlan] = useState<RecallPlan | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [messageFeedback, setMessageFeedback] = useState<Record<string, { type: string; rating?: number }>>({});

  const [temperature, setTemperature] = useConfigField<number>('chat.temperature', 0.3);
  const [maxTokens, setMaxTokens] = useConfigField<number>('chat.max_tokens', 512);
  // Top-K is a per-conversation retrieval override (ChatRequest.top_k), NOT a config write.
  // As a config field it wrote `retrieval.final_k` into whatever corpus the URL named, so
  // tuning a chat over corpus A silently mutated corpus B (M-02). null = use the
  // conversation corpus's configured final_k, which is what `topKBaseline` reads.
  const [topKOverride, setTopKOverride] = useState<number | null>(null);
  const [topKBaseline, setTopKBaseline] = useState<number | null>(null);

  // Recall is a source, not a corpus you tune. A chat-initiated corpus-scoped operation
  // belongs to the conversation's first RAG corpus - the same one retrieval fusion picks for
  // its reranker config on a mixed-corpus query (`rerank_config_corpus_id`), so the feedback
  // this records and the config that ranked the answer name the same corpus.
  const recallCorpusId = String(config?.chat?.recall?.default_corpus_id || 'recall_default');
  const conversationCorpusId = useMemo(
    () =>
      (activeSources?.corpus_ids ?? [])
        .map(String)
        .find((id) => id && id !== recallCorpusId) ?? '',
    [activeSources, recallCorpusId],
  );

  const chatShowConfidence = config?.ui?.chat_show_confidence ?? false;
  const chatShowCitations = config?.ui?.chat_show_citations ?? true;
  const chatShowTrace = config?.ui?.chat_show_trace ?? true;
  const chatShowDebugFooter = config?.ui?.chat_show_debug_footer ?? true;
  const recallGateShowDecision = Boolean(config?.chat?.recall_gate?.show_gate_decision ?? true);
  const recallGateShowSignals = Boolean(config?.chat?.recall_gate?.show_signals ?? false);
  const chatHistoryMax = Math.max(10, Math.min(500, Number(config?.ui?.chat_history_max ?? 50)));
  const multimodalCfg = (config?.chat?.multimodal ?? null) as ChatMultimodalConfig | null;
  const configuredChatTimeoutSeconds = Number(config?.ui?.chat_stream_timeout ?? 600);
  const chatRequestTimeoutMs = Number.isFinite(configuredChatTimeoutSeconds)
    ? Math.max(5, Math.min(600, configuredChatTimeoutSeconds)) * 1000
    : DEFAULT_CHAT_REQUEST_TIMEOUT_MS;

  const messagesRef = useRef(messages);
  const conversationIdRef = useRef(conversationId);
  const modelOverrideRef = useRef(modelOverride);
  const activeSourcesRef = useRef(activeSources);
  const topKOverrideRef = useRef(topKOverride);
  const requestAbortControllerRef = useRef<AbortController | null>(null);
  const activeRequestTokenRef = useRef(0);
  const sessionsLoadedRef = useRef(false);
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { messagesRef.current = messages; }, [messages]);
  useEffect(() => { conversationIdRef.current = conversationId; }, [conversationId]);
  useEffect(() => { modelOverrideRef.current = modelOverride; }, [modelOverride]);
  useEffect(() => { activeSourcesRef.current = activeSources; }, [activeSources]);
  useEffect(() => { topKOverrideRef.current = topKOverride; }, [topKOverride]);

  const notifyTrace = useCallback(
    (steps: TraceStep[], open: boolean, source: 'config' | 'response' | 'clear' = 'response') => {
      const effectiveOpen = source === 'response' ? open && chatShowTrace : open;
      onTraceUpdate?.(steps, effectiveOpen, source);
    },
    [chatShowTrace, onTraceUpdate],
  );

  const isRequestTokenActive = useCallback((token: number) => activeRequestTokenRef.current === token, []);

  const resetTransientChatState = useCallback((reason: string = 'aborted') => {
    const controller = requestAbortControllerRef.current;
    if (controller) {
      try {
        controller.abort(reason);
      } catch {
        // ignore abort races
      }
    }
    requestAbortControllerRef.current = null;
    activeRequestTokenRef.current += 1;
    setSending(false);
  }, []);

  const persistSessions = useCallback((sessions: ReturnType<typeof createChatSession>[], activeId: string) => {
    try {
      persistChatSessionsToStorage(localStorage, sessions, activeId);
    } catch (error) {
      console.error('[ChatInterface] Failed to persist chat sessions:', error);
    }
  }, []);

  const saveChatHistory = useCallback(
    (nextMessages: ThreadMessage[], overrides?: { conversationId?: string; modelOverride?: string; sources?: ActiveSources }) => {
      const nextConversationId = String(overrides?.conversationId || conversationIdRef.current || createConversationId()).trim();
      const nextModelOverride = String(overrides?.modelOverride ?? modelOverrideRef.current ?? '').trim();
      const nextSources = overrides?.sources || activeSourcesRef.current || defaultChatSources();
      const now = Date.now();
      setMessages(nextMessages);
      setChatSessions((prev) => {
        const next = upsertChatSession({
          sessions: prev,
          activeId: nextConversationId,
          messages: nextMessages,
          modelOverride: nextModelOverride,
          sources: nextSources,
          now,
          chatHistoryMax,
          maxSessions: MAX_CHAT_SESSIONS,
        });
        persistSessions(next, nextConversationId);
        sessionsLoadedRef.current = true;
        return next;
      });
      if (nextConversationId !== conversationIdRef.current) {
        conversationIdRef.current = nextConversationId;
        setConversationId(nextConversationId);
      }
    },
    [chatHistoryMax, persistSessions],
  );

  const renameConversation = useCallback(
    (nextConversationId: string, nextMessages: ThreadMessage[]) => {
      const currentId = conversationIdRef.current;
      if (!nextConversationId || nextConversationId === currentId) {
        saveChatHistory(nextMessages);
        return;
      }

      setChatSessions((prev) => {
        const renamed = prev.map((session) => {
          if (String(session.conversation_id || '').trim() !== currentId) return session;
          return {
            ...session,
            conversation_id: nextConversationId,
            updated_at: Date.now(),
            messages: nextMessages,
          };
        });
        persistSessions(renamed, nextConversationId);
        return renamed;
      });
      conversationIdRef.current = nextConversationId;
      setConversationId(nextConversationId);
      setMessages(nextMessages);
    },
    [persistSessions, saveChatHistory],
  );

  const activateSession = useCallback(
    (session: ReturnType<typeof createChatSession>) => {
      resetTransientChatState('session_change');
      const nextConversationId = String(session.conversation_id || '').trim() || createConversationId();
      conversationIdRef.current = nextConversationId;
      setConversationId(nextConversationId);
      const restoredMessages = clampChatHistory(
        Array.isArray(session.messages) ? session.messages : [],
        chatHistoryMax,
      );
      // Synchronously, not only through setMessages: the "an unused thread follows the active
      // corpus" effect below runs in the SAME commit as this call, so it would otherwise read
      // the previous thread's (empty) message list and overwrite the sources this conversation
      // was actually answered with (M-03).
      messagesRef.current = restoredMessages;
      setMessages(restoredMessages);
      modelOverrideRef.current = String(session.model_override || '').trim();
      setModelOverride(modelOverrideRef.current);
      topKOverrideRef.current = null;
      setTopKOverride(null);
      const sessionSources = (session.sources || defaultChatSources()) as ActiveSources;
      activeSourcesRef.current = sessionSources;
      setActiveSources(sessionSources);
      setLastMatches([]);
      setLastLatencyMs(null);
      setLastRecallPlan(null);
      notifyTrace([], false, 'clear');
    },
    [chatHistoryMax, notifyTrace, resetTransientChatState],
  );

  const loadChatHistory = useCallback(() => {
    try {
      const { sessions, activeSession, removeLegacyHistory } = loadChatSessionsFromStorage(localStorage, chatHistoryMax);
      setChatSessions(sessions);
      sessionsLoadedRef.current = true;
      persistSessions(sessions, String(activeSession.conversation_id || '').trim());
      activateSession(activeSession);
      if (removeLegacyHistory) {
        try {
          localStorage.removeItem(LEGACY_CHAT_HISTORY_STORAGE_KEY);
          localStorage.removeItem(LEGACY_CHAT_SESSIONS_STORAGE_KEY);
        } catch {
          // ignore localStorage cleanup failure
        }
      }
    } catch (error) {
      console.error('[ChatInterface] Failed to load chat history:', error);
    }
  }, [activateSession, chatHistoryMax, persistSessions]);

  useEffect(() => {
    if (!initialized) loadRepos();
  }, [initialized, loadRepos]);

  useEffect(() => {
    loadChatHistory();
    return () => {
      const controller = requestAbortControllerRef.current;
      if (controller) {
        try {
          controller.abort('unmount');
        } catch {
          // ignore
        }
      }
      requestAbortControllerRef.current = null;
    };
  }, [loadChatHistory]);

  // Default sources for a new thread: the configured defaults (recall memory)
  // plus the app's active corpus, so a first question goes to the corpus the
  // operator is looking at (2026-08-25 drive finding M6: Chat opened scoped to a
  // stale thread's corpus while a different corpus was active).
  const defaultSourcesForActiveCorpus = useCallback((): ActiveSources => {
    const configured = (config?.chat?.default_corpus_ids ?? [recallCorpusId]).map(String);
    const recallEnabled = config?.chat?.recall?.enabled ?? true;
    const ids = configured.filter((id) => id !== recallCorpusId || recallEnabled);
    const corpus = String(activeRepo || '').trim();
    if (corpus && !ids.includes(corpus)) ids.push(corpus);
    return { corpus_ids: ids };
  }, [activeRepo, config, recallCorpusId]);
  const defaultSourcesRef = useRef(defaultSourcesForActiveCorpus);
  useEffect(() => {
    defaultSourcesRef.current = defaultSourcesForActiveCorpus;
  }, [defaultSourcesForActiveCorpus]);

  useEffect(() => {
    if (!config) return;
    if (!sessionsLoadedRef.current) return;
    setActiveSources((current) => {
      if (Array.isArray(current?.corpus_ids) && current.corpus_ids.length > 0) return current;
      const next = defaultSourcesForActiveCorpus();
      activeSourcesRef.current = next;
      return next;
    });
  }, [config, defaultSourcesForActiveCorpus]);

  // A thread that has not been used yet follows the active corpus when it changes. "Unused"
  // is read from the ref as well as the state, because on the mount that restores a session
  // this effect runs before React has flushed activateSession's setMessages.
  useEffect(() => {
    if (!config || !sessionsLoadedRef.current) return;
    if (messages.length > 0 || messagesRef.current.length > 0) return;
    const corpus = String(activeRepo || '').trim();
    if (!corpus) return;
    setActiveSources((current) => {
      const ids = (current?.corpus_ids ?? []).map(String);
      if (ids.includes(corpus)) return current;
      const next = defaultSourcesForActiveCorpus();
      activeSourcesRef.current = next;
      return next;
    });
  }, [activeRepo, config, defaultSourcesForActiveCorpus, messages.length]);

  // The Top-K baseline is the CONVERSATION corpus's own retrieval.final_k. Reading the
  // globally scoped config would show one corpus's number while the conversation queries
  // another - the display half of M-02. No corpus selected means no baseline to show.
  useEffect(() => {
    let cancelled = false;
    const corpusId = conversationCorpusId;
    if (!corpusId) {
      setTopKBaseline(null);
      return;
    }
    (async () => {
      try {
        const response = await fetch(api(`config?corpus_id=${encodeURIComponent(corpusId)}`));
        if (!response.ok) {
          if (!cancelled) setTopKBaseline(null);
          return;
        }
        const data = (await response.json()) as TriBridConfig;
        const finalK = Number(data?.retrieval?.final_k);
        if (!cancelled) setTopKBaseline(Number.isFinite(finalK) ? finalK : null);
      } catch {
        if (!cancelled) setTopKBaseline(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api, conversationCorpusId]);

  useEffect(() => {
    if (!config) return;
    if (!chatModels.length) return;

    const optionValues = chatModels.map((model) => String(model.override || model.id || '').trim());
    if (modelOverride && optionValues.includes(modelOverride)) return;

    const litellmEnabled = Boolean(config.chat?.litellm?.enabled);
    const litellmDefault = String(config.chat?.litellm?.default_model || '').trim();

    const selectOverride = (model: ChatModelInfo): string => String(model.override || model.id || '').trim();
    const litellmModels = chatModels.filter((model) => model.source === 'litellm');

    const nextModel =
      (litellmEnabled && litellmDefault
        ? litellmModels.find((model) => String(model.id || '').trim() === litellmDefault || String(model.catalog_model || '').trim() === litellmDefault)
        : undefined) ||
      (litellmEnabled ? litellmModels[0] : undefined) ||
      chatModels[0];

    if (nextModel) setModelOverride(selectOverride(nextModel));
  }, [chatModels, config, modelOverride]);

  useEffect(() => {
    (async () => {
      try {
        const qs = activeRepo ? `?corpus_id=${encodeURIComponent(activeRepo)}` : '';
        const response = await fetch(api(`chat/models${qs}`));
        if (!response.ok) {
          setChatModels([]);
          return;
        }
        const data = (await response.json()) as ChatModelsResponse;
        setChatModels(Array.isArray(data?.models) ? (data.models as ChatModelInfo[]) : []);
      } catch {
        setChatModels([]);
      }
    })();
  }, [
    activeRepo,
    api,
    Boolean(config?.chat?.litellm?.enabled),
    String(config?.chat?.litellm?.base_url || '').trim(),
    String(config?.chat?.litellm?.default_model || '').trim(),
  ]);

  useEffect(() => {
    if (!sessionsLoadedRef.current) return;
    const activeId = String(conversationId || '').trim();
    if (!activeId) return;
    const nextModel = String(modelOverride || '').trim();
    setChatSessions((prev) => {
      const next = prev.slice();
      const index = next.findIndex((session) => String(session.conversation_id || '').trim() === activeId);
      if (index === -1) return prev;
      if (String(next[index].model_override || '').trim() === nextModel) return prev;
      next[index] = { ...next[index], model_override: nextModel, updated_at: Date.now() };
      persistSessions(next, activeId);
      return next;
    });
  }, [conversationId, modelOverride, persistSessions]);

  useEffect(() => {
    if (!sessionsLoadedRef.current) return;
    const activeId = String(conversationId || '').trim();
    if (!activeId) return;
    setChatSessions((prev) => {
      const next = prev.slice();
      const index = next.findIndex((session) => String(session.conversation_id || '').trim() === activeId);
      if (index === -1) return prev;
      const currentSignature = JSON.stringify(next[index].sources || defaultChatSources());
      const nextSignature = JSON.stringify(activeSources || defaultChatSources());
      if (currentSignature === nextSignature) return prev;
      next[index] = { ...next[index], sources: activeSources, updated_at: Date.now() };
      persistSessions(next, activeId);
      return next;
    });
  }, [activeSources, conversationId, persistSessions]);

  // Drop corpus ids that no longer exist - but only against a registry that actually loaded.
  // Unguarded, this ran on the first commit with `repos` still empty, pruned every real
  // corpus out of the just-restored conversation and persisted the result (M-03). An empty
  // or failed registry proves nothing about which corpora exist.
  useEffect(() => {
    if (!initialized || repos.length === 0) return;
    const allowed = new Set<string>(repos.map((repo) => String(repo.corpus_id)));
    allowed.add(recallCorpusId);
    const current = (activeSources?.corpus_ids ?? []).map(String);
    const next = current.filter((id) => allowed.has(id));
    if (next.length === current.length) return;
    const updated = { ...activeSources, corpus_ids: next };
    activeSourcesRef.current = updated;
    setActiveSources(updated);
  }, [activeSources, initialized, recallCorpusId, repos]);

  // What the operator sees: their override if they set one, otherwise the conversation
  // corpus's own configured breadth. Never a number belonging to a different corpus.
  const topKDisplay = topKOverride ?? topKBaseline;

  const retrievalSelected = (activeSources?.corpus_ids ?? []).length > 0;
  const chatBlockedReason =
    embeddingStatusError
      ? `Retrieval compatibility check failed: ${embeddingStatusError}`
      : !embeddingStatusLoading &&
        retrievalSelected &&
        Boolean(embeddingStatus?.hasIndex) &&
        Boolean(embeddingStatus?.isMismatched) &&
        (includeVector || includeSparse)
        ? 'Retrieval/index contract mismatch detected. Re-index or restore indexing config before sending.'
        : null;

  const maybeToastRerankOutcome = useCallback(
    (rerank: RerankDebugInfo | null | undefined) => {
      if (!rerank || !rerank.enabled) return;
      const mode = String(rerank.mode || 'rerank').trim() || 'rerank';
      const skipped = String(rerank.skipped_reason || '').trim();
      const errMsg = String(rerank.error_message || '').trim();
      const errRaw = String(rerank.error || '').trim();
      const traceId = String(rerank.debug_trace_id || '').trim();

      if (rerank.ok === false) {
        const message = errMsg || errRaw || 'Unknown error';
        showToast(`Rerank failed (${mode}): ${message}${traceId ? ` (trace ${traceId})` : ''}`, 'error');
        return;
      }

      if (!rerank.applied && skipped) {
        if (skipped.toLowerCase() === 'no_candidates' || skipped.toLowerCase() === 'empty_query') return;
        showToast(`Rerank skipped (${mode}): ${skipped}`, 'info');
      }
    },
    [showToast],
  );

  const sendFeedback = useCallback(
    async (eventId: string | undefined, messageId: string, signal: string) => {
      const normalizedSignal = String(signal || '').trim();
      try {
        const body: Record<string, unknown> = {
          context: 'chat',
          timestamp: new Date().toISOString(),
        };
        if (eventId) {
          body.event_id = eventId;
          body.signal = normalizedSignal;
        } else {
          showToast('Feedback not available yet (missing run_id).', 'error');
          return;
        }

        // Explicit scoping, not withCorpusScope: its fallback to the URL / localStorage
        // corpus is exactly the defect (M-02). A conversation with no RAG corpus (recall
        // only) is genuinely unscoped, and the endpoint's global feedback log is correct.
        const scopedFeedbackPath = conversationCorpusId
          ? `feedback?corpus_id=${encodeURIComponent(conversationCorpusId)}`
          : 'feedback';
        const response = await fetch(api(scopedFeedbackPath), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!response.ok) {
          const detail = await response.text();
          showToast(detail ? `Feedback failed: ${detail}` : 'Feedback failed.', 'error');
          return;
        }

        setMessageFeedback((prev) => ({
          ...prev,
          [messageId]: { type: normalizedSignal },
        }));
        showToast('Feedback recorded.', 'success');
      } catch (error) {
        console.error('[ChatInterface] Feedback error:', error);
        showToast('Feedback failed (network error).', 'error');
      }
    },
    [api, conversationCorpusId, showToast],
  );

  const updateAssistantMessage = useCallback(
    (
      assistantId: string,
      updater: (message: ThreadAssistantMessage) => ThreadAssistantMessage,
    ): ThreadMessage[] => {
      const nextMessages = clampChatHistory(
        messagesRef.current.map((message) => {
          if (message.id !== assistantId || message.role !== 'assistant') return message;
          return updater(message as ThreadAssistantMessage);
        }),
        chatHistoryMax,
      );
      setMessages(nextMessages);
      messagesRef.current = nextMessages;
      return nextMessages;
    },
    [chatHistoryMax],
  );

  const buildAssistantStatus = useCallback((type: 'complete' | 'error' | 'running', errorText?: string): MessageStatus => {
    if (type === 'running') return { type: 'running' };
    if (type === 'error') {
      return { type: 'incomplete', reason: 'error', error: errorText || 'Chat failed' };
    }
    return { type: 'complete', reason: 'stop' };
  }, []);

  const runUserTurn = useCallback(
    async (userMessage: ThreadUserMessage) => {
      if (chatBlockedReason) {
        showToast(chatBlockedReason, 'error');
        return;
      }

      const recallIntensityOverride = recallIntensity;
      if (recallIntensityOverride !== null) setRecallIntensity(null);

      resetTransientChatState('superseded');
      const requestToken = activeRequestTokenRef.current + 1;
      activeRequestTokenRef.current = requestToken;

      const requestSources = (activeSourcesRef.current || activeSources || defaultChatSources()) as ActiveSources;
      const assistantId = `assistant-${Date.now()}`;
      const assistantMessage = createAssistantThreadMessage({
        id: assistantId,
        createdAt: new Date(),
        status: buildAssistantStatus('running'),
      });
      const nextMessages = clampChatHistory([...messagesRef.current, userMessage, assistantMessage], chatHistoryMax);
      messagesRef.current = nextMessages;
      saveChatHistory(nextMessages);
      setSending(true);
      notifyTrace([], false, 'clear');

      const abortController = new AbortController();
      requestAbortControllerRef.current = abortController;
      const timeoutId = window.setTimeout(() => {
        try {
          abortController.abort(CHAT_REQUEST_ABORT_TIMEOUT);
        } catch {
          // ignore abort races
        }
      }, chatRequestTimeoutMs);

      let accumulated = '';
      try {
        const result = await sendRagweldChat({
          api,
          conversationId: conversationIdRef.current,
          includeGraph,
          includeSparse,
          includeVector,
          message: userMessage,
          modelOverride: modelOverrideRef.current,
          onTextDelta: (delta) => {
            if (!isRequestTokenActive(requestToken)) return;
            accumulated += delta;
            updateAssistantMessage(assistantId, (message) =>
              setMessageCustom(
                {
                  ...message,
                  content: accumulated ? [{ type: 'text', text: accumulated }] : [],
                  status: buildAssistantStatus('running'),
                },
                getMessageCustom(message),
              ),
            );
          },
          recallIntensityOverride,
          requestSources,
          signal: abortController.signal,
          streamPreferred: true,
          topK: topKOverrideRef.current,
          webEnabled,
        });

        if (!isRequestTokenActive(requestToken)) return;

        const custom = {
          confidence: typeof result.debug?.confidence === 'number' ? result.debug.confidence : undefined,
          correlationId: result.headers.correlationId,
          debug: result.debug,
          endedAtMs: result.endedAtMs,
          eventId: result.runId,
          providerResponseId: result.providerResponseId ?? null,
          rootSpanId: result.headers.rootSpanId,
          runId: result.runId,
          sources: result.sources,
          startedAtMs: result.startedAtMs,
          traceId: result.headers.traceId,
          webGrounding: result.webGrounding,
        };

        const finalMessages = updateAssistantMessage(assistantId, (message) =>
          setMessageCustom(
            {
              ...message,
              content: result.text ? [{ type: 'text', text: result.text }] : [],
              status: buildAssistantStatus('complete'),
            },
            custom,
          ),
        );

        renameConversation(result.conversationId, finalMessages);
        saveChatHistory(finalMessages, { conversationId: result.conversationId });
        setLastMatches(result.sources);
        if (typeof result.startedAtMs === 'number' && typeof result.endedAtMs === 'number') {
          setLastLatencyMs(Math.max(0, result.endedAtMs - result.startedAtMs));
        }
        setLastRecallPlan(result.debug?.recall_plan ?? null);
        maybeToastRerankOutcome(result.debug?.rerank);
        emitRunComplete(result.runId, result.startedAtMs, result.endedAtMs);
      } catch (error) {
        const abortReason = toAbortReason(error, abortController.signal);
        if (!isRequestTokenActive(requestToken)) return;

        if (abortReason) {
          const message = abortReason === CHAT_REQUEST_ABORT_TIMEOUT
            ? 'Error: Chat timed out before completion.'
            : 'Error: Chat request was cancelled.';
          const abortedMessages = updateAssistantMessage(assistantId, (assistant) =>
            setMessageCustom(
              {
                ...assistant,
                content: [{ type: 'text', text: message }],
                status: buildAssistantStatus('error', message),
              },
              getMessageCustom(assistant),
            ),
          );
          saveChatHistory(abortedMessages);
          if (abortReason === CHAT_REQUEST_ABORT_TIMEOUT) showToast('Chat timed out before completion.', 'error');
          return;
        }

        console.error('[ChatInterface] Failed to send message:', error);
        if (error instanceof ChatRequestFailedError && error.detail) {
          // Typed pre-generation failure: render a structured error card, not prose.
          const structured = { ...error.detail, http_status: error.status };
          const summary = error.detail.message || error.detail.code;
          const failedMessages = updateAssistantMessage(assistantId, (assistant) =>
            setMessageCustom(
              {
                ...assistant,
                content: [],
                status: buildAssistantStatus('error', summary),
              },
              { ...getMessageCustom(assistant), structuredError: structured },
            ),
          );
          saveChatHistory(failedMessages);
          showToast(summary, 'error');
          return;
        }
        const errorMessage = `Error: ${error instanceof Error ? error.message : 'Failed to get response'}`;
        const failedMessages = updateAssistantMessage(assistantId, (assistant) =>
          setMessageCustom(
            {
              ...assistant,
              content: [{ type: 'text', text: errorMessage }],
              status: buildAssistantStatus('error', errorMessage),
            },
            getMessageCustom(assistant),
          ),
        );
        saveChatHistory(failedMessages);
        showToast(error instanceof Error ? error.message : 'Failed to get response', 'error');
      } finally {
        window.clearTimeout(timeoutId);
        if (requestAbortControllerRef.current === abortController) {
          requestAbortControllerRef.current = null;
        }
        if (!isRequestTokenActive(requestToken)) return;
        setSending(false);
      }
    },
    [
      activeSources,
      api,
      buildAssistantStatus,
      chatBlockedReason,
      chatHistoryMax,
      chatRequestTimeoutMs,
      includeGraph,
      includeSparse,
      includeVector,
      isRequestTokenActive,
      maybeToastRerankOutcome,
      notifyTrace,
      recallIntensity,
      renameConversation,
      resetTransientChatState,
      saveChatHistory,
      showToast,
      updateAssistantMessage,
      webEnabled,
    ],
  );

  const handleAssistantUiAppend = useCallback(
    async (message: AppendMessage) => {
      if (message.role && message.role !== 'user') return;
      const createdAt = message.createdAt instanceof Date ? message.createdAt : new Date();
      const normalized: ThreadUserMessage = {
        id: `user-${createdAt.getTime()}-${Math.random().toString(16).slice(2)}`,
        role: 'user',
        createdAt,
        content: (message.content || []).filter((part) =>
          part.type === 'text' || part.type === 'image' || part.type === 'file' || part.type === 'data' || part.type === 'audio',
        ) as ThreadUserMessage['content'],
        attachments: [],
        metadata: { custom: message.metadata?.custom ?? {} },
      };
      await runUserTurn(normalized);
    },
    [runUserTurn],
  );

  const runtimeStore = useMemo(() => ({
    isDisabled: false,
    isLoading: false,
    isRunning: sending,
    messages,
    onCancel: async () => {
      resetTransientChatState('user_cancel');
    },
    onNew: handleAssistantUiAppend,
    suggestions: WELCOME_PROMPTS.map((prompt) => ({ prompt })),
    unstable_capabilities: { copy: true },
    adapters: {
      threadList: {
        threadId: conversationId,
        threads: chatSessions.map((session) => ({
          status: 'regular' as const,
          id: session.conversation_id,
          title: session.title,
        })),
      },
    },
  }), [chatSessions, conversationId, handleAssistantUiAppend, messages, resetTransientChatState, sending]);
  const runtime = useExternalStoreRuntime(runtimeStore);

  const handleSend = useCallback(
    (text: string, images: ImageAttachment[]) => {
      const userMessage = createUserThreadMessage({
        text,
        images,
      });
      void runUserTurn(userMessage);
    },
    [runUserTurn],
  );

  const handleCleanupUnindexed = useCallback(async () => {
    try {
      const deleted = await deleteUnindexedCorpora();
      if (!deleted.length) return;
      const ids = (activeSources?.corpus_ids ?? []).filter((id) => !deleted.includes(String(id)));
      const next = { ...activeSources, corpus_ids: ids };
      activeSourcesRef.current = next;
      setActiveSources(next);
    } catch (error) {
      console.error('[ChatInterface] Failed to delete unindexed corpora:', error);
    }
  }, [activeSources, deleteUnindexedCorpora]);

  const handleNewChat = useCallback(() => {
    const session = createChatSession({
      title: 'New chat',
      messages: [],
      modelOverride: modelOverrideRef.current,
      sources: defaultSourcesRef.current(),
      chatHistoryMax,
    });
    const nextConversationId = String(session.conversation_id || '').trim();
    setChatSessions((prev) => {
      let next = [session, ...prev];
      next.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
      if (next.length > MAX_CHAT_SESSIONS) next = next.slice(0, MAX_CHAT_SESSIONS);
      persistSessions(next, nextConversationId);
      return next;
    });
    sessionsLoadedRef.current = true;
    activateSession(session);
  }, [activateSession, chatHistoryMax, persistSessions]);

  const handleClear = useCallback(async () => {
    const activeId = String(conversationIdRef.current || '').trim();
    const activeTitle = chatSessions.find((session) => String(session.conversation_id || '').trim() === activeId)?.title || 'this chat';
    const proceed = await confirmDialog({
      title: 'Delete chat',
      message: `Delete "${activeTitle}"?\n\nThis removes it from the local chat history. Recall memory is not deleted.`,
      confirmLabel: 'Delete chat',
      danger: true,
    });
    if (!proceed) {
      return;
    }

    let remaining = chatSessions.filter((session) => String(session.conversation_id || '').trim() !== activeId);
    remaining.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
    if (remaining.length === 0) {
      remaining = [
        createChatSession({
          title: 'New chat',
          messages: [],
          modelOverride: modelOverrideRef.current,
          sources: defaultSourcesRef.current(),
          chatHistoryMax,
        }),
      ];
    }

    const nextActive = remaining[0];
    setChatSessions(remaining);
    sessionsLoadedRef.current = true;
    persistSessions(remaining, String(nextActive.conversation_id || '').trim());
    activateSession(nextActive);
  }, [activateSession, chatHistoryMax, chatSessions, persistSessions]);

  const handleSelectSession = useCallback(
    (session: ReturnType<typeof createChatSession>) => {
      persistSessions(chatSessions, String(session.conversation_id || '').trim());
      activateSession(session);
    },
    [activateSession, chatSessions, persistSessions],
  );

  const handleExport = useCallback(() => {
    const exportData = {
      exported: new Date().toISOString(),
      conversation_id: conversationIdRef.current,
      messages: messagesRef.current.map((message) => ({
        role: message.role,
        createdAt: message.createdAt.toISOString(),
        text: getMessageText(message),
        custom: getMessageCustom(message),
      })),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `chat-export-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, []);

  const handleCopy = useCallback((content: string) => {
    navigator.clipboard.writeText(content);
  }, []);

  const handleViewTraceAndLogs = useCallback((message: ThreadMessage) => {
    const custom = getMessageCustom(message);
    window.dispatchEvent(
      new CustomEvent('tribrid:chat:open-trace', {
        detail: {
          run_id: custom.runId || custom.eventId,
          started_at_ms: custom.startedAtMs,
          ended_at_ms: custom.endedAtMs,
        },
      }),
    );
    const traceElement = document.getElementById('chat-trace') as HTMLDetailsElement | null;
    if (traceElement) {
      traceElement.open = true;
      traceElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, []);

  return (
    <div
      data-react-chat="true"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '70vh',
        border: '1px solid var(--line)',
        borderRadius: '18px',
        overflow: 'hidden',
        background: 'var(--card-bg)',
      }}
    >
      <div
        style={{
          padding: '14px 18px',
          borderBottom: '1px solid var(--line)',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '12px',
          alignItems: 'center',
          background: 'linear-gradient(180deg, var(--bg-elev1) 0%, rgba(255,255,255,0.02) 100%)',
        }}
      >
        <div style={{ flexShrink: 0 }}>
          <h3 style={{ margin: '0 0 4px 0', fontSize: '14px', fontWeight: 700 }}>
            Chat Workbench
          </h3>
          <p style={{ margin: 0, fontSize: '11px', color: 'var(--fg-muted)' }}>
            assistant-ui runtime with ragweld recall and source grounding
          </p>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', flex: '1 1 auto', minWidth: 0 }}>
          <SourceDropdown
            value={activeSources}
            onChange={(next) => {
              activeSourcesRef.current = next;
              setActiveSources(next);
              if (!(next.corpus_ids ?? []).includes('recall_default')) setRecallIntensity(null);
            }}
            corpora={repos}
            includeVector={includeVector}
            includeSparse={includeSparse}
            includeGraph={includeGraph}
            onIncludeVectorChange={setIncludeVector}
            onIncludeSparseChange={setIncludeSparse}
            onIncludeGraphChange={setIncludeGraph}
            recallIntensity={recallIntensity}
            onRecallIntensityChange={setRecallIntensity}
            onCleanupUnindexed={handleCleanupUnindexed}
            webEnabled={webEnabled}
            onWebEnabledChange={setWebEnabled}
          />

          <div style={{ flex: '1 1 220px', minWidth: '180px', maxWidth: '360px' }}>
            <ModelPicker value={modelOverride} onChange={setModelOverride} models={chatModels} />
          </div>

          <button
            type="button"
            onClick={handleExport}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--accent-text)',
              border: '1px solid var(--accent)',
              padding: '8px 12px',
              borderRadius: '12px',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            Export
          </button>

          <button
            type="button"
            onClick={() => setShowHistory((current) => !current)}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              border: '1px solid var(--line)',
              padding: '8px 12px',
              borderRadius: '12px',
              fontSize: '12px',
              cursor: 'pointer',
            }}
            aria-label="Toggle history"
          >
            History
          </button>

          <button
            data-testid="chat-new-chat"
            type="button"
            onClick={handleNewChat}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--accent-text)',
              border: '1px solid var(--accent)',
              padding: '8px 12px',
              borderRadius: '12px',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            New chat
          </button>

          <button
            type="button"
            onClick={handleClear}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--err)',
              border: '1px solid var(--err)',
              padding: '8px 12px',
              borderRadius: '12px',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            Delete
          </button>

          <button
            type="button"
            data-testid="chat-quick-settings"
            aria-expanded={showSettings}
            onClick={() => setShowSettings((current) => !current)}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              border: '1px solid var(--line)',
              padding: '8px 12px',
              borderRadius: '12px',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            Settings
          </button>
        </div>
      </div>

      <EmbeddingMismatchWarning variant="inline" showActions={true} />

      {(() => {
        const selected = (activeSources?.corpus_ids ?? []).filter((id) => id && id !== 'recall_default');
        const selectedCorpora = selected
          .map((id) => repos.find((repo) => repo.corpus_id === id))
          .filter(Boolean) as Array<(typeof repos)[number]>;
        const unindexed = selectedCorpora.filter((corpus) => !corpus.last_indexed);
        if (unindexed.length === 0) return null;
        const names = unindexed.map((corpus) => corpus.name || corpus.corpus_id).join(', ');
        return (
          <div
            role="alert"
            style={{
              background: 'linear-gradient(135deg, rgba(255, 170, 0, 0.1) 0%, rgba(255, 170, 0, 0.05) 100%)',
              borderBottom: '1px solid var(--warn)',
              padding: '12px 16px',
            }}
          >
            <div style={{ fontWeight: 700, color: 'var(--warn)', fontSize: '13px', marginBottom: '4px' }}>
              Not indexed yet
            </div>
            <div style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
              Selected corpora are not indexed ({names}). Go to
              {' '}
              <a href="/web/rag?subtab=indexing" style={{ color: 'var(--link)', textDecoration: 'underline' }}>
                RAG - Indexing
              </a>
              {' '}
              before expecting grounded retrieval results.
            </div>
          </div>
        );
      })()}

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {showHistory && (
          <ChatHistorySidebar
            sessions={chatSessions}
            activeConversationId={String(conversationId || '').trim()}
            onSelectSession={handleSelectSession}
            onNewChat={handleNewChat}
            onDeleteChat={handleClear}
          />
        )}

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <AssistantRuntimeProvider runtime={runtime}>
            <ThreadPrimitive.Root
              style={{
                display: 'flex',
                flexDirection: 'column',
                flex: 1,
                minHeight: 0,
              }}
            >
              <ThreadPrimitive.Viewport
                ref={messagesContainerRef}
                style={{
                  flex: 1,
                  overflowY: 'auto',
                  padding: '18px',
                  minHeight: 0,
                }}
              >
                <AuiIf condition={(state) => state.thread.isEmpty}>
                  <ThreadWelcome onPromptSelect={(prompt) => handleSend(prompt, [])} />
                </AuiIf>

                <ThreadPrimitive.Messages>
                  {() => (
                    <AssistantThreadMessage
                      messageFeedback={messageFeedback}
                      onCopy={handleCopy}
                      onSendFeedback={(message, signal) => {
                        const custom = getMessageCustom(message);
                        void sendFeedback(custom.eventId ?? custom.runId, message.id, signal);
                      }}
                      onViewTraceAndLogs={handleViewTraceAndLogs}
                      renderAssistantContent={(content) => <AssistantMarkdown content={content} />}
                      showCitations={chatShowCitations}
                      showConfidence={chatShowConfidence}
                      showDebugFooter={chatShowDebugFooter}
                      showRecallGateSignals={recallGateShowSignals}
                    />
                  )}
                </ThreadPrimitive.Messages>

                <ThreadPrimitive.ViewportFooter
                  style={{
                    position: 'sticky',
                    bottom: 0,
                    display: 'flex',
                    justifyContent: 'center',
                    padding: '8px 0 0 0',
                    pointerEvents: 'none',
                  }}
                >
                  <ThreadPrimitive.ScrollToBottom asChild>
                    <button
                      type="button"
                      style={{
                        pointerEvents: 'auto',
                        borderRadius: '999px',
                        border: '1px solid var(--line)',
                        background: 'var(--bg-elev1)',
                        color: 'var(--fg)',
                        padding: '8px 12px',
                        fontSize: '11px',
                        cursor: 'pointer',
                        boxShadow: '0 12px 30px rgba(0,0,0,0.18)',
                      }}
                    >
                      Jump to latest
                    </button>
                  </ThreadPrimitive.ScrollToBottom>
                </ThreadPrimitive.ViewportFooter>
              </ThreadPrimitive.Viewport>
            </ThreadPrimitive.Root>
          </AssistantRuntimeProvider>

          <div
            style={{
              padding: '16px',
              borderTop: '1px solid var(--line)',
              background: 'linear-gradient(180deg, rgba(255,255,255,0.02) 0%, var(--bg-elev1) 100%)',
              display: 'grid',
              gap: '12px',
            }}
          >
            <ChatComposer
              blockedReason={chatBlockedReason}
              multimodal={multimodalCfg}
              onCancel={() => resetTransientChatState('user_cancel')}
              onSend={handleSend}
              sending={sending}
            />

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '11px', color: 'var(--fg-muted)', fontWeight: 700 }}>Retrieval legs:</span>
              {[
                { id: 'vector', label: 'Vector', enabled: includeVector, set: setIncludeVector },
                { id: 'sparse', label: 'Sparse', enabled: includeSparse, set: setIncludeSparse },
                { id: 'graph', label: 'Graph', enabled: includeGraph, set: setIncludeGraph },
              ].map((toggle) => (
                <button
                  key={toggle.id}
                  type="button"
                  onClick={() => toggle.set(!toggle.enabled)}
                  aria-pressed={toggle.enabled}
                  data-testid={`chat-toggle-${toggle.id}`}
                  style={{
                    padding: '6px 10px',
                    borderRadius: '999px',
                    border: toggle.enabled ? '1px solid var(--accent)' : '1px solid var(--line)',
                    background: toggle.enabled ? 'rgba(0, 170, 255, 0.12)' : 'var(--bg-elev2)',
                    color: toggle.enabled ? 'var(--fg)' : 'var(--fg-muted)',
                    fontSize: '11px',
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  {toggle.enabled ? 'On ' : 'Off '}
                  {toggle.label}
                </button>
              ))}
            </div>

            <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
              Press Ctrl+Enter to send. Final message metadata keeps citations, recall decisions, run IDs, and trace headers.
            </div>
          </div>
        </div>

        {showSettings && (
          <div
            style={{
              width: '280px',
              borderLeft: '1px solid var(--line)',
              padding: '16px',
              overflowY: 'auto',
              background: 'var(--bg-elev1)',
            }}
          >
            <h4 style={{ margin: '0 0 16px 0', fontSize: '13px', fontWeight: 700 }}>
              Quick Settings
            </h4>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--fg-muted)', marginBottom: '4px' }}>
                Temperature: {temperature}
              </label>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={temperature}
                onChange={(event) => setTemperature(parseFloat(event.target.value))}
                style={{ width: '100%' }}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--fg-muted)', marginBottom: '4px' }}>
                Max Tokens
              </label>
              <input
                type="number"
                value={maxTokens}
                onChange={(event) => setMaxTokens(parseInt(event.target.value, 10))}
                min="100"
                max="16384"
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '8px',
                  fontSize: '12px',
                }}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label
                htmlFor="chat-top-k"
                style={{ display: 'block', fontSize: '12px', fontWeight: 700, color: 'var(--fg-muted)', marginBottom: '4px' }}
              >
                Top-K (results) for this conversation
              </label>
              <input
                id="chat-top-k"
                data-testid="chat-top-k"
                type="number"
                value={topKDisplay ?? ''}
                placeholder={conversationCorpusId ? '' : 'Select a corpus'}
                onChange={(event) => {
                  const raw = event.target.value.trim();
                  const next = raw === '' ? null : Math.max(1, Math.min(100, parseInt(raw, 10) || 1));
                  topKOverrideRef.current = next;
                  setTopKOverride(next);
                }}
                min="1"
                max="100"
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '8px',
                  fontSize: '14px',
                }}
              />
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '4px', lineHeight: 1.45 }}>
                {topKOverride === null
                  ? conversationCorpusId
                    ? `Using ${conversationCorpusId}'s configured default.`
                    : 'Select a corpus in Sources to set retrieval breadth.'
                  : `Overrides ${conversationCorpusId || 'the corpus'} default for this conversation only; the corpus config is unchanged.`}
              </div>
            </div>
          </div>
        )}
      </div>

      <StatusBar
        sources={activeSources}
        matches={lastMatches}
        latencyMs={lastLatencyMs}
        recallPlan={lastRecallPlan}
        showRecallGateDecision={recallGateShowDecision}
      />
    </div>
  );
}
