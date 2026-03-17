// TriBridRAG - Chat Interface Component
// Main chat UI with message list, input, streaming, and trace panel
// Reference: /assets/chat tab.png, /assets/chat_built_in.png

import type React from 'react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { useAPI, useConfig, useConfigField, useEmbeddingStatus } from '@/hooks';
import { useUIHelpers } from '@/hooks/useUIHelpers';
import { withCorpusScope } from '@/api/client';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { useRepoStore } from '@/stores/useRepoStore';
import { ChatHistorySidebar } from '@/components/Chat/ChatHistorySidebar';
import { SourceDropdown } from '@/components/Chat/SourceDropdown';
import { ModelPicker } from '@/components/Chat/ModelPicker';
import { StatusBar } from '@/components/Chat/StatusBar';
import { ChatMessageThread } from '@/components/Chat/ChatMessageThread';
import {
  clampChatHistory,
  createChatSession,
  createConversationId,
  defaultChatSources,
  LEGACY_CHAT_HISTORY_STORAGE_KEY,
  loadChatSessionsFromStorage,
  persistChatSessions as persistChatSessionsToStorage,
  upsertChatSession,
} from '@/components/Chat/chatSessions';
import {
  sendChatTransport,
  toAbortReason,
} from '@/components/Chat/chatTransport';
import type { ChatSession, Message } from '@/components/Chat/chatSessions';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
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
} from '@/types/generated';

// Useful tips shown during response generation
// Each tip has content and optional category for styling
const TRIBRID_TIPS = [
  // RAG & Search Tips
  { tip: "Use specific file paths like 'server/app.py' to narrow your search to specific areas of the codebase.", category: "search" },
  { tip: "Try asking 'Where is X implemented?' rather than 'What is X?' for more precise code locations.", category: "search" },
  { tip: "Multi-query expansion rewrites your question multiple ways to find more relevant results.", category: "rag" },
  { tip: "The reranker scores results by semantic similarity - higher confidence means better matches.", category: "rag" },
  { tip: "BM25 finds keyword matches while dense search finds semantic meaning - Tri-Brid RAG uses both.", category: "rag" },
  { tip: "Click any citation to open the file directly in VS Code at the exact line number.", category: "ux" },
  { tip: "Fast mode skips reranking for quicker results when you need speed over precision.", category: "rag" },
  { tip: "The confidence score reflects how well the retrieved documents match your query.", category: "rag" },
  
  // Learning Reranker
  { tip: "Every thumbs up/down you give trains the Learning Reranker to better understand your codebase.", category: "feedback" },
  { tip: "The Learning Reranker trains from your mined triplets to improve result ordering over time (MLX Qwen3 on Apple Silicon).", category: "feedback" },
  { tip: "Consistent feedback helps Tri-Brid RAG learn your codebase's unique terminology and patterns.", category: "feedback" },
  { tip: "The reranker model checkpoints are saved automatically - your feedback is never lost.", category: "feedback" },
  
  // Prompts & Models
  { tip: "Custom system prompts let you tailor Tri-Brid RAG's response style to your team's preferences.", category: "config" },
  { tip: "Lower temperature (0.0-0.3) gives more focused answers; higher (0.7+) allows more creativity.", category: "config" },
  { tip: "You can use local models via Ollama for air-gapped environments or cost savings.", category: "config" },
  { tip: "The model automatically fails over to cloud APIs if local inference isn't available.", category: "config" },
  
  // Indexing
  { tip: "Re-index after major refactors to keep Tri-Brid RAG's understanding of your code current.", category: "indexing" },
  { tip: "The AST chunker preserves function boundaries - results always show complete code blocks.", category: "indexing" },
  { tip: "Chunk summaries provide fast, high-level context about files and classes.", category: "indexing" },
  { tip: "Index stats show when your codebase was last indexed - check Dashboard for details.", category: "indexing" },
  
  // Evaluation & Quality
  { tip: "Run evals regularly to track retrieval quality as your codebase evolves.", category: "eval" },
  { tip: "Eval datasets are your benchmark - add questions that matter to your team.", category: "eval" },
  { tip: "MRR (Mean Reciprocal Rank) measures how quickly Tri-Brid RAG finds the right answer.", category: "eval" },
  { tip: "Compare eval runs to see if config changes improved or regressed retrieval quality.", category: "eval" },
  
  // Tracing & Debugging
  { tip: "Enable the Routing Trace to see exactly how Tri-Brid RAG found and ranked your results.", category: "debug" },
  { tip: "Trace steps show timing for each stage: retrieval, reranking, and generation.", category: "debug" },
  { tip: "The provider failover trace shows when Tri-Brid RAG switched between local and cloud models.", category: "debug" },
  { tip: "Use LangSmith integration for detailed traces of the full RAG pipeline.", category: "debug" },
  
  // Keyboard & UX
  { tip: "Press Ctrl+Enter to send messages without clicking the button.", category: "ux" },
  { tip: "Use Ctrl+K anywhere to quickly search settings and jump to any configuration.", category: "ux" },
  { tip: "Export your conversation to JSON for documentation or sharing with teammates.", category: "ux" },
  { tip: "Toggle the side panel to access quick settings without leaving the chat.", category: "ux" },
  
  // Infrastructure
  { tip: "Postgres/pgvector stores your vectors locally - no data leaves your machine unless you use cloud models.", category: "infra" },
  { tip: "Caching can speed up repeated queries (depending on your configuration).", category: "infra" },
  { tip: "The embedded Grafana dashboard shows real-time metrics and query patterns.", category: "infra" },
  { tip: "Docker containers can be configured for different deployment scenarios.", category: "infra" },
  
  // Best Practices
  { tip: "Ask follow-up questions - Tri-Brid RAG maintains context from your conversation history.", category: "best" },
  { tip: "Be specific about what you're looking for: 'error handling in auth' beats 'auth code'.", category: "best" },
  { tip: "If results seem off, try rephrasing - different words can surface different code.", category: "best" },
  { tip: "Check citations to verify the answer - Tri-Brid RAG shows exactly where information came from.", category: "best" },
  { tip: "Use the repo selector to focus on specific repositories in multi-repo setups.", category: "best" },
  
  // Advanced
  { tip: "Each corpus has isolated storage + graph + configuration - switch corpora to change context.", category: "advanced" },
  { tip: "The MCP server enables IDE integrations - ask your editor about your code.", category: "advanced" },
  { tip: "Webhooks can trigger re-indexing automatically when you push code changes.", category: "advanced" },
  { tip: "The CLI supports all chat features for terminal-first workflows.", category: "advanced" },
];

// Shuffle array using Fisher-Yates
function shuffleArray<T>(array: T[]): T[] {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

// Calculate display duration based on tip length (min 3s, ~150 chars/sec reading speed)
function getTipDuration(tip: string): number {
  const wordsPerMinute = 200;
  const words = tip.split(' ').length;
  const readingTimeMs = (words / wordsPerMinute) * 60 * 1000;
  return Math.max(3000, Math.min(readingTimeMs + 1500, 8000)); // 3-8 seconds
}

// Category colors for visual variety
const CATEGORY_COLORS: Record<string, string> = {
  search: 'var(--link)',
  rag: 'var(--accent)',
  feedback: 'var(--success)',
  config: 'var(--warn)',
  indexing: 'var(--info)',
  eval: 'var(--accent)',
  debug: 'var(--fg-muted)',
  ux: 'var(--link)',
  infra: 'var(--info)',
  best: 'var(--success)',
  advanced: 'var(--warn)',
};

const CATEGORY_ICONS: Record<string, string> = {
  search: '🔍',
  rag: '🧠',
  feedback: '👍',
  config: '⚙️',
  indexing: '📑',
  eval: '📊',
  debug: '🔬',
  ux: '✨',
  infra: '🏗️',
  best: '💡',
  advanced: '🚀',
};

const CHAT_REQUEST_ABORT_TIMEOUT = 'timeout';
const DEFAULT_CHAT_REQUEST_TIMEOUT_MS = 120_000;

export interface TraceStep {
  step: string;
  duration: number;
  details: any;
}

interface ChatInterfaceProps {
  traceOpen?: boolean;
  onTraceUpdate?: (steps: TraceStep[], open: boolean, source?: 'config' | 'response' | 'clear') => void;
  onTracePreferenceChange?: (open: boolean) => void;
}

type ChatComposerProps = {
  sending: boolean;
  multimodal: ChatMultimodalConfig | null;
  blockedReason?: string | null;
  onSend: (text: string, images: ImageAttachment[]) => void;
};

const ChatComposer = memo(function ChatComposer({ sending, multimodal, blockedReason, onSend }: ChatComposerProps) {
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

      const imageFiles = files.filter((f) => f && typeof f.type === 'string' && f.type.startsWith('image/'));
      if (!imageFiles.length) return;

      const room = Math.max(0, maxImages - attachments.length);
      if (room <= 0) {
        showToast(`Max ${maxImages} images per message.`, 'error');
        return;
      }

      const selected = imageFiles.slice(0, room);
      const maxBytes = maxImageSizeMb * 1024 * 1024;

      const next: ImageAttachment[] = [];
      for (const f of selected) {
        const mime = String(f.type || 'image/png');
        const ext = (mime.split('/', 2)[1] || '').toLowerCase();
        const extNorm = ext === 'jpg' ? 'jpeg' : ext;
        if (supportedFormats.length) {
          const allowed = new Set<string>(supportedFormats);
          if (allowed.has('jpg')) allowed.add('jpeg');
          if (allowed.has('jpeg')) allowed.add('jpg');
          if (extNorm && !allowed.has(extNorm)) {
            showToast(`Unsupported image type: ${mime}`, 'error');
            continue;
          }
        }
        if (typeof f.size === 'number' && f.size > maxBytes) {
          showToast(`Image too large (max ${maxImageSizeMb} MB).`, 'error');
          continue;
        }

        const base64 = await fileToBase64NoPrefix(f);
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
    [attachments.length, fileToBase64NoPrefix, maxImageSizeMb, maxImages, showToast, supportedFormats, visionEnabled]
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
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const items = Array.from(e.clipboardData?.items || []);
      const imageFiles = items
        .filter((it) => it.kind === 'file' && (it.type || '').startsWith('image/'))
        .map((it) => it.getAsFile())
        .filter(Boolean) as File[];
      if (!imageFiles.length) return;
      e.preventDefault();
      void addFiles(imageFiles);
    },
    [addFiles]
  );

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      e.target.value = '';
      void addFiles(files);
    },
    [addFiles]
  );

  const removeAttachment = useCallback((idx: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  return (
    <div style={{ display: 'flex', gap: '8px', marginBottom: '8px', alignItems: 'flex-end' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {attachments.length > 0 && (
          <div
            data-testid="chat-attachments"
            style={{
              display: 'flex',
              gap: '8px',
              flexWrap: 'wrap',
              padding: '8px',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              background: 'var(--bg-elev2)',
            }}
          >
            {attachments.map((att, idx) => (
              <div
                key={idx}
                data-testid={`chat-attachment-${idx}`}
                style={{
                  position: 'relative',
                  width: '56px',
                  height: '56px',
                  borderRadius: '6px',
                  overflow: 'hidden',
                  border: '1px solid var(--line)',
                  background: 'var(--bg-elev1)',
                }}
                title={att.mime_type}
              >
                <img
                  src={`data:${att.mime_type};base64,${att.base64}`}
                  alt={`Attachment ${idx + 1}`}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
                <button
                  type="button"
                  onClick={() => removeAttachment(idx)}
                  aria-label="Remove image"
                  data-testid={`chat-attachment-remove-${idx}`}
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
                  ×
                </button>
              </div>
            ))}
            <div style={{ marginLeft: 'auto', fontSize: '10px', color: 'var(--fg-muted)', alignSelf: 'center' }}>
              Paste a screenshot or attach (max {maxImages})
            </div>
          </div>
        )}

        <textarea
          id="chat-input"
          ref={textareaRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Ask a question about your codebase... (paste screenshot to attach)"
          disabled={sending || Boolean(blockedReason)}
          style={{
            flex: 1,
            background: 'var(--input-bg)',
            border: '1px solid var(--line)',
            color: 'var(--fg)',
            padding: '12px',
            borderRadius: '6px',
            fontSize: '14px',
            fontFamily: 'inherit',
            resize: 'none',
            minHeight: '60px',
            maxHeight: '120px',
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
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={sending || Boolean(blockedReason) || !visionEnabled || attachments.length >= maxImages}
          data-testid="chat-attach-button"
          style={{
            background:
              sending || Boolean(blockedReason) || !visionEnabled || attachments.length >= maxImages
                ? 'var(--bg-elev2)'
                : 'var(--bg-elev1)',
            color:
              sending || Boolean(blockedReason) || !visionEnabled || attachments.length >= maxImages
                ? 'var(--fg-muted)'
                : 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '10px 12px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: 700,
            cursor:
              sending || Boolean(blockedReason) || !visionEnabled || attachments.length >= maxImages
                ? 'not-allowed'
                : 'pointer',
          }}
          aria-label="Attach image"
          title={!visionEnabled ? 'Vision disabled' : attachments.length >= maxImages ? `Max ${maxImages} images` : 'Attach an image'}
        >
          📎
        </button>
        <button
          id="chat-send"
          onClick={handleSend}
          disabled={!canSend}
          style={{
            background: canSend ? 'var(--accent)' : 'var(--bg-elev2)',
            color: canSend ? 'var(--accent-contrast)' : 'var(--fg-muted)',
            border: 'none',
            padding: '12px 24px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '600',
            cursor: canSend ? 'pointer' : 'not-allowed',
            height: 'fit-content',
          }}
          aria-label="Send message"
        >
          {sending ? 'Sending...' : 'Send'}
        </button>
      </div>
      {blockedReason && (
        <div style={{ fontSize: '11px', color: 'var(--warn)' }}>
          {blockedReason}
        </div>
      )}
    </div>
  );
});

type AssistantMarkdownProps = {
  content: string;
};

const AssistantMarkdown = memo(function AssistantMarkdown({ content }: AssistantMarkdownProps) {
  return (
    <div
      className="chat-markdown"
      style={{
        fontSize: '13px',
        lineHeight: '1.7',
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ node, inline, className, children, ...props }: any) {
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
                    onClick={() => navigator.clipboard.writeText(codeString)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#888',
                      cursor: 'pointer',
                      fontSize: '10px',
                    }}
                  >
                    📋 Copy
                  </button>
                </div>
                <SyntaxHighlighter
                  style={oneDark}
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
          h1({ children }) {
            return (
              <h1 style={{ fontSize: '18px', fontWeight: 600, margin: '16px 0 8px 0', color: 'var(--accent)' }}>
                {children}
              </h1>
            );
          },
          h2({ children }) {
            return (
              <h2 style={{ fontSize: '16px', fontWeight: 600, margin: '14px 0 6px 0', color: 'var(--accent)' }}>
                {children}
              </h2>
            );
          },
          h3({ children }) {
            return <h3 style={{ fontSize: '14px', fontWeight: 600, margin: '12px 0 4px 0' }}>{children}</h3>;
          },
          strong({ children }) {
            return <strong style={{ fontWeight: 600, color: 'var(--fg)' }}>{children}</strong>;
          },
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: 'var(--link)', textDecoration: 'underline' }}
              >
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
          table({ children }) {
            return (
              <div style={{ overflowX: 'auto', margin: '12px 0' }}>
                <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '12px' }}>{children}</table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th
                style={{
                  border: '1px solid var(--line)',
                  padding: '8px',
                  background: 'var(--bg-elev2)',
                  textAlign: 'left',
                }}
              >
                {children}
              </th>
            );
          },
          td({ children }) {
            return <td style={{ border: '1px solid var(--line)', padding: '8px' }}>{children}</td>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});

export function ChatInterface({ traceOpen, onTraceUpdate }: ChatInterfaceProps) {
  const { api } = useAPI();
  const { showToast } = useUIHelpers();
  const { status: embeddingStatus, loading: embeddingStatusLoading, error: embeddingStatusError } = useEmbeddingStatus();
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [typing, setTyping] = useState(false);
  const [conversationId, setConversationId] = useState<string>(() => createConversationId());
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const sessionsLoadedRef = useRef(false);
  
  // Use centralized repo store for repo list and default
  const { repos, loadRepos, initialized, activeRepo, deleteUnindexedCorpora } = useRepoStore();
  
  // Chat UI preferences (TriBridConfig-backed)
  const { config } = useConfig();
  const chatStreamingEnabled = Boolean(config?.ui?.chat_streaming_enabled ?? 1);
  const chatShowConfidence = Boolean(config?.ui?.chat_show_confidence ?? 0);
  const chatShowCitations = Boolean(config?.ui?.chat_show_citations ?? 1);
  const chatShowTrace = Boolean(config?.ui?.chat_show_trace ?? 1);
  const chatShowDebugFooter = Boolean(config?.ui?.chat_show_debug_footer ?? 1);
  const recallGateShowDecision = Boolean(config?.chat?.recall_gate?.show_gate_decision ?? true);
  const recallGateShowSignals = Boolean(config?.chat?.recall_gate?.show_signals ?? false);
  const chatHistoryMax = Math.max(10, Math.min(500, Number(config?.ui?.chat_history_max ?? 50)));
  const multimodalCfg = (config?.chat?.multimodal ?? null) as ChatMultimodalConfig | null;
  const configuredChatTimeoutSeconds = Number(config?.ui?.chat_stream_timeout ?? 120);
  const chatRequestTimeoutMs = Number.isFinite(configuredChatTimeoutSeconds)
    ? Math.max(5, Math.min(600, configuredChatTimeoutSeconds)) * 1000
    : DEFAULT_CHAT_REQUEST_TIMEOUT_MS;

  // Per-message retrieval leg toggles (do NOT persist; user requested per-message control)
  const [includeVector, setIncludeVector] = useState(true);
  const [includeSparse, setIncludeSparse] = useState(true);
  const [includeGraph, setIncludeGraph] = useState(false);
  // Note: include_vector/sparse/graph are per-message settings on ChatRequest,
  // not config settings. They default to true in the Pydantic model.
  const [recallIntensity, setRecallIntensity] = useState<RecallIntensity | null>(null);

  const maybeToastRerankOutcome = useCallback(
    (rerank: RerankDebugInfo | null | undefined) => {
      if (!rerank || !rerank.enabled) return;

      const mode = String(rerank.mode || 'rerank').trim() || 'rerank';
      const skipped = String(rerank.skipped_reason || '').trim();
      const errMsg = String(rerank.error_message || '').trim();
      const errRaw = String(rerank.error || '').trim();
      const traceId = String(rerank.debug_trace_id || '').trim();

      if (rerank.ok === false) {
        const msg = errMsg || errRaw || 'Unknown error';
        showToast(`Rerank failed (${mode}): ${msg}${traceId ? ` (trace ${traceId})` : ''}`, 'error');
        return;
      }

      if (!rerank.applied && skipped) {
        const skipKey = skipped.toLowerCase();
        // These are expected "non-errors" and shouldn't spam the user.
        if (skipKey === 'no_candidates' || skipKey === 'empty_query') return;

        showToast(`Rerank skipped (${mode}): ${skipped}`, 'info');
      }
    },
    [showToast]
  );

  // Chat 2.0: composable sources + model picker
  const sourcesInitRef = useRef(false);
  const activeSourcesRef = useRef<ActiveSources>(defaultChatSources());
  const [activeSources, setActiveSources] = useState<ActiveSources>(defaultChatSources());
  const handleSourcesChange = useCallback(
    (next: ActiveSources) => {
      activeSourcesRef.current = next;
      setActiveSources(next);
      const ids = next.corpus_ids ?? [];
      if (!ids.includes('recall_default')) {
        setRecallIntensity(null);
      }
    },
    [setActiveSources]
  );
  const handleCleanupUnindexed = useCallback(async () => {
    try {
      const deleted = await deleteUnindexedCorpora();
      if (!deleted.length) return;
      const ids = (activeSources?.corpus_ids ?? []).filter((id) => !deleted.includes(String(id)));
      handleSourcesChange({ ...activeSources, corpus_ids: ids });
    } catch (e) {
      console.error('[ChatInterface] Failed to delete unindexed corpora:', e);
    }
  }, [activeSources, deleteUnindexedCorpora, handleSourcesChange]);
  const retrievalSelected = (activeSources?.corpus_ids ?? []).length > 0;
  const chatBlockedReason =
    embeddingStatusError
      ? `Retrieval compatibility check failed: ${embeddingStatusError}`
      : !embeddingStatusLoading
        && retrievalSelected
        && Boolean(embeddingStatus?.hasIndex)
        && Boolean(embeddingStatus?.isMismatched)
        && (includeVector || includeSparse)
        ? 'Retrieval/index contract mismatch detected. Re-index or restore indexing config before sending.'
        : null;

  // Prune selected sources when corpora are deleted/changed.
  useEffect(() => {
    const allowed = new Set<string>(repos.map((r) => String(r.corpus_id)));
    allowed.add('recall_default');
    const current = (activeSources?.corpus_ids ?? []).map(String);
    const next = current.filter((id) => allowed.has(id));
    if (next.length === current.length) return;
    handleSourcesChange({ ...activeSources, corpus_ids: next });
  }, [activeSources, handleSourcesChange, repos]);
  useEffect(() => {
    if (sourcesInitRef.current) return;
    if (!config) return;
    sourcesInitRef.current = true;
    const defaults = config.chat?.default_corpus_ids ?? ['recall_default'];
    handleSourcesChange({ corpus_ids: defaults });
  }, [config, handleSourcesChange]);

  const [chatModels, setChatModels] = useState<ChatModelInfo[]>([]);
  const [modelOverride, setModelOverride] = useState<string>('');
  useEffect(() => {
    if (!config) return;
    if (!chatModels.length) {
      if (modelOverride) setModelOverride('');
      return;
    }
    // Pick a sensible default model_override based on what's actually available.
    //
    // Important: This should prefer OpenRouter only when it's enabled, and prefer local only
    // when local models are actually discoverable. Otherwise, fall back to a configured
    // cloud default (ui.chat_default_model) when present in the model list.
    const openrouterEnabled = Boolean(config.chat?.openrouter?.enabled);
    const openrouterDefault = config.chat?.openrouter?.default_model;
    const localDefault = config.chat?.local_models?.default_chat_model;
    const openrouterDefaultTrimmed = typeof openrouterDefault === 'string' ? openrouterDefault.trim() : '';

    const toOverrideValue = (m: ChatModelInfo): string => {
      return String(m.override || m.id || '').trim();
    };

    // If current selection is valid, don't override it.
    const optionValues = chatModels.map(toOverrideValue);
    if (modelOverride && optionValues.includes(modelOverride)) {
      return;
    }

    const localModels = chatModels.filter((m) => m.source === 'local');
    const localDefaultTrimmed = typeof localDefault === 'string' ? localDefault.trim() : '';
    const localDefaultOption =
      localDefaultTrimmed
        ? localModels.find(
            (m) =>
              String(m.id || '').trim() === localDefaultTrimmed ||
              String(m.catalog_model || '').trim() === localDefaultTrimmed
          )
        : undefined;

    const openrouterDefaultOption =
      openrouterEnabled && openrouterDefaultTrimmed
        ? chatModels.find(
            (m) =>
              m.source === 'openrouter' &&
              (String(m.id || '').trim() === openrouterDefaultTrimmed ||
                String(m.catalog_model || '').trim() === openrouterDefaultTrimmed)
          )
        : undefined;

    const uiDefault = typeof config.ui?.chat_default_model === 'string' ? config.ui.chat_default_model.trim() : '';
    const cloudDefaultOption = uiDefault
      ? chatModels.find((m) => {
          const id = String(m.id || '').trim();
          const catalogModel = String(m.catalog_model || '').trim();
          const override = String(m.override || '').trim();
          return (
            id === uiDefault ||
            catalogModel === uiDefault ||
            override === uiDefault ||
            id.endsWith(`/${uiDefault}`) ||
            override.endsWith(`/${uiDefault}`)
          );
        })
      : undefined;

    const preferred =
      (openrouterDefaultOption ? toOverrideValue(openrouterDefaultOption) : '') ||
      (localModels.length ? (localDefaultOption ? toOverrideValue(localDefaultOption) : toOverrideValue(localModels[0])) : '') ||
      (cloudDefaultOption ? toOverrideValue(cloudDefaultOption) : '');

    const nextOverride = preferred
      ? String(preferred)
      : (() => {
          const first = chatModels[0];
          return toOverrideValue(first);
        })();

    setModelOverride(nextOverride);
  }, [chatModels, config, modelOverride]);

  const [lastMatches, setLastMatches] = useState<ChunkMatch[]>([]);
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);
  const [lastRecallPlan, setLastRecallPlan] = useState<RecallPlan | null>(null);

  // Quick settings (also editable in Chat Settings subtab)
  const [temperature, setTemperature] = useConfigField<number>('chat.temperature', 0.3);
  const [maxTokens, setMaxTokens] = useConfigField<number>('chat.max_tokens', 4096);
  const [topK, setTopK] = useConfigField<number>('retrieval.final_k', 10);

  const [tracePreference, setTracePreference] = useState<boolean>(() => {
    if (traceOpen !== undefined) return Boolean(traceOpen);
    return chatShowTrace;
  });
  // Trace is maintained via ref + parent callback (no local render use)
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const typingStartedAtRef = useRef<number | null>(null);
  const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamingSupportedRef = useRef<boolean | null>(null);
  const requestAbortControllerRef = useRef<AbortController | null>(null);
  const activeRequestTokenRef = useRef(0);
  
  // Tip rotation state for streaming indicator
  const [currentTip, setCurrentTip] = useState<typeof TRIBRID_TIPS[0] | null>(null);
  const [tipFade, setTipFade] = useState(true);
  const shuffledTipsRef = useRef<typeof TRIBRID_TIPS>([]);
  const tipIndexRef = useRef(0);
  
  // Feedback state: track which messages have received feedback
  const [messageFeedback, setMessageFeedback] = useState<Record<string, { type: string; rating?: number }>>({});
  
  // Send feedback to API
  const sendFeedback = async (eventId: string | undefined, messageId: string, signal: string) => {
    const normalizedSignal = String(signal || '').trim();
    const rating = normalizedSignal.startsWith('star') ? parseInt(normalizedSignal.slice(4), 10) : null;
    
    try {
      const body: any = {
        context: 'chat',
        timestamp: new Date().toISOString(),
      };
      if (eventId) {
        body.event_id = eventId;
        body.signal = normalizedSignal;
      } else if (rating && rating >= 1 && rating <= 5) {
        // When we don't have a run_id (e.g., the assistant response errored), still allow UI meta-rating
        // without mixing shapes (backend forbids rating + event_id/signal).
        body.rating = rating;
      } else {
        showToast('Feedback not available yet (missing run_id).', 'error');
        return;
      }

      const response = await fetch(api(withCorpusScope('feedback')), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      
      if (response.ok) {
        setMessageFeedback(prev => ({
          ...prev,
          [messageId]: { type: signal, rating: rating && rating >= 1 && rating <= 5 ? rating : undefined }
        }));
        showToast('Feedback recorded.', 'success');
      } else {
        let detail = '';
        try {
          const ct = response.headers.get('content-type') || '';
          if (ct.includes('application/json')) {
            const j: any = await response.json();
            detail = typeof j?.detail === 'string' ? j.detail : JSON.stringify(j).slice(0, 200);
          } else {
            detail = (await response.text()).slice(0, 200);
          }
        } catch {
          detail = '';
        }
        showToast(detail ? `Feedback failed: ${detail}` : 'Feedback failed.', 'error');
      }
    } catch (error) {
      console.error('[ChatInterface] Feedback error:', error);
      showToast('Feedback failed (network error).', 'error');
    }
  };
  
  // Rotate tips during streaming/typing
  useEffect(() => {
    if (!streaming && !typing) {
      setCurrentTip(null);
      return;
    }
    
    // Shuffle tips on first activation
    if (shuffledTipsRef.current.length === 0) {
      shuffledTipsRef.current = shuffleArray(TRIBRID_TIPS);
      tipIndexRef.current = 0;
    }
    
    // Show first tip immediately
    const showNextTip = () => {
      setTipFade(false);
      setTimeout(() => {
        const tip = shuffledTipsRef.current[tipIndexRef.current];
        setCurrentTip(tip);
        tipIndexRef.current = (tipIndexRef.current + 1) % shuffledTipsRef.current.length;
        // Re-shuffle when we've shown all tips
        if (tipIndexRef.current === 0) {
          shuffledTipsRef.current = shuffleArray(TRIBRID_TIPS);
        }
        setTipFade(true);
      }, 150);
    };
    
    showNextTip();
    
    // Set up interval for tip rotation
    const getNextInterval = () => {
      const tip = shuffledTipsRef.current[tipIndexRef.current];
      return getTipDuration(tip?.tip || '');
    };
    
    let timeoutId: ReturnType<typeof setTimeout>;
    const scheduleNext = () => {
      timeoutId = setTimeout(() => {
        showNextTip();
        scheduleNext();
      }, getNextInterval());
    };
    scheduleNext();
    
    return () => {
      clearTimeout(timeoutId);
    };
  }, [streaming, typing]);

  // Load chat model options (Chat 2.0)
  useEffect(() => {
    (async () => {
      try {
        const qs = activeRepo ? `?corpus_id=${encodeURIComponent(activeRepo)}` : '';
        const r = await fetch(api(`chat/models${qs}`));
        if (!r.ok) {
          setChatModels([]);
          return;
        }
        const d = (await r.json()) as ChatModelsResponse;
        const models = Array.isArray(d?.models) ? (d.models as ChatModelInfo[]) : [];
        setChatModels(models);
      } catch {
        // Best-effort; show explicit degraded state instead of masking provider readiness.
        setChatModels([]);
      }
    })();
  }, [
    api,
    activeRepo,
    Boolean(config?.chat?.openrouter?.enabled),
    Array.isArray(config?.chat?.local_models?.providers)
      ? config!.chat!.local_models!.providers!.map((p) => `${p.enabled !== false}:${p.base_url}`).join('|')
      : '',
  ]);

  // Chat settings state (TriBridConfig-backed)
  const [streamPref, setStreamPref] = useState<boolean>(() => chatStreamingEnabled);
  const [showConfidence, setShowConfidence] = useState<boolean>(() => chatShowConfidence);
  const [showCitations, setShowCitations] = useState<boolean>(() => chatShowCitations);
  const [showDebugFooter, setShowDebugFooter] = useState<boolean>(() => chatShowDebugFooter);
  const traceRef = useRef<TraceStep[]>([]);
  const [fastMode, setFastMode] = useState<boolean>(() => {
    const params = new URLSearchParams(window.location.search || '');
    return params.get('fast') === '1' || params.get('smoke') === '1';
  });

  // Sync local UI toggles when config changes
  useEffect(() => {
    setStreamPref(chatStreamingEnabled);
  }, [chatStreamingEnabled]);

  useEffect(() => {
    setShowConfidence(chatShowConfidence);
  }, [chatShowConfidence]);

  useEffect(() => {
    setShowCitations(chatShowCitations);
  }, [chatShowCitations]);

  useEffect(() => {
    setShowDebugFooter(chatShowDebugFooter);
  }, [chatShowDebugFooter]);

  useEffect(() => {
    if (traceOpen === undefined) {
      setTracePreference(chatShowTrace);
    }
  }, [chatShowTrace, traceOpen]);

  // Define notifyTrace before useEffects that use it
  const notifyTrace = useCallback((steps: TraceStep[], open: boolean, source: 'config' | 'response' | 'clear' = 'response') => {
    traceRef.current = steps;
    const effectiveOpen = source === 'response' ? (open && tracePreference) : open;
    onTraceUpdate?.(steps, effectiveOpen, source);
  }, [onTraceUpdate, tracePreference]);

  const isRequestTokenActive = useCallback((token: number) => {
    return activeRequestTokenRef.current === token;
  }, []);

  const resetTransientChatState = useCallback((reason: string = 'aborted') => {
    const controller = requestAbortControllerRef.current;
    if (controller) {
      try {
        controller.abort(reason);
      } catch {
        // Ignore abort races.
      }
    }
    requestAbortControllerRef.current = null;
    activeRequestTokenRef.current += 1;
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
      typingTimeoutRef.current = null;
    }
    typingStartedAtRef.current = null;
    setSending(false);
    setStreaming(false);
    setTyping(false);
  }, []);

  const persistSessions = useCallback((sessions: ChatSession[], activeId: string) => {
    try {
      persistChatSessionsToStorage(localStorage, sessions, activeId);
    } catch (error) {
      console.error('[ChatInterface] Failed to persist chat sessions:', error);
    }
  }, []);

  const activateSession = useCallback(
    (session: ChatSession) => {
      resetTransientChatState('session_change');
      const id = String(session?.conversation_id || '').trim() || createConversationId();
      setConversationId(id);
      setMessages(clampChatHistory(Array.isArray(session?.messages) ? session.messages : [], chatHistoryMax));
      setModelOverride(String(session?.model_override || '').trim());
      const sessionSources = (session?.sources || defaultChatSources()) as ActiveSources;
      activeSourcesRef.current = sessionSources;
      setActiveSources(sessionSources);
      setLastMatches([]);
      setLastLatencyMs(null);
      setLastRecallPlan(null);
      notifyTrace([], false, 'clear');
      // Prevent config defaults from clobbering per-session selection.
      sourcesInitRef.current = true;
    },
    [chatHistoryMax, notifyTrace, resetTransientChatState]
  );

  const chatHistoryInitRef = useRef(false);

  // Load repositories via store (once on mount if not initialized)
  useEffect(() => {
    if (!initialized) {
      loadRepos();
    }
  }, [initialized, loadRepos]);

  // Load chat sessions from localStorage (once).
  useEffect(() => {
    if (chatHistoryInitRef.current) return;
    chatHistoryInitRef.current = true;
    loadChatHistory();
  }, []);

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
      if (typingTimeoutRef.current) {
        clearTimeout(typingTimeoutRef.current);
        typingTimeoutRef.current = null;
      }
    };
  }, []);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: streaming ? 'auto' : 'smooth' });
  }, [messages.length, streaming]);

  const loadChatHistory = () => {
    try {
      const { sessions, activeSession, removeLegacyHistory } = loadChatSessionsFromStorage(localStorage, chatHistoryMax);
      setChatSessions(sessions);
      sessionsLoadedRef.current = true;
      persistSessions(sessions, String(activeSession.conversation_id || '').trim());
      activateSession(activeSession);

      try {
        if (removeLegacyHistory) {
          localStorage.removeItem(LEGACY_CHAT_HISTORY_STORAGE_KEY);
        }
      } catch {}
    } catch (error) {
      console.error('[ChatInterface] Failed to load chat history:', error);
    }
  };

  const saveChatHistory = (msgs: Message[]) => {
    try {
      const now = Date.now();
      const activeId = String(conversationId || '').trim() || createConversationId();

      setChatSessions((prev) => {
        const next = upsertChatSession({
          sessions: prev,
          activeId,
          messages: msgs,
          modelOverride,
          sources: activeSources || defaultChatSources(),
          now,
          chatHistoryMax,
        });
        persistSessions(next, activeId);
        sessionsLoadedRef.current = true;
        return next;
      });
    } catch (error) {
      console.error('[ChatInterface] Failed to save chat history:', error);
    }
  };

  // Persist model selection immediately (prevents reverting after a turn).
  useEffect(() => {
    if (!sessionsLoadedRef.current) return;
    const activeId = String(conversationId || '').trim();
    if (!activeId) return;
    const nextModel = String(modelOverride || '').trim();
    if (!nextModel) return;

    setChatSessions((prev) => {
      let next = Array.isArray(prev) ? prev.slice() : [];
      const idx = next.findIndex((s) => String(s.conversation_id || '').trim() === activeId);
      if (idx === -1) return prev;
      const cur = next[idx];
      if (String(cur.model_override || '').trim() === nextModel) return prev;
      next[idx] = { ...cur, model_override: nextModel, updated_at: Date.now() };
      persistSessions(next, activeId);
      return next;
    });
  }, [conversationId, modelOverride, persistSessions]);

  // Persist source/recall selection immediately (prevents drift on tab/session churn).
  useEffect(() => {
    if (!sessionsLoadedRef.current) return;
    const activeId = String(conversationId || '').trim();
    if (!activeId) return;

    setChatSessions((prev) => {
      const next = Array.isArray(prev) ? prev.slice() : [];
      const idx = next.findIndex((s) => String(s.conversation_id || '').trim() === activeId);
      if (idx === -1) return prev;
      const cur = next[idx];
      const curSig = JSON.stringify(cur.sources || defaultChatSources());
      const nextSig = JSON.stringify(activeSources || defaultChatSources());
      if (curSig === nextSig) return prev;
      next[idx] = { ...cur, sources: (activeSources || defaultChatSources()) as ActiveSources, updated_at: Date.now() };
      persistSessions(next, activeId);
      return next;
    });
  }, [activeSources, conversationId, persistSessions]);

  const startThinking = () => {
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
      typingTimeoutRef.current = null;
    }
    typingStartedAtRef.current = Date.now();
    setTyping(true);
  };

  const stopThinking = (requestToken: number) => {
    if (!isRequestTokenActive(requestToken)) return;
    const elapsed = typingStartedAtRef.current ? Date.now() - typingStartedAtRef.current : 0;
    const remaining = Math.max(0, 750 - elapsed);
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
      typingTimeoutRef.current = null;
    }
    typingTimeoutRef.current = setTimeout(() => {
      if (!isRequestTokenActive(requestToken)) return;
      typingTimeoutRef.current = null;
      setTyping(false);
    }, remaining);
  };

  const handleSend = async (text: string, images: ImageAttachment[]) => {
    if (!text.trim() || sending) return;
    if (chatBlockedReason) {
      showToast(chatBlockedReason, 'error');
      return;
    }
    const recallIntensityOverride = recallIntensity;
    if (recallIntensityOverride !== null) {
      setRecallIntensity(null);
    }

    resetTransientChatState('superseded');
    const requestToken = activeRequestTokenRef.current + 1;
    activeRequestTokenRef.current = requestToken;
    const requestSources = (activeSourcesRef.current || activeSources || defaultChatSources()) as ActiveSources;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text.trim(),
      images: Array.isArray(images) && images.length ? images : undefined,
      timestamp: Date.now(),
    };

    const newMessages = clampChatHistory([...messages, userMessage], chatHistoryMax);
    setMessages(newMessages);
    saveChatHistory(newMessages);
    setSending(true);
    notifyTrace([], false, 'clear');
    startThinking();

    const abortController = new AbortController();
    requestAbortControllerRef.current = abortController;
    const timeoutId = setTimeout(() => {
      try {
        abortController.abort(CHAT_REQUEST_ABORT_TIMEOUT);
      } catch {
        // Ignore abort races.
      }
    }, chatRequestTimeoutMs);

    try {
      await sendChatTransport(
        {
          api,
          conversationId,
          modelOverride,
          includeVector,
          includeSparse,
          includeGraph,
          fastMode,
          chatHistoryMax,
          messagesContainerRef,
          messagesEndRef,
          isRequestTokenActive,
          setStreaming,
          setConversationId,
          setMessages,
          setLastMatches,
          setLastLatencyMs,
          setLastRecallPlan,
          maybeToastRerankOutcome,
          showToast,
          saveChatHistory,
        },
        {
          userMessage,
          recallIntensityOverride,
          requestToken,
          signal: abortController.signal,
          requestSources,
          streamPreferred: streamPref && streamingSupportedRef.current !== false,
          markStreamingSupported: () => {
            if (isRequestTokenActive(requestToken)) {
              streamingSupportedRef.current = true;
            }
          },
          markStreamingUnsupported: () => {
            streamingSupportedRef.current = false;
          },
        }
      );
    } catch (error) {
      const abortReason = toAbortReason(error, abortController.signal);
      if (abortReason) {
        if (abortReason === CHAT_REQUEST_ABORT_TIMEOUT && isRequestTokenActive(requestToken)) {
          showToast('Chat timed out before completion.', 'error');
        }
        return;
      }
      if (!isRequestTokenActive(requestToken)) return;
      console.error('[ChatInterface] Failed to send message:', error);
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `Error: ${error instanceof Error ? error.message : 'Failed to get response'}`,
        timestamp: Date.now(),
      };
      const updatedMessages = clampChatHistory([...newMessages, errorMessage], chatHistoryMax);
      setMessages(updatedMessages);
      saveChatHistory(updatedMessages);
    } finally {
      clearTimeout(timeoutId);
      if (requestAbortControllerRef.current === abortController) {
        requestAbortControllerRef.current = null;
      }
      if (!isRequestTokenActive(requestToken)) return;
      setSending(false);
      setStreaming(false);
      stopThinking(requestToken);
    }
  };

  const handleNewChat = useCallback(() => {
    const session = createChatSession({
      title: 'New chat',
      messages: [],
      modelOverride,
      sources: activeSources || defaultChatSources(),
      chatHistoryMax,
    });
    const id = String(session.conversation_id || '').trim();

    setChatSessions((prev) => {
      let next = Array.isArray(prev) ? prev.slice() : [];
      next = [session, ...next];
      next.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
      if (next.length > 50) next = next.slice(0, 50);
      persistSessions(next, id);
      return next;
    });
    sessionsLoadedRef.current = true;
    activateSession(session);
  }, [activeSources, activateSession, chatHistoryMax, modelOverride, persistSessions]);

  const handleClear = useCallback(() => {
    const activeId = String(conversationId || '').trim();
    const activeTitle =
      chatSessions.find((s) => String(s.conversation_id || '').trim() === activeId)?.title || 'this chat';

    if (!confirm(`Delete "${activeTitle}"?\n\nThis removes it from UI history. Recall memory is not deleted.`)) {
      return;
    }

    let remaining = chatSessions.filter((s) => String(s.conversation_id || '').trim() !== activeId);
    remaining.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));

    if (remaining.length === 0) {
      // Always keep at least one empty chat.
      remaining = [
        createChatSession({
          title: 'New chat',
          messages: [],
          modelOverride,
          sources: activeSources || defaultChatSources(),
          chatHistoryMax,
        }),
      ];
    }

    const nextActive = remaining[0];
    setChatSessions(remaining);
    sessionsLoadedRef.current = true;
    persistSessions(remaining, String(nextActive.conversation_id || '').trim());
    activateSession(nextActive);
  }, [activeSources, activateSession, chatHistoryMax, chatSessions, conversationId, modelOverride, persistSessions]);

  const handleExport = () => {
    const exportData = {
      exported: new Date().toISOString(),
      messages: messages.map(m => ({
        role: m.role,
        content: m.content,
        timestamp: new Date(m.timestamp).toISOString()
      }))
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-export-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopy = (content: string) => {
    navigator.clipboard.writeText(content);
    // Could add a toast notification here
  };

  const handleViewTraceAndLogs = useCallback((message: Message) => {
    const run_id = (message.runId || '').trim();
    // Dispatch an event so the parent ChatTab can load the right run context.
    window.dispatchEvent(
      new CustomEvent('tribrid:chat:open-trace', {
        detail: {
          run_id: run_id || undefined,
          started_at_ms: message.startedAtMs,
          ended_at_ms: message.endedAtMs,
        },
      })
    );

    const el = document.getElementById('chat-trace') as HTMLDetailsElement | null;
    if (el) {
      el.open = true;
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, []);

  const handleSelectSession = useCallback(
    (session: ChatSession) => {
      const id = String(session.conversation_id || '').trim();
      const nextActive = id || createConversationId();
      persistSessions(chatSessions, nextActive);
      activateSession(session);
    },
    [activateSession, chatSessions, persistSessions]
  );

  return (
    <div
      data-react-chat="true"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '70vh',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        overflow: 'hidden',
        background: 'var(--card-bg)'
      }}
    >
      {/* Header - responsive flex layout with wrap */}
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid var(--line)',
        display: 'flex',
        flexWrap: 'wrap',
        gap: '12px',
        alignItems: 'center',
        background: 'var(--bg-elev1)'
      }}>
        <div style={{ flexShrink: 0 }}>
          <h3 style={{ margin: '0 0 2px 0', fontSize: '14px', fontWeight: '600', whiteSpace: 'nowrap' }}>
            <span style={{ color: 'var(--accent)' }}>●</span> RAG Chat
          </h3>
          <p style={{
            margin: '0',
            fontSize: '11px',
            color: 'var(--fg-muted)',
            whiteSpace: 'nowrap'
          }}>
            Ask questions about your codebase
          </p>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', flex: '1 1 auto', minWidth: 0 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            <input id="chat-fast-mode" type="checkbox" checked={fastMode} onChange={(e) => setFastMode(e.target.checked)} style={{ width: '14px', height: '14px', cursor: 'pointer' }} />
            Fast
          </label>
          <SourceDropdown
            value={activeSources}
            onChange={handleSourcesChange}
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
          />
          <div style={{ flex: '1 1 200px', minWidth: '180px', maxWidth: '360px' }}>
            <ModelPicker value={modelOverride} onChange={setModelOverride} models={chatModels} />
          </div>

          <button
            onClick={handleExport}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--accent)',
              border: '1px solid var(--accent)',
              padding: '6px 12px',
              borderRadius: '4px',
              fontSize: '12px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
            aria-label="Export conversation"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export
          </button>

          <button
            onClick={() => setShowHistory(!showHistory)}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              border: '1px solid var(--line)',
              padding: '6px 12px',
              borderRadius: '4px',
              fontSize: '12px',
              cursor: 'pointer'
            }}
            aria-label="Toggle history"
          >
            🕘
          </button>

          <button
            data-testid="chat-new-chat"
            onClick={handleNewChat}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--accent)',
              border: '1px solid var(--accent)',
              padding: '6px 12px',
              borderRadius: '4px',
              fontSize: '12px',
              cursor: 'pointer'
            }}
            aria-label="New chat"
            title="Start a new chat (new conversation_id)"
          >
            New chat
          </button>

          <button
            onClick={handleClear}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--err)',
              border: '1px solid var(--err)',
              padding: '6px 12px',
              borderRadius: '4px',
              fontSize: '12px',
              cursor: 'pointer'
            }}
            aria-label="Delete chat"
          >
            Delete
          </button>

          <button
            onClick={() => setShowSettings(!showSettings)}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              border: '1px solid var(--line)',
              padding: '6px 12px',
              borderRadius: '4px',
              fontSize: '12px',
              cursor: 'pointer'
            }}
            aria-label="Toggle settings"
          >
            ⚙️
          </button>
        </div>
      </div>

      {/* Embedding Mismatch Warning - Critical for chat results */}
      <EmbeddingMismatchWarning variant="inline" showActions={true} />
      
      {/* No Index Warning - Show when user hasn't indexed yet */}
      {(() => {
        const selected = (activeSources?.corpus_ids ?? []).filter((id) => id && id !== 'recall_default');
        const selectedCorpora = selected
          .map((id) => repos.find((r) => r.corpus_id === id))
          .filter(Boolean) as Array<(typeof repos)[number]>;
        const unindexed = selectedCorpora.filter((c) => !c.last_indexed);
        if (unindexed.length === 0) return null;
        const names = unindexed.map((c) => c.name || c.corpus_id).join(', ');
        return (
        <div
          role="alert"
          style={{
            background: 'linear-gradient(135deg, rgba(255, 170, 0, 0.1) 0%, rgba(255, 170, 0, 0.05) 100%)',
            border: '1px solid var(--warn)',
            borderRadius: '8px',
            padding: '12px 16px',
            marginBottom: '0',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
            <span style={{ fontSize: '20px', flexShrink: 0 }}>📑</span>
            <div style={{ flex: 1 }}>
              <div style={{ 
                fontWeight: 600, 
                color: 'var(--warn)', 
                fontSize: '13px',
                marginBottom: '4px',
              }}>
                Not indexed yet
              </div>
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                Selected corpora are not indexed ({names}). Chat can’t retrieve anything until you index them.
                {' '}
                Go to <a 
                  href="/web/rag?subtab=indexing"
                  style={{ color: 'var(--link)', textDecoration: 'underline' }}
                >
                  RAG → Indexing
                </a> and click "INDEX NOW" to get started.
              </div>
            </div>
          </div>
        </div>
        );
      })()}

      {/* Main content area with messages and optional sidebars */}
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
        {/* Messages area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Messages */}
          <div id="chat-messages" ref={messagesContainerRef} style={{
            flex: 1,
            overflowY: 'auto',
            padding: '16px'
          }}>
            <ChatMessageThread
              messages={messages}
              showConfidence={showConfidence}
              showCitations={showCitations}
              showDebugFooter={showDebugFooter}
              showRecallGateSignals={recallGateShowSignals}
              messageFeedback={messageFeedback}
              onCopy={handleCopy}
              onSendFeedback={(message, signal) => {
                sendFeedback(message.eventId ?? message.runId, message.id, signal);
              }}
              onViewTraceAndLogs={handleViewTraceAndLogs}
              renderAssistantContent={(content) => <AssistantMarkdown content={content} />}
            />

            {streaming && (
              <div style={{
                background: 'linear-gradient(135deg, var(--bg-elev1) 0%, var(--bg-elev2) 100%)',
                border: '1px solid var(--line)',
                borderRadius: '12px',
                padding: '16px 20px',
                marginBottom: '12px',
                boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
              }}>
                {/* Status indicator */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  marginBottom: currentTip ? '12px' : '0'
                }}>
                  <div style={{
                    width: '10px',
                    height: '10px',
                    borderRadius: '50%',
                    background: 'var(--accent)',
                    animation: 'pulse 1.5s ease-in-out infinite',
                    boxShadow: '0 0 8px var(--accent)'
                  }} />
                  <span style={{
                    fontSize: '13px',
                    fontWeight: 600,
                    color: 'var(--fg)',
                    letterSpacing: '0.3px'
                  }}>
                    Generating response...
                  </span>
                </div>
                
                {/* Tip display */}
                {currentTip && (
                  <div style={{
                    opacity: tipFade ? 1 : 0,
                    transition: 'opacity 0.15s ease-in-out',
                    borderTop: '1px solid var(--line)',
                    paddingTop: '12px',
                    marginTop: '4px'
                  }}>
                    <div style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '10px'
                    }}>
                      <span style={{
                        fontSize: '16px',
                        lineHeight: '1.4'
                      }}>
                        {CATEGORY_ICONS[currentTip.category] || '💡'}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div style={{
                          fontSize: '10px',
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          letterSpacing: '0.8px',
                          color: CATEGORY_COLORS[currentTip.category] || 'var(--fg-muted)',
                          marginBottom: '4px'
                        }}>
                          {currentTip.category === 'rag' ? 'RAG' : currentTip.category === 'ux' ? 'UX' : currentTip.category}
                        </div>
                        <div style={{
                          fontSize: '12px',
                          lineHeight: '1.5',
                          color: 'var(--fg)'
                        }}>
                          {currentTip.tip}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {!streaming && typing && (
              <div style={{
                background: 'linear-gradient(135deg, var(--bg-elev1) 0%, var(--bg-elev2) 100%)',
                border: '1px solid var(--line)',
                borderRadius: '12px',
                padding: '16px 20px',
                marginBottom: '12px',
                boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
              }} aria-live="polite" aria-label="Assistant is thinking">
                {/* Status indicator */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  marginBottom: currentTip ? '12px' : '0'
                }}>
                  <LoadingSpinner variant="dots" size="md" color="accent" />
                  <span style={{
                    fontSize: '13px',
                    fontWeight: 600,
                    color: 'var(--fg)',
                    letterSpacing: '0.3px'
                  }}>
                    Thinking...
                  </span>
                </div>
                
                {/* Tip display */}
                {currentTip && (
                  <div style={{
                    opacity: tipFade ? 1 : 0,
                    transition: 'opacity 0.15s ease-in-out',
                    borderTop: '1px solid var(--line)',
                    paddingTop: '12px',
                    marginTop: '4px'
                  }}>
                    <div style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '10px'
                    }}>
                      <span style={{
                        fontSize: '16px',
                        lineHeight: '1.4'
                      }}>
                        {CATEGORY_ICONS[currentTip.category] || '💡'}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div style={{
                          fontSize: '10px',
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          letterSpacing: '0.8px',
                          color: CATEGORY_COLORS[currentTip.category] || 'var(--fg-muted)',
                          marginBottom: '4px'
                        }}>
                          {currentTip.category === 'rag' ? 'RAG' : currentTip.category === 'ux' ? 'UX' : currentTip.category}
                        </div>
                        <div style={{
                          fontSize: '12px',
                          lineHeight: '1.5',
                          color: 'var(--fg)'
                        }}>
                          {currentTip.tip}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input area */}
          <div style={{
            padding: '16px',
            borderTop: '1px solid var(--line)',
            background: 'var(--bg-elev1)'
          }}>
            <ChatComposer sending={sending} multimodal={multimodalCfg} blockedReason={chatBlockedReason} onSend={handleSend} />

            <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
              Press Ctrl+Enter to send • Citations appear as clickable file links when enabled in settings
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                flexWrap: 'wrap',
                marginBottom: '0',
              }}
            >
              <span style={{ fontSize: '11px', color: 'var(--fg-muted)', fontWeight: 700 }}>Retrieval legs:</span>
              {[
                { id: 'vector', label: 'Vector', enabled: includeVector, set: setIncludeVector },
                { id: 'sparse', label: 'Sparse', enabled: includeSparse, set: setIncludeSparse },
                { id: 'graph', label: 'Graph', enabled: includeGraph, set: setIncludeGraph },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => t.set(!t.enabled)}
                  aria-pressed={t.enabled}
                  data-testid={`chat-toggle-${t.id}`}
                  style={{
                    padding: '6px 10px',
                    borderRadius: '999px',
                    border: t.enabled ? '1px solid var(--accent)' : '1px solid var(--line)',
                    background: t.enabled ? 'rgba(var(--accent-rgb), 0.12)' : 'var(--bg-elev2)',
                    color: t.enabled ? 'var(--fg)' : 'var(--fg-muted)',
                    fontSize: '11px',
                    fontWeight: 700,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  title={`Include ${t.label} retrieval for this message`}
                >
                  {t.enabled ? '✓ ' : ''}
                  {t.label}
                </button>
              ))}
            </div>

          </div>
        </div>

        {/* Settings sidebar (toggle) */}
        {showSettings && (
          <div style={{
            width: '280px',
            borderLeft: '1px solid var(--line)',
            padding: '16px',
            overflowY: 'auto',
            background: 'var(--bg-elev1)'
          }}>
            <h4 style={{ margin: '0 0 16px 0', fontSize: '13px', fontWeight: '600' }}>
              Quick Settings
            </h4>

            <div style={{ marginBottom: '16px' }}>
              <label style={{
                display: 'block',
                fontSize: '11px',
                fontWeight: '600',
                color: 'var(--fg-muted)',
                marginBottom: '4px'
              }}>
                Temperature: {temperature}
              </label>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                style={{ width: '100%' }}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{
                display: 'block',
                fontSize: '11px',
                fontWeight: '600',
                color: 'var(--fg-muted)',
                marginBottom: '4px'
              }}>
                Max Tokens
              </label>
              <input
                type="number"
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value))}
                min="100"
                max="16384"
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                  fontSize: '12px'
                }}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{
                display: 'block',
                fontSize: '11px',
                fontWeight: '600',
                color: 'var(--fg-muted)',
                marginBottom: '4px'
              }}>
                Top-K (results)
              </label>
              <input
                type="number"
                value={topK}
                onChange={(e) => setTopK(Math.max(1, parseInt(e.target.value) || 10))}
                min="1"
                max="100"
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                  fontSize: '12px'
                }}
              />
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

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
