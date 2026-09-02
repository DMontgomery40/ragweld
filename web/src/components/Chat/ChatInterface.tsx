import type React from 'react';
import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useNavigationType } from 'react-router-dom';
import {
  AssistantRuntimeProvider,
  AuiIf,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useExternalStoreRuntime,
} from '@assistant-ui/react';
import { AssistantMarkdown } from '@/components/ui/AssistantMarkdown';
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
  CHAT_SESSIONS_CHANGED_EVENT,
  defaultChatSources,
  getMessageCustom,
  getMessageImages,
  getMessageText,
  LEGACY_CHAT_HISTORY_STORAGE_KEY,
  LEGACY_CHAT_SESSIONS_STORAGE_KEY,
  loadChatSessionsFromStorage,
  persistChatSessions as persistChatSessionsToStorage,
  reconcileInterruptedMessages,
  setMessageCustom,
  upsertChatSession,
} from '@/components/Chat/chatSessions';
import type { RagweldMessageCustom } from '@/components/Chat/chatSessions';
import {
  ChatRequestFailedError,
  ChatStreamEventError,
  type ChatFailedRun,
  sendRagweldChat,
  toAbortReason,
} from '@/components/Chat/chatTransport';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { NumberField } from '@/components/ui/NumberField';
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
// A user pressing Stop. Unlike 'superseded'/'session_change'/'unmount', a Stop (and a
// timeout) has no successor turn that owns the UI, so its catch handler must finalize the
// in-flight assistant message even though resetTransientChatState already bumped the request
// token (leaving it 'running' forever was M-93/B-07).
const CHAT_REQUEST_ABORT_USER_CANCEL = 'user_cancel';
const DEFAULT_CHAT_REQUEST_TIMEOUT_MS = 600_000;
const MAX_CHAT_SESSIONS = 50;

const WELCOME_PROMPTS = [
  'What are the main topics covered in this corpus?',
  'Summarize the most relevant document for a question I ask.',
  'What kinds of questions can I ask about this corpus?',
];

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

type ChatComposerProps = {
  blockedReason?: string | null;
  multimodal: ChatMultimodalConfig | null;
  onCancel?: () => void;
  onSend: (text: string, images: ImageAttachment[]) => void;
  sending: boolean;
};

/** Composer-local view of a pending attachment: the wire fields plus the file's own name/size
 * so the preview can say what is about to be sent (B-25). Only base64 + mime_type cross the
 * wire; name/size are UI state and never become a wire contract. */
type ComposerAttachment = ImageAttachment & { name: string; size: number };

function formatAttachmentSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const ChatComposer = memo(function ChatComposer({ blockedReason, multimodal, onCancel, onSend, sending }: ChatComposerProps) {
  const { showToast } = useUIHelpers();
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
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
      const nonImages = files.filter((file) => !(file && typeof file.type === 'string' && file.type.startsWith('image/')));
      if (nonImages.length) {
        // Previously these were silently dropped, so an operator who picked a PDF or a .zip got
        // no feedback at all (B-25). Name what was refused and why.
        const names = nonImages.map((file) => file.name || 'file').slice(0, 3).join(', ');
        showToast(`Only image files can be attached. Skipped: ${names}${nonImages.length > 3 ? ', …' : ''}`, 'error');
      }
      if (!imageFiles.length) return;

      const room = Math.max(0, maxImages - attachments.length);
      if (room <= 0) {
        showToast(`Max ${maxImages} images per message.`, 'error');
        return;
      }

      const selected = imageFiles.slice(0, room);
      const maxBytes = maxImageSizeMb * 1024 * 1024;
      const next: ComposerAttachment[] = [];
      for (const file of selected) {
        const mime = String(file.type || 'image/png');
        const ext = (mime.split('/', 2)[1] || '').toLowerCase();
        const normalizedExt = ext === 'jpg' ? 'jpeg' : ext;
        if (supportedFormats.length) {
          const allowed = new Set<string>(supportedFormats);
          if (allowed.has('jpg')) allowed.add('jpeg');
          if (allowed.has('jpeg')) allowed.add('jpg');
          if (normalizedExt && !allowed.has(normalizedExt)) {
            showToast(`Unsupported image type: ${mime} (allowed: ${supportedFormats.join(', ')})`, 'error');
            continue;
          }
        }
        if (typeof file.size === 'number' && file.size > maxBytes) {
          showToast(`"${file.name || 'image'}" is too large (${formatAttachmentSize(file.size)}; max ${maxImageSizeMb} MB).`, 'error');
          continue;
        }
        const base64 = await fileToBase64NoPrefix(file);
        if (!base64) {
          showToast('Failed to read image.', 'error');
          continue;
        }
        next.push({ base64, mime_type: mime, name: String(file.name || 'image'), size: Number(file.size || 0) });
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
    // Only the wire fields leave the composer; name/size are UI-only and the wire
    // ImageAttachment forbids extra keys.
    onSend(trimmed, attachments.map((attachment) => ({ base64: attachment.base64, mime_type: attachment.mime_type })));
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

  // Docked, the composer sits in a ~280-360px pane whose body inherits
  // `overflow-wrap: anywhere` (DockPanel, A-44). A textarea's automatic minimum width is its
  // intrinsic 20-column size, so the text column refused to shrink, the button column paid,
  // and anywhere-wrapping split "Send" into S/e/n/d and "Attach" into Att/ach (S36). The text
  // column is the only thing allowed to shrink; the buttons keep their labels on one line.
  return (
    <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end', minWidth: 0 }}>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
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
            {attachments.map((attachment, index) => {
              const typeLabel = String(attachment.mime_type || '').split('/', 2)[1]?.toUpperCase() || 'IMAGE';
              const sizeLabel = formatAttachmentSize(attachment.size);
              return (
                <div
                  key={index}
                  data-testid={`chat-attachment-${index}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '6px 10px 6px 6px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                    background: 'var(--bg-elev1)',
                    maxWidth: '260px',
                  }}
                >
                  <img
                    src={`data:${attachment.mime_type};base64,${attachment.base64}`}
                    alt={attachment.name || `Attachment ${index + 1}`}
                    style={{
                      width: '44px',
                      height: '44px',
                      objectFit: 'cover',
                      borderRadius: '8px',
                      border: '1px solid var(--line)',
                      flex: '0 0 auto',
                    }}
                  />
                  <div style={{ minWidth: 0, display: 'grid', gap: '2px' }}>
                    <span
                      data-testid={`chat-attachment-name-${index}`}
                      title={attachment.name}
                      style={{
                        fontSize: '12px',
                        fontWeight: 700,
                        color: 'var(--fg)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {attachment.name}
                    </span>
                    <span style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>
                      {typeLabel}
                      {sizeLabel ? ` · ${sizeLabel}` : ''}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setAttachments((prev) => prev.filter((_, current) => current !== index))}
                    aria-label={`Remove ${attachment.name || 'image'}`}
                    data-testid={`chat-attachment-remove-${index}`}
                    style={{
                      marginLeft: 'auto',
                      flex: '0 0 auto',
                      width: '22px',
                      height: '22px',
                      borderRadius: '999px',
                      border: '1px solid var(--line)',
                      background: 'var(--bg-elev2)',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      lineHeight: '18px',
                      cursor: 'pointer',
                    }}
                  >
                    x
                  </button>
                </div>
              );
            })}
          </div>
        )}

        <textarea
          id="chat-input"
          ref={textareaRef}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Ask ragweld about this corpus..."
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
            minWidth: 0,
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

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flexShrink: 0 }}>
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
            whiteSpace: 'nowrap',
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
            whiteSpace: 'nowrap',
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
  onRetry: (messageId: string) => void;
  onSendFeedback: (message: ThreadMessage, signal: string) => void;
  onViewTraceAndLogs: (message: ThreadMessage) => void;
  renderAssistantContent: (content: string) => React.ReactNode;
  showCitations: boolean;
  showConfidence: boolean;
  showDebugFooter: boolean;
  showRecallGateSignals: boolean;
};

/** Live elapsed counter shown while an assistant answer is streaming. The drive's 92.7 s wait
 * showed only a static "Streaming" with no elapsed time and no sign of progress (B-24/M-97);
 * the backend's per-leg spans are emitted on the streaming path this lane does not own, so this
 * is the client-side half: a ticking elapsed time so the operator can see it is still working. */
const StreamingElapsed = memo(function StreamingElapsed({ startedAtMs }: { startedAtMs: number }) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const seconds = Math.max(0, Math.floor((nowMs - startedAtMs) / 1000));
  return (
    <span data-testid="chat-streaming-elapsed" style={{ color: 'var(--accent-text)', fontWeight: 700 }}>
      Streaming · {seconds}s
    </span>
  );
});

function formatConfidence(value?: number | null): string | null {
  if (value === undefined || value === null || Number.isNaN(value)) return null;
  const percent = value <= 1 ? value * 100 : value;
  return `${percent.toFixed(1)}%`;
}

/** The identity a failed send shares with a successful one, taken from the stream's `done`
 * event: the run the trace store recorded plus the request's trace headers. Feedback and the
 * Trace button key off the same fields, so a failed answer can be traced like any other. */
function failedRunCustom(run: ChatFailedRun | null): Partial<RagweldMessageCustom> {
  if (!run) return {};
  return {
    correlationId: run.headers.correlationId,
    endedAtMs: run.endedAtMs,
    eventId: run.runId,
    rootSpanId: run.headers.rootSpanId,
    runId: run.runId,
    startedAtMs: run.startedAtMs,
    traceId: run.headers.traceId,
  };
}

function StructuredErrorCard({
  error,
  runId,
}: {
  error: NonNullable<RagweldMessageCustom['structuredError']>;
  runId?: string;
}) {
  const action = error.required_action || error.operator_hint || '';
  const detailEntries: [string, unknown][] = [];
  if (error.operation) detailEntries.push(['operation', error.operation]);
  // The provider's own words (sanitised server-side) and how the server classified them:
  // the hint above is chosen from these, so the operator can check the classification.
  if (error.failure_kind) detailEntries.push(['failure class', error.failure_kind]);
  if (error.gateway_reason) detailEntries.push(['reason', error.gateway_reason]);
  if (runId) detailEntries.push(['run id', runId]);
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
            <StreamingElapsed startedAtMs={custom.startedAtMs ?? message.createdAt.getTime()} />
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
                  ? 'var(--ok)'
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
              <StructuredErrorCard error={custom.structuredError} runId={custom.runId || custom.eventId} />
            ) : isAssistantError ? (
              <div
                data-testid="chat-assistant-error"
                style={{
                  marginTop: '10px',
                  padding: '10px 12px',
                  borderRadius: '10px',
                  background: 'rgba(214, 79, 79, 0.12)',
                  border: '1px solid rgba(214, 79, 79, 0.35)',
                  color: 'var(--fg)',
                  fontSize: '12.5px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '12px',
                  flexWrap: 'wrap',
                }}
              >
                <span>
                  {(messageStatus?.type === 'incomplete' && typeof messageStatus.error === 'string' && messageStatus.error) ||
                    'Generation ended with an error.'}
                </span>
                <button
                  type="button"
                  data-testid="chat-retry"
                  onClick={() => props.onRetry(message.id)}
                  style={{
                    background: 'var(--bg-elev2)',
                    color: 'var(--accent-text)',
                    border: '1px solid var(--accent)',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    fontSize: '12px',
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  Retry
                </button>
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

        {props.showCitations &&
          (sources.length > 0 || legacyCitations.length > 0 || webCitations.length > 0 || (custom.attachedImageCount ?? 0) > 0) && (
            <SourceList
              sources={sources}
              legacyCitations={legacyCitations}
              webCitations={webCitations}
              attachedImageCount={custom.attachedImageCount ?? 0}
            />
          )}

        <div
          style={{
            marginTop: '10px',
            fontSize: '11.5px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '10px',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <button
              type="button"
              onClick={() => props.onCopy(text)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--fg-muted)',
                cursor: 'pointer',
                padding: '0',
                fontSize: '11.5px',
                fontWeight: 600,
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
                  color: 'var(--fg-muted)',
                  cursor: 'pointer',
                  padding: '0',
                  fontSize: '11.5px',
                  fontWeight: 600,
                }}
              >
                Trace
              </button>
            ) : null}
          </div>

          {message.role === 'assistant' ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginLeft: 'auto' }}>
              {props.messageFeedback[message.id] ? (
                <span style={{ color: 'var(--ok)', fontWeight: 700 }}>Feedback saved</span>
              ) : (
                <>
                  <button
                    type="button"
                    data-testid="chat-feedback-thumbsup"
                    onClick={() => props.onSendFeedback(message, 'thumbsup')}
                    style={{ background: 'none', border: 'none', color: 'var(--ok)', cursor: 'pointer', fontSize: '12px', fontWeight: 700, padding: 0 }}
                  >
                    Helpful
                  </button>
                  <button
                    type="button"
                    data-testid="chat-feedback-thumbsdown"
                    onClick={() => props.onSendFeedback(message, 'thumbsdown')}
                    style={{ background: 'none', border: 'none', color: 'var(--fg-muted)', cursor: 'pointer', fontSize: '12px', fontWeight: 700, padding: 0 }}
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
            {typeof custom.debug.graph_enabled === 'boolean' ? (
              // The graph leg's own accounting, verbatim from the chat debug contract:
              // Qdrant-seeded traversal, relationship expansion, hydrated chunks. There is no
              // entity-hit figure any more, so none is shown (Task 8 drive, step 7).
              <div data-testid="chat-debug-graph">
                graph: graph_enabled={String(custom.debug.graph_enabled)}
                {' '}graph_qdrant_seed_chunks={String(custom.debug.graph_qdrant_seed_chunks ?? 0)}
                {' '}graph_relationship_expansion_hits={String(custom.debug.graph_relationship_expansion_hits ?? 0)}
                {' '}graph_hydrated_chunks={String(custom.debug.graph_hydrated_chunks ?? 0)}
              </div>
            ) : null}
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
        {WELCOME_PROMPTS.map((prompt, index) => (
          <button
            key={prompt}
            type="button"
            data-testid={`chat-welcome-prompt-${index}`}
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

export function ChatInterface() {
  const { api } = useAPI();
  const { config } = useConfig();
  const { showToast } = useUIHelpers();
  const { status: embeddingStatus, loading: embeddingStatusLoading, error: embeddingStatusError } = useEmbeddingStatus();
  const { repos, loadRepos, initialized, activeRepo, deleteUnindexedCorpora } = useRepoStore();
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();

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

  // D20: the page-level corpus (`?corpus=`, the top-bar switcher) and a used conversation's
  // Sources are allowed to disagree - a used thread is never rewritten (M-03/B-04). What is
  // not allowed is hiding the disagreement: the drive opened `/chat?corpus=X` over a thread
  // answered from Y, the answer searched Y and honestly found nothing about X. An unused
  // thread already follows the active corpus, so only a thread with messages can mismatch.
  const activeRepoId = String(activeRepo || '').trim();
  const activeRepoLabel = useMemo(
    () => repos.find((repo) => String(repo.corpus_id) === activeRepoId)?.name || activeRepoId,
    [activeRepoId, repos],
  );
  const activeRepoOutsideSources =
    Boolean(activeRepoId) &&
    messages.length > 0 &&
    !(activeSources?.corpus_ids ?? []).map(String).includes(activeRepoId);

  const chatShowConfidence = config?.ui?.chat_show_confidence ?? false;
  const chatShowCitations = config?.ui?.chat_show_citations ?? true;
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
  // False until the first load off storage. Only that initial hydration reconciles abandoned
  // 'running' messages (M-93); a mirror-triggered reload while another instance streams must
  // NOT, or it would flip the live stream to "interrupted" in the docked copy.
  const hydratedRef = useRef(false);
  const sendingRef = useRef(false);
  /** A mirror event that arrived while this instance was streaming, replayed when it ends. */
  const pendingReloadRef = useRef(false);
  /** Distinguishes this instance's own writes from the other instance's (tab vs dock). */
  const instanceIdRef = useRef(`chat-${Math.random().toString(36).slice(2)}`);
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { messagesRef.current = messages; }, [messages]);
  useEffect(() => { conversationIdRef.current = conversationId; }, [conversationId]);
  useEffect(() => { modelOverrideRef.current = modelOverride; }, [modelOverride]);
  useEffect(() => { activeSourcesRef.current = activeSources; }, [activeSources]);
  useEffect(() => { topKOverrideRef.current = topKOverride; }, [topKOverride]);
  useEffect(() => { sendingRef.current = sending; }, [sending]);

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
      persistChatSessionsToStorage(localStorage, sessions, activeId, { writerId: instanceIdRef.current });
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
      const nextConversationId = String(session.conversation_id || '').trim() || createConversationId();
      // Reloading the SAME conversation is a mirror of the docked instance, not a session
      // change: it must not abort a request, clear the status bar, or silently drop the
      // operator's per-conversation Top-K. Only an actual switch resets those.
      const sameConversation = nextConversationId === conversationIdRef.current;
      if (!sameConversation) resetTransientChatState('session_change');
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
      const sessionSources = (session.sources || defaultChatSources()) as ActiveSources;
      activeSourcesRef.current = sessionSources;
      setActiveSources(sessionSources);
      if (!sameConversation) {
        topKOverrideRef.current = null;
        setTopKOverride(null);
        setLastMatches([]);
        setLastLatencyMs(null);
        setLastRecallPlan(null);
      }
    },
    [chatHistoryMax, resetTransientChatState],
  );

  const loadChatHistory = useCallback(() => {
    try {
      const loaded = loadChatSessionsFromStorage(localStorage, chatHistoryMax);
      const { removeLegacyHistory } = loaded;
      let { sessions, activeSession } = loaded;
      // Only the very first hydration cleans abandoned streams (a reload or an un-finalized
      // Stop left them 'running'). A later reload is a mirror of another instance that may be
      // actively streaming; leave its 'running' message alone.
      if (!hydratedRef.current) {
        hydratedRef.current = true;
        const activeId = String(activeSession.conversation_id || '').trim();
        sessions = sessions.map((session) => {
          const { messages, changed } = reconcileInterruptedMessages(session.messages);
          return changed ? { ...session, messages } : session;
        });
        activeSession = sessions.find((s) => String(s.conversation_id || '').trim() === activeId) || sessions[0] || activeSession;
      }
      setChatSessions(sessions);
      sessionsLoadedRef.current = true;
      // persistChatSessions no-ops its broadcast when the bytes are unchanged, so this only
      // rewrites storage (and notifies the dock) when a stream was actually reconciled.
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

  // The chat tab and the docked chat are two instances over one stored thread. Each reloads
  // when the OTHER writes, so the docked copy mirrors the live conversation instead of
  // showing a third, independent state (M-03/B-39). An instance with an answer in flight is
  // never disturbed, and it ignores the echo of its own writes.
  useEffect(() => {
    const onThreadsChanged = (event: Event) => {
      const writerId = (event as CustomEvent<{ writerId?: string }>).detail?.writerId;
      if (writerId && writerId === instanceIdRef.current) return;
      if (sendingRef.current) {
        // Deferred, not dropped. Discarding it left this instance stale for good, and its
        // post-send saveChatHistory would then persist that stale state over whatever the
        // other instance wrote.
        pendingReloadRef.current = true;
        return;
      }
      loadChatHistory();
    };
    window.addEventListener(CHAT_SESSIONS_CHANGED_EVENT, onThreadsChanged);
    return () => window.removeEventListener(CHAT_SESSIONS_CHANGED_EVENT, onThreadsChanged);
  }, [loadChatHistory]);

  // Drain a mirror event that arrived mid-stream once the answer has landed.
  useEffect(() => {
    if (sending) return;
    if (!pendingReloadRef.current) return;
    pendingReloadRef.current = false;
    loadChatHistory();
  }, [loadChatHistory, sending]);

  // Initial load, and a reload when the loader's inputs change - but NEVER mid-send. This used
  // to also live in the unmount effect below, whose cleanup then aborted and nulled the
  // in-flight request every time `loadChatHistory`'s identity changed (config settling churned
  // it through activateSession -> a since-deleted trace callback keyed on chat_show_trace). A
  // send in flight when that happened lost its abort controller, so a later Stop had nothing
  // to abort and the answer stayed "Streaming" forever (M-93). Reloading history over a live
  // answer would also drop its accumulation, so this defers while sending, exactly like the
  // mirror listener.
  useEffect(() => {
    if (sendingRef.current) return;
    loadChatHistory();
  }, [loadChatHistory]);

  // Abort any in-flight request only on a real unmount, never on a dependency change.
  useEffect(() => {
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
  }, []);

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

        const attachedImageCount = getMessageImages(userMessage).length;
        const custom = {
          attachedImageCount: attachedImageCount > 0 ? attachedImageCount : undefined,
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
        // A user Stop ('user_cancel') or a timeout must finalize THIS assistant message even
        // though resetTransientChatState already bumped the request token — there is no
        // successor turn, and the early token guard is what left the bubble 'running' forever
        // (M-93). A 'superseded'/'session_change'/'unmount' abort, and any non-abort error,
        // keep the guard: a newer turn or view owns the UI and must not be clobbered.
        const userInitiatedAbort =
          abortReason === CHAT_REQUEST_ABORT_TIMEOUT || abortReason === CHAT_REQUEST_ABORT_USER_CANCEL;
        if (!userInitiatedAbort && !isRequestTokenActive(requestToken)) return;

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
        // A failure the stream reported after the server had started a run carries that run;
        // it is published exactly like a success so the Routing Trace panel follows it.
        const failedRun =
          error instanceof ChatRequestFailedError || error instanceof ChatStreamEventError ? error.run : null;
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
              { ...getMessageCustom(assistant), ...failedRunCustom(failedRun), structuredError: structured },
            ),
          );
          saveChatHistory(failedMessages);
          if (failedRun) emitRunComplete(failedRun.runId, failedRun.startedAtMs, failedRun.endedAtMs);
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
            { ...getMessageCustom(assistant), ...failedRunCustom(failedRun) },
          ),
        );
        saveChatHistory(failedMessages);
        if (failedRun) emitRunComplete(failedRun.runId, failedRun.startedAtMs, failedRun.endedAtMs);
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
      resetTransientChatState(CHAT_REQUEST_ABORT_USER_CANCEL);
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

  // Re-run the user turn behind a failed or interrupted assistant message. Both the interrupted
  // bubble and the user message that prompted it are dropped, then the user message is replayed
  // (runUserTurn re-appends it), so the thread does not accumulate a duplicate question (B-07).
  // Any images survive only while they are still in the message content (a reload strips them),
  // which is the honest limit of a text-first retry.
  const handleRetry = useCallback(
    (assistantId: string) => {
      if (sendingRef.current) return;
      const current = messagesRef.current;
      const assistantIndex = current.findIndex((message) => message.id === assistantId && message.role === 'assistant');
      if (assistantIndex < 0) return;
      let userIndex = -1;
      for (let i = assistantIndex - 1; i >= 0; i -= 1) {
        if (current[i].role === 'user') {
          userIndex = i;
          break;
        }
      }
      if (userIndex < 0) return;
      const priorUser = current[userIndex] as ThreadUserMessage;
      const replayUser: ThreadUserMessage = {
        ...priorUser,
        id: `user-${Date.now()}-retry`,
        createdAt: new Date(),
      };
      const trimmed = current.filter((_, index) => index !== assistantIndex && index !== userIndex);
      messagesRef.current = trimmed;
      setMessages(trimmed);
      saveChatHistory(trimmed);
      void runUserTurn(replayUser);
    },
    [runUserTurn, saveChatHistory],
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

  // Same path as a tick in the Sources picker: ref + state, and the sources->session effect
  // persists it. Appending never drops recall, so the recall intensity is left alone.
  const handleAddActiveCorpus = useCallback(() => {
    if (!activeRepoId) return;
    const current = activeSourcesRef.current || activeSources || defaultChatSources();
    const ids = (current.corpus_ids ?? []).map(String);
    if (ids.includes(activeRepoId)) return;
    const next = { ...current, corpus_ids: [...ids, activeRepoId] };
    activeSourcesRef.current = next;
    setActiveSources(next);
  }, [activeRepoId, activeSources]);

  // `?thread=new` is a deep link meaning "chat about this corpus in a fresh conversation"
  // (StartTab's Open Chat). It fires once sessions and the active corpus are settled, so the
  // new thread's default sources include the URL corpus, and it is consumed by rewriting the
  // URL through the router: a window-level replaceState would be undone by the next subtab
  // navigation, which rebuilds the query string from react-router's own location. That
  // rebuild can also resurrect the param once (the subtab hook's ensure-in-URL replace runs
  // in the same commit with the pre-strip search), so a REPLACE that carries it again is
  // stripped without minting a second thread; only a fresh PUSH is a new deep link. The
  // docked copy renders under a synthetic location and never sees the param. An unused
  // active thread already follows the active corpus, so it is the fresh thread.
  //
  // The thread itself is created in a later commit, through state, never from the mount
  // effect pass: handleNewChat persists inside a setChatSessions updater that runs on the
  // next render, and StrictMode's second effect pass on mount re-runs loadChatHistory
  // before that, re-hydrating the old thread over the one just created.
  const threadDeepLinkConsumedKeyRef = useRef<string | null>(null);
  const [threadDeepLinkPending, setThreadDeepLinkPending] = useState(false);
  useEffect(() => {
    if (!initialized || !config || !activeRepoId) return;
    if (!sessionsLoadedRef.current) return;
    const params = new URLSearchParams(location.search || '');
    if (params.get('thread') !== 'new') return;
    const consumedKey = threadDeepLinkConsumedKeyRef.current;
    const fresh = consumedKey === null || (navigationType === 'PUSH' && consumedKey !== location.key);
    threadDeepLinkConsumedKeyRef.current = location.key;
    params.delete('thread');
    const search = params.toString();
    navigate({ pathname: location.pathname, search: search ? `?${search}` : '' }, { replace: true });
    if (fresh && messagesRef.current.length > 0) setThreadDeepLinkPending(true);
  }, [
    activeRepoId,
    config,
    handleNewChat,
    initialized,
    location.key,
    location.pathname,
    location.search,
    navigate,
    navigationType,
  ]);
  useEffect(() => {
    if (!threadDeepLinkPending) return;
    setThreadDeepLinkPending(false);
    handleNewChat();
  }, [handleNewChat, threadDeepLinkPending]);

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
    const exportMessages = messagesRef.current;
    if (exportMessages.length === 0) {
      showToast('Nothing to export yet — this chat has no messages.', 'info');
      return;
    }
    const exportData = {
      exported: new Date().toISOString(),
      conversation_id: conversationIdRef.current,
      messages: exportMessages.map((message) => ({
        role: message.role,
        createdAt: message.createdAt.toISOString(),
        text: getMessageText(message),
        custom: getMessageCustom(message),
      })),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const filename = `chat-export-${Date.now()}.json`;
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    anchor.style.display = 'none';
    // The anchor must be in the document and the object URL must outlive the click: the old
    // code called URL.revokeObjectURL synchronously on the next line, which cancels the
    // download in Chromium before it starts (B-26 — "no download, ~/Downloads unchanged").
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    showToast(`Exported ${exportMessages.length} message${exportMessages.length === 1 ? '' : 's'} to ${filename}.`, 'success');
  }, [showToast]);

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
        // At short desktop window heights, 70vh left less than 100px between the
        // toolbar and composer. Citation/feedback controls then occupied the same
        // screen coordinates as the status bar and could not be clicked. Keep a
        // usable message viewport; the surrounding tab remains the page scroller.
        height: 'clamp(560px, 70vh, 760px)',
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
            data-testid="chat-export"
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
            data-testid="chat-history-toggle"
            aria-expanded={showHistory}
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

        {activeRepoOutsideSources ? (
          <div
            data-testid="chat-active-corpus-mismatch"
            role="status"
            style={{
              flex: '1 1 100%',
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'center',
              gap: '8px',
              padding: '6px 10px',
              border: '1px solid var(--line)',
              borderRadius: '10px',
              background: 'var(--bg-elev2)',
              color: 'var(--fg-muted)',
              fontSize: '12.5px',
              lineHeight: 1.4,
            }}
          >
            <span style={{ flex: '1 1 auto', minWidth: 0 }}>
              Active corpus <strong style={{ color: 'var(--fg)' }}>{activeRepoLabel}</strong> is not in this
              conversation&apos;s Sources.
            </span>
            <button
              type="button"
              data-testid="chat-add-active-corpus"
              onClick={handleAddActiveCorpus}
              style={{
                background: 'var(--bg-elev1)',
                color: 'var(--accent-text)',
                border: '1px solid var(--accent)',
                padding: '5px 10px',
                borderRadius: '10px',
                fontSize: '12.5px',
                cursor: 'pointer',
              }}
            >
              Add {activeRepoLabel}
            </button>
            <button
              type="button"
              data-testid="chat-new-thread-active-corpus"
              onClick={handleNewChat}
              style={{
                background: 'var(--bg-elev1)',
                color: 'var(--fg)',
                border: '1px solid var(--line)',
                padding: '5px 10px',
                borderRadius: '10px',
                fontSize: '12.5px',
                cursor: 'pointer',
              }}
            >
              New chat about {activeRepoLabel}
            </button>
          </div>
        ) : null}
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

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
          <AssistantRuntimeProvider runtime={runtime}>
            <ThreadPrimitive.Root
              style={{
                display: 'flex',
                flexDirection: 'column',
                flex: 1,
                minHeight: 0,
                minWidth: 0,
              }}
            >
              <ThreadPrimitive.Viewport
                ref={messagesContainerRef}
                style={{
                  flex: 1,
                  overflowY: 'auto',
                  // A wide code block or an unbreakable string used to grow the whole list
                  // sideways at 1024px (M-97). Clip here; wide code scrolls inside its own
                  // container (AssistantMarkdown) rather than the message list.
                  overflowX: 'hidden',
                  padding: '18px',
                  minHeight: 0,
                  minWidth: 0,
                  // Message controls (citation buttons, thumbs) scrolled flush to this
                  // viewport's edges land under the sticky "Jump to latest" footer or the
                  // composer/status-bar seam; scroll padding keeps scroll-into-view targets
                  // clear of both without force-clicks.
                  scrollPaddingTop: '18px',
                  scrollPaddingBottom: '64px',
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
                      onRetry={handleRetry}
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
              onCancel={() => resetTransientChatState(CHAT_REQUEST_ABORT_USER_CANCEL)}
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
              <NumberField
                configPath="chat.max_tokens"
                value={maxTokens}
                onCommit={setMaxTokens}
                min={100}
                max={16384}
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
              {/*
                Deliberately NOT a NumberField (T5/M-25): this control is a *nullable* override
                -- clearing it and blurring reverts to the corpus's configured final_k
                (`topKDisplay = topKOverride ?? topKBaseline`), it is never itself persisted to
                config. `NumberField.commit()` treats an empty box as "fall back to the last
                committed number" and always calls `onCommit` with a `number`, so it has no way
                to express "the operator cleared this" -- adopting it here would silently break
                the only way to return to the corpus default. Still clamped consistently with
                every other field (1-100, matching the range below) via the same
                Math.max/Math.min pattern NumberField's own clamp uses, just inline.
              */}
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
