// TriBridRAG - Chat Interface Component
// Main chat UI with message list, input, streaming, and trace panel
// Reference: /assets/chat tab.png, /assets/chat_built_in.png

import type React from 'react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { useAPI, useConfig, useConfigField } from '@/hooks';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { useRepoStore } from '@/stores/useRepoStore';
import { SourceDropdown } from '@/components/Chat/SourceDropdown';
import { ModelPicker } from '@/components/Chat/ModelPicker';
import { StatusBar } from '@/components/Chat/StatusBar';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { ActiveSources, ChatDebugInfo, ChatModelInfo, ChatModelsResponse, ChunkMatch, RecallIntensity, RecallPlan } from '@/types/generated';

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
  { tip: "The cross-encoder reranker learns from your feedback to improve result ordering over time.", category: "feedback" },
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
  { tip: "Semantic cards summarize files and classes for better high-level understanding.", category: "indexing" },
  { tip: "Index stats show when your codebase was last indexed - check Dashboard for details.", category: "indexing" },
  
  // Evaluation & Quality
  { tip: "Run evals regularly to track retrieval quality as your codebase evolves.", category: "eval" },
  { tip: "Golden questions are your benchmark - add questions that matter to your team.", category: "eval" },
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
  { tip: "Qdrant stores your vectors locally - no data leaves your machine unless you use cloud models.", category: "infra" },
  { tip: "Redis caches embeddings and checkpoints for faster repeated queries.", category: "infra" },
  { tip: "The embedded Grafana dashboard shows real-time metrics and query patterns.", category: "infra" },
  { tip: "Docker containers can be configured for different deployment scenarios.", category: "infra" },
  
  // Best Practices
  { tip: "Ask follow-up questions - Tri-Brid RAG maintains context from your conversation history.", category: "best" },
  { tip: "Be specific about what you're looking for: 'error handling in auth' beats 'auth code'.", category: "best" },
  { tip: "If results seem off, try rephrasing - different words can surface different code.", category: "best" },
  { tip: "Check citations to verify the answer - Tri-Brid RAG shows exactly where information came from.", category: "best" },
  { tip: "Use the repo selector to focus on specific repositories in multi-repo setups.", category: "best" },
  
  // Advanced
  { tip: "Profiles let you save and switch between different Tri-Brid RAG configurations instantly.", category: "advanced" },
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

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  citations?: string[];
  confidence?: number;
  runId?: string;
  startedAtMs?: number;
  endedAtMs?: number;
  debug?: ChatDebugInfo | null;
  traceData?: any;
  meta?: any; // provider/backend/failover transparency
  eventId?: string; // For feedback correlation
}

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
  onSend: (text: string) => void;
};

const ChatComposer = memo(function ChatComposer({ sending, onSend }: ChatComposerProps) {
  const [draft, setDraft] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = draft.trim().length > 0 && !sending;

  const handleSend = useCallback(() => {
    const trimmed = draft.trim();
    if (!trimmed || sending) return;
    onSend(trimmed);
    setDraft('');
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [draft, onSend, sending]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  return (
    <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
      <textarea
        id="chat-input"
        ref={textareaRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask a question about your codebase..."
        disabled={sending}
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
          alignSelf: 'flex-end',
        }}
        aria-label="Send message"
      >
        {sending ? 'Sending...' : 'Send'}
      </button>
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
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [typing, setTyping] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  
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

  // Per-message retrieval leg toggles (do NOT persist; user requested per-message control)
  const [includeVector, setIncludeVector] = useState(true);
  const [includeSparse, setIncludeSparse] = useState(true);
  const [includeGraph, setIncludeGraph] = useState(false);
  // Note: include_vector/sparse/graph are per-message settings on ChatRequest,
  // not config settings. They default to true in the Pydantic model.
  const [recallIntensity, setRecallIntensity] = useState<RecallIntensity | null>(null);

  // Chat 2.0: composable sources + model picker
  const sourcesInitRef = useRef(false);
  const [activeSources, setActiveSources] = useState<ActiveSources>({ corpus_ids: ['recall_default'] });
  const handleSourcesChange = useCallback(
    (next: ActiveSources) => {
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
    setActiveSources({ corpus_ids: defaults });
  }, [config]);

  const [chatModels, setChatModels] = useState<ChatModelInfo[]>([]);
  const [modelOverride, setModelOverride] = useState<string>('');
  useEffect(() => {
    if (!config) return;
    if (!chatModels.length) return;
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
      if (m.source === 'local') return `local:${m.id}`;
      if (m.source === 'openrouter') return `openrouter:${m.id}`;
      return String(m.id || '');
    };

    // If current selection is valid, don't override it.
    const optionValues = chatModels.map(toOverrideValue);
    if (modelOverride && optionValues.includes(modelOverride)) {
      return;
    }

    const localModels = chatModels.filter((m) => m.source === 'local');
    const localDefaultTrimmed = typeof localDefault === 'string' ? localDefault.trim() : '';
    const localDefaultOption =
      localDefaultTrimmed ? localModels.find((m) => String(m.id) === localDefaultTrimmed) : undefined;

    const openrouterDefaultOption =
      openrouterEnabled && openrouterDefaultTrimmed
        ? chatModels.find((m) => m.source === 'openrouter' && String(m.id) === openrouterDefaultTrimmed)
        : undefined;

    const uiDefault = typeof config.ui?.chat_default_model === 'string' ? config.ui.chat_default_model.trim() : '';
    const cloudDefaultOption = uiDefault
      ? chatModels.find((m) => {
          const id = String(m.id || '').trim();
          return id === uiDefault || id.endsWith(`/${uiDefault}`);
        })
      : undefined;

    const preferred =
      (openrouterDefaultOption ? `openrouter:${openrouterDefaultTrimmed}` : '') ||
      (localModels.length
        ? (localDefaultOption ? `local:${localDefaultTrimmed}` : `local:${localModels[0].id}`)
        : '') ||
      (cloudDefaultOption ? String(cloudDefaultOption.id) : '');

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
  const streamingSupportedRef = useRef<boolean | null>(null);
  
  // Tip rotation state for streaming indicator
  const [currentTip, setCurrentTip] = useState<typeof TRIBRID_TIPS[0] | null>(null);
  const [tipFade, setTipFade] = useState(true);
  const shuffledTipsRef = useRef<typeof TRIBRID_TIPS>([]);
  const tipIndexRef = useRef(0);
  
  // Feedback state: track which messages have received feedback
  const [messageFeedback, setMessageFeedback] = useState<Record<string, { type: string; rating?: number }>>({});
  
  // Send feedback to API
  const sendFeedback = async (eventId: string | undefined, messageId: string, signal: string) => {
    if (!eventId) return;
    
    try {
      const response = await fetch(api('feedback'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId, signal })
      });
      
      if (response.ok) {
        setMessageFeedback(prev => ({
          ...prev,
          [messageId]: { type: signal, rating: signal.startsWith('star') ? parseInt(signal.slice(4)) : undefined }
        }));
      }
    } catch (error) {
      console.error('[ChatInterface] Feedback error:', error);
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
      const fallbackModels: ChatModelInfo[] = [
        { id: 'gpt-4o-mini', provider: 'OpenAI', source: 'cloud_direct' },
      ];
      try {
        const qs = activeRepo ? `?corpus_id=${encodeURIComponent(activeRepo)}` : '';
        const r = await fetch(api(`chat/models${qs}`));
        if (!r.ok) {
          setChatModels(fallbackModels);
          return;
        }
        const d = (await r.json()) as ChatModelsResponse;
        const models = Array.isArray(d?.models) ? (d.models as ChatModelInfo[]) : [];
        setChatModels(models.length > 0 ? models : fallbackModels);
      } catch {
        // Best-effort; provide a sensible default so the UI can still run offline.
        setChatModels(fallbackModels);
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

  // Load repositories via store (once on mount if not initialized)
  useEffect(() => {
    if (!initialized) {
      loadRepos();
    }
    // Load chat history from localStorage
    loadChatHistory();
  }, [initialized, loadRepos]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: streaming ? 'auto' : 'smooth' });
  }, [messages.length, streaming]);

  const clampChatHistory = (msgs: Message[]): Message[] => {
    if (!Array.isArray(msgs)) return [];
    if (msgs.length <= chatHistoryMax) return msgs;
    return msgs.slice(-chatHistoryMax);
  };

  const loadChatHistory = () => {
    try {
      const saved = localStorage.getItem('tribrid-chat-history');
      if (saved) {
        const parsed = JSON.parse(saved);
        const trimmed = clampChatHistory(Array.isArray(parsed) ? (parsed as Message[]) : []);
        setMessages(trimmed);
        // If the stored history exceeds our cap, overwrite it immediately to avoid future slow boots.
        if (Array.isArray(parsed) && parsed.length !== trimmed.length) {
          saveChatHistory(trimmed);
        }
      }
    } catch (error) {
      console.error('[ChatInterface] Failed to load chat history:', error);
    }
  };

  const saveChatHistory = (msgs: Message[]) => {
    try {
      const trimmed = clampChatHistory(msgs);
      localStorage.setItem('tribrid-chat-history', JSON.stringify(trimmed));
    } catch (error) {
      console.error('[ChatInterface] Failed to save chat history:', error);
    }
  };

  const startThinking = () => {
    typingStartedAtRef.current = Date.now();
    setTyping(true);
  };

  const stopThinking = () => {
    const elapsed = typingStartedAtRef.current ? Date.now() - typingStartedAtRef.current : 0;
    const remaining = Math.max(0, 750 - elapsed);
    setTimeout(() => setTyping(false), remaining);
  };

  const formatConfidence = (value?: number | null) => {
    if (value === undefined || value === null || Number.isNaN(value)) return null;
    const pct = value <= 1 ? value * 100 : value;
    return `${pct.toFixed(1)}%`;
  };

  const citationToVscodeHref = (citation: string): string => {
    const m = citation.match(/^(.*?):(\d+)(?:-(\d+))?$/);
    if (!m) return `vscode://file/${citation}`;
    const filePath = m[1];
    const startLine = m[2];
    return `vscode://file/${filePath}:${startLine}`;
  };

  const handleSend = async (text: string) => {
    if (!text.trim() || sending) return;
    const recallIntensityOverride = recallIntensity;
    if (recallIntensityOverride !== null) {
      setRecallIntensity(null);
    }

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text.trim(),
      timestamp: Date.now()
    };

    const newMessages = clampChatHistory([...messages, userMessage]);
    setMessages(newMessages);
    saveChatHistory(newMessages);
    setSending(true);
    notifyTrace([], false, 'clear');
    startThinking();

    try {
      const streamingEnabled = streamPref && streamingSupportedRef.current !== false;
      if (streamingEnabled) {
        try {
          await handleStreamingResponse(userMessage, recallIntensityOverride);
          streamingSupportedRef.current = true;
        } catch (err) {
          streamingSupportedRef.current = false;
          await handleRegularResponse(userMessage, recallIntensityOverride);
        }
      } else {
        await handleRegularResponse(userMessage, recallIntensityOverride);
      }
    } catch (error) {
      console.error('[ChatInterface] Failed to send message:', error);
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `Error: ${error instanceof Error ? error.message : 'Failed to get response'}`,
        timestamp: Date.now()
      };
      const updatedMessages = clampChatHistory([...newMessages, errorMessage]);
      setMessages(updatedMessages);
      saveChatHistory(updatedMessages);
    } finally {
      setSending(false);
      setStreaming(false);
      stopThinking();
    }
  };

  const handleStreamingResponse = async (
    userMessage: Message,
    recallIntensityOverride: RecallIntensity | null
  ) => {
    setStreaming(true);

    // Stream from /api/chat/stream (SSE)
    const response = await fetch(api('chat/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userMessage.content,
        sources: activeSources,
        conversation_id: conversationId,
        stream: true,
        images: [],
        model_override: modelOverride,
        include_vector: includeVector,
        include_sparse: includeSparse,
        include_graph: includeGraph,
        recall_intensity: recallIntensityOverride,
      })
    });

    if (!response.ok) {
      throw new Error('Failed to start streaming');
    }

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    let streamBuffer = '';
    let accumulatedContent = '';
    const assistantMessageId = `assistant-${Date.now()}`;
    const assistantTimestamp = Date.now();
    let citations: string[] = [];
    let runId: string | undefined;
    let startedAtMs: number | undefined;
    let endedAtMs: number | undefined;
    let debug: ChatDebugInfo | null = null;
    let confidence: number | undefined;
    let rafPending = false;
    let persistAfterNextRender = false;

    if (!reader) {
      throw new Error('Response body is not readable');
    }

    const scheduleAssistantRender = (persist: boolean = false) => {
      if (persist) persistAfterNextRender = true;
      if (rafPending) return;
      const container = messagesContainerRef.current;
      const shouldAutoscroll =
        !!container && container.scrollHeight - container.scrollTop - container.clientHeight < 160;
      rafPending = true;

      requestAnimationFrame(() => {
        rafPending = false;
        const assistantMessage: Message = {
          id: assistantMessageId,
          role: 'assistant',
          content: accumulatedContent,
          timestamp: assistantTimestamp,
          citations,
          runId,
          startedAtMs,
          endedAtMs,
          debug,
          confidence,
        };

        setMessages((prev) => {
          const last = prev[prev.length - 1];
          let next: Message[];

          // Common path: streaming assistant message is the last item.
          if (last && last.id === assistantMessageId) {
            next = prev.slice();
            next[next.length - 1] = assistantMessage;
          } else {
            next = [...prev, assistantMessage];
          }

          next = clampChatHistory(next);

          if (persistAfterNextRender) {
            persistAfterNextRender = false;
            saveChatHistory(next);
          }

          return next;
        });

        if (shouldAutoscroll) {
          requestAnimationFrame(() => {
            messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
          });
        }
      });
    };

    const processDataLine = (line: string) => {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) return;
      const data = trimmed.slice(5).trim();
      if (!data || data === '[DONE]') return;

      try {
        const parsed = JSON.parse(data);
        const chunkType = parsed.type;

        switch (chunkType) {
          case 'text':
            if (typeof parsed.content === 'string') {
              accumulatedContent += parsed.content;
            }
            break;

          case 'done':
            // Server may include conversation_id in the final event (best-effort).
            if (typeof parsed.conversation_id === 'string') {
              setConversationId(parsed.conversation_id);
            }
            if (Array.isArray(parsed.sources)) {
              setLastMatches(parsed.sources as ChunkMatch[]);
              citations = parsed.sources
                .map((s: any) => {
                  const fp = s?.file_path;
                  const sl = s?.start_line;
                  const el = s?.end_line;
                  if (!fp) return null;
                  return `${fp}:${sl ?? 0}-${el ?? sl ?? 0}`;
                })
                .filter(Boolean) as string[];
            }
            if (typeof parsed.run_id === 'string') {
              runId = parsed.run_id;
            }
            if (typeof parsed.started_at_ms === 'number') {
              startedAtMs = parsed.started_at_ms;
            }
            if (typeof parsed.ended_at_ms === 'number') {
              const ended = parsed.ended_at_ms;
              endedAtMs = ended;
              if (typeof startedAtMs === 'number') {
                setLastLatencyMs(Math.max(0, ended - startedAtMs));
              }
            }
            debug = parsed && typeof parsed.debug === 'object' ? (parsed.debug as ChatDebugInfo) : null;
            confidence = typeof parsed?.debug?.confidence === 'number' ? parsed.debug.confidence : undefined;
            setLastRecallPlan((debug as any)?.recall_plan ?? null);

            try {
              window.dispatchEvent(
                new CustomEvent('tribrid:chat:run-complete', {
                  detail: {
                    run_id: runId,
                    started_at_ms: startedAtMs,
                    ended_at_ms: endedAtMs,
                  },
                })
              );
            } catch {}
            break;

          case 'error':
            console.error('[ChatInterface] Stream error:', parsed.message);
            accumulatedContent = `Error: ${parsed.message || 'Unknown error'}`;
            break;

          default:
            if (typeof parsed.content === 'string') {
              accumulatedContent += parsed.content;
            }
        }
        scheduleAssistantRender(chunkType === 'done' || chunkType === 'error');
      } catch (error) {
        console.error('[ChatInterface] Failed to parse SSE data:', error, data);
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      streamBuffer += decoder.decode(value, { stream: true });
      const lines = streamBuffer.split('\n');
      streamBuffer = lines.pop() || '';

      for (const line of lines) {
        processDataLine(line);
      }
    }

    const remaining = decoder.decode();
    if (remaining) {
      streamBuffer += remaining;
    }
    if (streamBuffer.trim()) {
      processDataLine(streamBuffer);
    }

    // Ensure the final assistant message is rendered + persisted exactly once.
    scheduleAssistantRender(true);
  };

  const handleRegularResponse = async (
    userMessage: Message,
    recallIntensityOverride: RecallIntensity | null
  ) => {
    const params = new URLSearchParams(window.location.search || '');
    const fast = fastMode || params.get('fast') === '1' || params.get('smoke') === '1';

    // NOTE: `fast` is currently a UI-only toggle. The backend chat API does not accept fast_mode yet.
    void fast;

    const response = await fetch(api('chat'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userMessage.content,
        sources: activeSources,
        conversation_id: conversationId,
        stream: false,
        images: [],
        model_override: modelOverride,
        include_vector: includeVector,
        include_sparse: includeSparse,
        include_graph: includeGraph,
        recall_intensity: recallIntensityOverride,
      })
    });

    if (!response.ok) {
      throw new Error('Failed to get response');
    }

    const data = await response.json();

    // New Pydantic ChatResponse: { run_id, started_at_ms, ended_at_ms, debug, conversation_id, message, sources, tokens_used }
    const nextConversationId: string | null =
      data && typeof data.conversation_id === 'string' ? data.conversation_id : null;
    if (nextConversationId) setConversationId(nextConversationId);

    const sources: ChunkMatch[] = Array.isArray(data?.sources) ? (data.sources as ChunkMatch[]) : [];
    setLastMatches(sources);
    const citations: string[] = sources
      .map((s: any) => {
        const fp = s?.file_path;
        const sl = s?.start_line;
        const el = s?.end_line;
        if (!fp) return null;
        return `${fp}:${sl ?? 0}-${el ?? sl ?? 0}`;
      })
      .filter(Boolean) as string[];

    const assistantText: string = String(data?.message?.content || '');
    const runId: string | undefined = typeof data?.run_id === 'string' ? data.run_id : undefined;
    const startedAtMs: number | undefined = typeof data?.started_at_ms === 'number' ? data.started_at_ms : undefined;
    const endedAtMs: number | undefined = typeof data?.ended_at_ms === 'number' ? data.ended_at_ms : undefined;
    if (typeof startedAtMs === 'number' && typeof endedAtMs === 'number') {
      setLastLatencyMs(Math.max(0, endedAtMs - startedAtMs));
    }
    const debug: ChatDebugInfo | null = data && typeof data?.debug === 'object' ? (data.debug as ChatDebugInfo) : null;
    setLastRecallPlan((debug as any)?.recall_plan ?? null);
    const confidence: number | undefined = typeof data?.debug?.confidence === 'number' ? data.debug.confidence : undefined;
    const assistantMessage: Message = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: assistantText,
      timestamp: Date.now(),
      citations,
      runId,
      startedAtMs,
      endedAtMs,
      debug,
      confidence,
    };

    try {
      window.dispatchEvent(
        new CustomEvent('tribrid:chat:run-complete', {
          detail: {
            run_id: runId,
            started_at_ms: startedAtMs,
            ended_at_ms: endedAtMs,
          },
        })
      );
    } catch {}

    setMessages((prev) => {
      const updated = clampChatHistory([...prev, assistantMessage]);
      saveChatHistory(updated);
      return updated;
    });
  };

  const handleClear = () => {
    if (confirm('Clear all messages?')) {
      setMessages([]);
      notifyTrace([], false, 'clear');
      localStorage.removeItem('tribrid-chat-history');
    }
  };

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
      {/* Header */}
      <div style={{
        padding: '16px',
        borderBottom: '1px solid var(--line)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'var(--bg-elev1)'
      }}>
        <div>
          <h3 style={{ margin: '0 0 4px 0', fontSize: '16px', fontWeight: '600' }}>
            <span style={{ color: 'var(--accent)' }}>●</span> RAG Chat
          </h3>
          <p style={{
            margin: '0',
            fontSize: '12px',
            color: 'var(--fg-muted)'
          }}>
            Ask questions about your codebase
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
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
          <div style={{ width: '360px', minWidth: '280px' }}>
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
            aria-label="Clear chat"
          >
            Clear
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
          <div style={{ width: '260px', borderRight: '1px solid var(--line)', background: 'var(--bg-elev1)', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '12px', borderBottom: '1px solid var(--line)', fontSize: '12px', fontWeight: 600, color: 'var(--fg)' }}>History</div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
              {messages.filter(m => m.role === 'user').slice(-20).reverse().map((m, i) => (
                <div key={`${m.id}-${i}`} style={{ padding: '8px', border: '1px solid var(--line)', borderRadius: '6px', marginBottom: '8px', background: 'var(--card-bg)' }}>
                  <div style={{ fontSize: '11px', opacity: 0.7 }}>{new Date(m.timestamp).toLocaleString()}</div>
                  <div style={{ fontSize: '12px', marginTop: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.content}</div>
                </div>
              ))}
              {messages.length === 0 && (
                <div style={{ fontSize: '12px', color: 'var(--fg-muted)', padding: '12px' }}>No messages yet</div>
              )}
            </div>
            <div style={{ padding: '8px', borderTop: '1px solid var(--line)' }}>
              <button onClick={handleClear} style={{ width: '100%', background: 'var(--bg-elev2)', color: 'var(--err)', border: '1px solid var(--err)', padding: '8px', borderRadius: '6px', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }}>New Chat</button>
            </div>
          </div>
        )}
        {/* Messages area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Messages */}
          <div id="chat-messages" ref={messagesContainerRef} style={{
            flex: 1,
            overflowY: 'auto',
            padding: '16px'
          }}>
            {messages.length === 0 ? (
              <div style={{
                textAlign: 'center',
                color: 'var(--fg-muted)',
                padding: '40px 20px'
              }}>
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                     style={{ opacity: 0.3, marginBottom: '12px' }}>
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <div style={{ fontSize: '14px' }}>Start a conversation with your codebase</div>
                <div style={{ fontSize: '11px', marginTop: '8px' }}>
                  Try: "Where is OAuth token validated?" or "How do we handle API errors?"
                </div>
              </div>
            ) : (
              messages.map(message => (
                <div
                  key={message.id}
                  data-role={message.role}
                  style={{
                    marginBottom: '16px',
                    display: 'flex',
                    justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start'
                  }}
                >
                  <div style={{
                    maxWidth: message.role === 'user' ? '70%' : '85%',
                    background: message.role === 'user' 
                      ? 'linear-gradient(135deg, var(--accent) 0%, var(--link) 100%)' 
                      : 'linear-gradient(135deg, var(--bg-elev1) 0%, var(--bg-elev2) 100%)',
                    color: message.role === 'user' ? 'var(--accent-contrast)' : 'var(--fg)',
                    padding: message.role === 'user' ? '12px 16px' : '16px 20px',
                    borderRadius: message.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                    position: 'relative',
                    boxShadow: message.role === 'user' 
                      ? '0 2px 8px rgba(0,0,0,0.2)' 
                      : '0 2px 12px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.05)',
                    border: message.role === 'assistant' ? '1px solid var(--line)' : 'none'
                  }}>
                    <div style={{ 
                      fontSize: '11px', 
                      opacity: 0.7, 
                      marginBottom: '8px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px'
                    }}>
                      {message.role === 'assistant' && <span style={{ fontSize: '14px' }}>🤖</span>}
                      {message.role === 'user' ? 'You' : 'Assistant'} · {new Date(message.timestamp).toLocaleTimeString()}
                      {message.role === 'assistant' && message.meta?.repo && (
                        <span style={{ 
                          background: 'var(--accent)', 
                          color: 'var(--accent-contrast)', 
                          padding: '1px 6px', 
                          borderRadius: '4px', 
                          fontSize: '10px',
                          fontWeight: 500
                        }}>
                          repo: {message.meta.repo}
                        </span>
                      )}
                    </div>
                    
                    {/* Confidence badge for assistant */}
                    {message.role === 'assistant' && showConfidence && message.confidence !== undefined && (
                      <div style={{
                        display: 'inline-block',
                        background: message.confidence > 0.7 ? 'var(--success)' : message.confidence > 0.4 ? 'var(--warn)' : 'var(--error)',
                        color: '#000',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 600,
                        marginBottom: '10px'
                      }}>
                        Confidence: {formatConfidence(message.confidence)}
                      </div>
                    )}
                    
                    {/* Message content - markdown for assistant, plain for user */}
                    {message.role === 'user' ? (
                      <div style={{
                        fontSize: '13px',
                        lineHeight: '1.6',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word'
                      }}>
                        {message.content}
                      </div>
                    ) : (
                      <AssistantMarkdown content={message.content} />
                    )}

                    {showCitations && message.citations && message.citations.length > 0 && (
                      <div style={{
                        marginTop: '8px',
                        paddingTop: '8px',
                        borderTop: '1px solid var(--line)',
                        fontSize: '11px',
                        opacity: 0.8
                      }}>
                        <strong>Citations:</strong>
                        {message.citations.map((citation, idx) => (
                          <div key={idx} style={{ marginTop: '4px' }}>
                            <a
                              href={citationToVscodeHref(citation)}
                              style={{
                                color: 'var(--link)',
                                textDecoration: 'none',
                                borderBottom: '1px solid var(--link)',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '11px',
                                cursor: 'pointer',
                              }}
                              title="Open in editor"
                              data-testid="chat-citation-link"
                            >
                              {citation}
                            </a>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Message footer with copy and feedback */}
                    <div style={{
                      marginTop: '8px',
                      fontSize: '10px',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: '8px',
                      opacity: 0.75
                    }}>
                      <button
                        onClick={() => handleCopy(message.content)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'inherit',
                          cursor: 'pointer',
                          padding: '2px 6px',
                          fontSize: '10px',
                          borderRadius: '4px',
                          transition: 'background 0.15s'
                        }}
                        aria-label="Copy message"
                        title="Copy to clipboard"
                      >
                        📋
                      </button>
                      
                      {/* Feedback controls for assistant messages */}
                      {message.role === 'assistant' && (
                        <div style={{ 
                          display: 'flex', 
                          alignItems: 'center', 
                          gap: '4px',
                          marginLeft: 'auto'
                        }}>
                          {/* Show submitted feedback state OR the feedback buttons */}
                          {messageFeedback[message.id] ? (
                            <span style={{ 
                              fontSize: '10px', 
                              color: messageFeedback[message.id].type === 'thumbsup' ? 'var(--success)' : 
                                     messageFeedback[message.id].type === 'thumbsdown' ? 'var(--warn)' : 'var(--accent)',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '3px'
                            }}>
                              {messageFeedback[message.id].type === 'thumbsup' && '👍'}
                              {messageFeedback[message.id].type === 'thumbsdown' && '👎'}
                              {messageFeedback[message.id].rating && '⭐'.repeat(messageFeedback[message.id].rating!)}
                              <span style={{ opacity: 0.7, marginLeft: '2px' }}>Thanks!</span>
                            </span>
                          ) : (
                            <>
                              {/* Thumbs up/down */}
                              <button
                                onClick={() => sendFeedback(message.eventId, message.id, 'thumbsup')}
                                style={{
                                  background: 'none',
                                  border: 'none',
                                  cursor: 'pointer',
                                  padding: '2px 4px',
                                  fontSize: '12px',
                                  borderRadius: '4px',
                                  transition: 'all 0.15s',
                                  opacity: 0.6
                                }}
                                aria-label="Helpful"
                                title="This was helpful - trains the reranker"
                              >
                                👍
                              </button>
                              <button
                                onClick={() => sendFeedback(message.eventId, message.id, 'thumbsdown')}
                                style={{
                                  background: 'none',
                                  border: 'none',
                                  cursor: 'pointer',
                                  padding: '2px 4px',
                                  fontSize: '12px',
                                  borderRadius: '4px',
                                  transition: 'all 0.15s',
                                  opacity: 0.6
                                }}
                                aria-label="Not helpful"
                                title="Not helpful - trains the reranker"
                              >
                                👎
                              </button>
                              
                              {/* Star rating - compact row */}
                              <span style={{ 
                                borderLeft: '1px solid var(--line)', 
                                paddingLeft: '6px', 
                                marginLeft: '2px',
                                display: 'flex',
                                gap: '1px'
                              }}>
                                {[1, 2, 3, 4, 5].map((star) => (
                                  <button
                                    key={star}
                                    onClick={() => sendFeedback(message.eventId, message.id, `star${star}`)}
                                    style={{
                                      background: 'none',
                                      border: 'none',
                                      cursor: 'pointer',
                                      padding: '1px 2px',
                                      fontSize: '11px',
                                      borderRadius: '2px',
                                      transition: 'all 0.15s',
                                      opacity: 0.4,
                                      lineHeight: 1
                                    }}
                                    aria-label={`Rate ${star} star${star > 1 ? 's' : ''}`}
                                    title={`Rate ${star}/5 - trains the reranker`}
                                  >
                                    ⭐
                                  </button>
                                ))}
                              </span>
                            </>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Dev footer (per-answer debug metadata) */}
                    {message.role === 'assistant' && showDebugFooter && (() => {
                      const dbg = message.debug;
                      if (!dbg && !message.runId) return null;

                      const conf =
                        typeof dbg?.confidence === 'number'
                          ? dbg.confidence
                          : typeof message.confidence === 'number'
                            ? message.confidence
                            : undefined;

                      const legs: string[] = [];
                      if (dbg?.include_vector && dbg.vector_enabled !== false) legs.push('vector');
                      if (dbg?.include_sparse && dbg.sparse_enabled !== false) legs.push('sparse');
                      if (dbg?.include_graph && dbg.graph_enabled !== false) legs.push('graph');
                      const legsText = legs.length ? legs.join(' + ') : '—';

                      let fusionText = '—';
                      if (dbg?.fusion_method === 'rrf') {
                        fusionText = `rrf(k=${dbg.rrf_k ?? '—'})`;
                      } else if (dbg?.fusion_method === 'weighted') {
                        const vw = typeof dbg.vector_weight === 'number' ? dbg.vector_weight.toFixed(2) : '—';
                        const sw = typeof dbg.sparse_weight === 'number' ? dbg.sparse_weight.toFixed(2) : '—';
                        const gw = typeof dbg.graph_weight === 'number' ? dbg.graph_weight.toFixed(2) : '—';
                        fusionText = `weighted(v=${vw}, s=${sw}, g=${gw}${dbg.normalize_scores ? ', norm' : ''})`;
                      }

                      const kText = dbg?.final_k_used ?? '—';
                      const countsText = dbg
                        ? `v:${dbg.vector_results ?? '—'} s:${dbg.sparse_results ?? '—'} g:${dbg.graph_hydrated_chunks ?? '—'} final:${dbg.final_results ?? '—'}`
                        : '—';
                      const runShort = message.runId ? message.runId.slice(0, 8) : '—';
                      const recallPlan = (dbg as any)?.recall_plan;
                      const recallIntensity =
                        typeof recallPlan?.intensity === 'string' ? (recallPlan.intensity as string) : null;
                      const recallReason = typeof recallPlan?.reason === 'string' ? (recallPlan.reason as string) : null;

                      return (
                        <div
                          data-testid="chat-debug-footer"
                          style={{
                            marginTop: '8px',
                            paddingTop: '8px',
                            borderTop: '1px solid var(--line)',
                            fontSize: '11px',
                            color: 'var(--fg-muted)',
                            opacity: 0.9,
                            display: 'flex',
                            flexWrap: 'wrap',
                            gap: '10px',
                            alignItems: 'center',
                          }}
                        >
                          <span>conf {typeof conf === 'number' ? formatConfidence(conf) : '—'}</span>
                          <span>legs {legsText}</span>
                          <span>fusion {fusionText}</span>
                          <span>k {kText}</span>
                          <span>{countsText}</span>
                          {recallIntensity ? <span>recall {recallIntensity}</span> : null}
                          {recallReason ? (
                            <span title={recallReason} style={{ maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              gate {recallReason}
                            </span>
                          ) : null}
                          <span>run {runShort}</span>
                          {recallGateShowSignals && recallPlan ? (
                            <details>
                              <summary style={{ cursor: 'pointer', color: 'var(--link)' }}>signals</summary>
                              <pre
                                style={{
                                  marginTop: 6,
                                  background: 'var(--bg-elev2)',
                                  border: '1px solid var(--line)',
                                  padding: 10,
                                  borderRadius: 8,
                                  maxWidth: 680,
                                  overflow: 'auto',
                                  whiteSpace: 'pre-wrap',
                                }}
                              >
                                {JSON.stringify(recallPlan, null, 2)}
                              </pre>
                            </details>
                          ) : null}
                          <button
                            type="button"
                            data-testid="chat-debug-view-trace"
                            onClick={() => handleViewTraceAndLogs(message)}
                            style={{
                              background: 'none',
                              border: 'none',
                              padding: 0,
                              color: 'var(--link)',
                              cursor: 'pointer',
                              textDecoration: 'underline',
                              fontSize: '11px',
                            }}
                            title="Jump to trace & logs for this run"
                          >
                            View trace &amp; logs
                          </button>
                        </div>
                      );
                    })()}
                  </div>
                </div>
              ))
            )}

            {/* Provider transparency indicator (accessibility) */}
            {messages.length > 0 && (
              <div style={{
                marginTop: '8px',
                fontSize: '11px',
                color: 'var(--fg-muted)'
              }}>
                {(() => {
                  const last = messages[messages.length - 1];
                  const m = last && last.meta ? last.meta : null;
                  if (!m) return null;
                  const parts: string[] = [];
                  const backend = m.backend || m.provider;
                  if (backend) parts.push(`backend: ${backend}`);
                  if (m.model) parts.push(`model: ${m.model}`);
                  if (m.failover && m.failover.from && m.failover.to) parts.push(`failover: ${m.failover.from} → ${m.failover.to}`);
                  if (!parts.length) return null;
                  return (<span>— [{parts.join(' • ')}]</span>);
                })()}
              </div>
            )}

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
            <ChatComposer sending={sending} onSend={handleSend} />

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
