// AGRO - Chat Interface Component
// Main chat UI with message list, input, streaming, and trace panel
// Reference: /assets/chat tab.png, /assets/chat_built_in.png

import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useAPI, useConfig } from '@/hooks';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RepoSelector } from '@/components/ui/RepoSelector';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { useEmbeddingStatus } from '@/hooks/useEmbeddingStatus';
import { useRepoStore } from '@/stores/useRepoStore';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

// Useful tips shown during response generation
// Each tip has content and optional category for styling
const AGRO_TIPS = [
  // RAG & Search Tips
  { tip: "Use specific file paths like 'server/app.py' to narrow your search to specific areas of the codebase.", category: "search" },
  { tip: "Try asking 'Where is X implemented?' rather than 'What is X?' for more precise code locations.", category: "search" },
  { tip: "Multi-query expansion rewrites your question multiple ways to find more relevant results.", category: "rag" },
  { tip: "The reranker scores results by semantic similarity - higher confidence means better matches.", category: "rag" },
  { tip: "BM25 finds keyword matches while dense search finds semantic meaning - AGRO uses both.", category: "rag" },
  { tip: "Click any citation to open the file directly in VS Code at the exact line number.", category: "ux" },
  { tip: "Fast mode skips reranking for quicker results when you need speed over precision.", category: "rag" },
  { tip: "The confidence score reflects how well the retrieved documents match your query.", category: "rag" },
  
  // Learning Reranker
  { tip: "Every thumbs up/down you give trains the Learning Reranker to better understand your codebase.", category: "feedback" },
  { tip: "The cross-encoder reranker learns from your feedback to improve result ordering over time.", category: "feedback" },
  { tip: "Consistent feedback helps AGRO learn your codebase's unique terminology and patterns.", category: "feedback" },
  { tip: "The reranker model checkpoints are saved automatically - your feedback is never lost.", category: "feedback" },
  
  // Prompts & Models
  { tip: "Custom system prompts let you tailor AGRO's response style to your team's preferences.", category: "config" },
  { tip: "Lower temperature (0.0-0.3) gives more focused answers; higher (0.7+) allows more creativity.", category: "config" },
  { tip: "You can use local models via Ollama for air-gapped environments or cost savings.", category: "config" },
  { tip: "The model automatically fails over to cloud APIs if local inference isn't available.", category: "config" },
  
  // Indexing
  { tip: "Re-index after major refactors to keep AGRO's understanding of your code current.", category: "indexing" },
  { tip: "The AST chunker preserves function boundaries - results always show complete code blocks.", category: "indexing" },
  { tip: "Semantic cards summarize files and classes for better high-level understanding.", category: "indexing" },
  { tip: "Index stats show when your codebase was last indexed - check Dashboard for details.", category: "indexing" },
  
  // Evaluation & Quality
  { tip: "Run evals regularly to track retrieval quality as your codebase evolves.", category: "eval" },
  { tip: "Golden questions are your benchmark - add questions that matter to your team.", category: "eval" },
  { tip: "MRR (Mean Reciprocal Rank) measures how quickly AGRO finds the right answer.", category: "eval" },
  { tip: "Compare eval runs to see if config changes improved or regressed retrieval quality.", category: "eval" },
  
  // Tracing & Debugging
  { tip: "Enable the Routing Trace to see exactly how AGRO found and ranked your results.", category: "debug" },
  { tip: "Trace steps show timing for each stage: retrieval, reranking, and generation.", category: "debug" },
  { tip: "The provider failover trace shows when AGRO switched between local and cloud models.", category: "debug" },
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
  { tip: "Ask follow-up questions - AGRO maintains context from your conversation history.", category: "best" },
  { tip: "Be specific about what you're looking for: 'error handling in auth' beats 'auth code'.", category: "best" },
  { tip: "If results seem off, try rephrasing - different words can surface different code.", category: "best" },
  { tip: "Check citations to verify the answer - AGRO shows exactly where information came from.", category: "best" },
  { tip: "Use the repo selector to focus on specific repositories in multi-repo setups.", category: "best" },
  
  // Advanced
  { tip: "Profiles let you save and switch between different AGRO configurations instantly.", category: "advanced" },
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

export function ChatInterface({ traceOpen, onTraceUpdate, onTracePreferenceChange }: ChatInterfaceProps) {
  const { api } = useAPI();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [typing, setTyping] = useState(false);
  // Per-query repo override - empty string means use the global activeRepo
  const [queryRepoOverride, setQueryRepoOverride] = useState('');
  
  // Use centralized repo store for repo list and default
  const { repos, activeRepo, loadRepos, initialized } = useRepoStore();
  
  // Check if index exists for "no index" warning
  const { status: embeddingStatus } = useEmbeddingStatus();
  const [tracePreference, setTracePreference] = useState<boolean>(() => {
    if (traceOpen !== undefined) return Boolean(traceOpen);
    return chatShowTrace;
  });
  const [currentTrace, setCurrentTrace] = useState<TraceStep[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const typingStartedAtRef = useRef<number | null>(null);
  const streamingSupportedRef = useRef<boolean | null>(null);
  
  // Tip rotation state for streaming indicator
  const [currentTip, setCurrentTip] = useState<typeof AGRO_TIPS[0] | null>(null);
  const [tipFade, setTipFade] = useState(true);
  const shuffledTipsRef = useRef<typeof AGRO_TIPS>([]);
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
      shuffledTipsRef.current = shuffleArray(AGRO_TIPS);
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
          shuffledTipsRef.current = shuffleArray(AGRO_TIPS);
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

  // Chat settings state - Pydantic/Zustand-backed
  const { get, set: setConfigValue } = useConfig();
  const model = get('GEN_MODEL_CHAT', get('GEN_MODEL', ''));
  const systemPrompt = get('PROMPT_MAIN_RAG_CHAT', '');
  const temperature = get('GEN_TEMPERATURE', 0);
  const maxTokens = get('GEN_MAX_TOKENS', 1000);
  const topP = get('GEN_TOP_P', 1);
  const topK = get('FINAL_K', 10);
  const chatStreamingEnabled = Boolean(get('CHAT_STREAMING_ENABLED', 1));
  const chatShowConfidence = Boolean(get('CHAT_SHOW_CONFIDENCE', 0));
  const chatShowCitations = Boolean(get('CHAT_SHOW_CITATIONS', 1));
  const chatShowTrace = Boolean(get('CHAT_SHOW_TRACE', 0));
  const [streamPref, setStreamPref] = useState<boolean>(() => chatStreamingEnabled);
  const [showConfidence, setShowConfidence] = useState<boolean>(() => chatShowConfidence);
  const [showCitations, setShowCitations] = useState<boolean>(() => chatShowCitations);
  const traceRef = useRef<TraceStep[]>([]);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
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
    if (traceOpen === undefined) {
      setTracePreference(chatShowTrace);
    }
  }, [chatShowTrace, traceOpen]);

  // Define notifyTrace before useEffects that use it
  const notifyTrace = useCallback((steps: TraceStep[], open: boolean, source: 'config' | 'response' | 'clear' = 'response') => {
    setCurrentTrace(steps);
    traceRef.current = steps;
    const effectiveOpen = source === 'response' ? (open && tracePreference) : open;
    onTraceUpdate?.(steps, effectiveOpen, source);
  }, [onTraceUpdate, tracePreference]);

  // Load model options (backend discovery)
  useEffect(() => {
    (async () => {
      try {
        const p = await fetch(api('/api/models'));
        if (p.ok) {
          const d = await p.json();
          const list = (d.models || [])
            .filter((m: any) => (m && (String(m.unit || '').toLowerCase() === '1k_tokens')))
            .map((m: any) => String(m.model || '').trim())
            .filter(Boolean);
          setModelOptions(Array.from(new Set(list)));
        }
      } catch {}
    })();
  }, [api]);

  // React to config updates from ChatSettings (cross-component sync)
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail || {};
      if (detail && typeof detail === 'object') {
        if (Object.prototype.hasOwnProperty.call(detail, 'streaming')) {
          const val = Boolean(detail.streaming);
          setStreamPref(val);
          setConfigValue('CHAT_STREAMING_ENABLED', val ? 1 : 0);
        }
        if (Object.prototype.hasOwnProperty.call(detail, 'showConfidence')) {
          const val = Boolean(detail.showConfidence);
          setShowConfidence(val);
          setConfigValue('CHAT_SHOW_CONFIDENCE', val ? 1 : 0);
        }
        if (Object.prototype.hasOwnProperty.call(detail, 'showCitations')) {
          const val = Boolean(detail.showCitations);
          setShowCitations(val);
          setConfigValue('CHAT_SHOW_CITATIONS', val ? 1 : 0);
        }
        if (Object.prototype.hasOwnProperty.call(detail, 'showTrace')) {
          const pref = Boolean(detail.showTrace);
          setTracePreference(pref);
          onTracePreferenceChange?.(pref);
          notifyTrace(traceRef.current, pref, 'config');
          setConfigValue('CHAT_SHOW_TRACE', pref ? 1 : 0);
        }
      }
    };
    window.addEventListener('agro-chat-config-updated', handler as EventListener);
    return () => window.removeEventListener('agro-chat-config-updated', handler as EventListener);
  }, [notifyTrace, onTracePreferenceChange]);

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
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadChatHistory = () => {
    try {
      const saved = localStorage.getItem('agro-chat-history');
      if (saved) {
        const parsed = JSON.parse(saved);
        setMessages(parsed);
      }
    } catch (error) {
      console.error('[ChatInterface] Failed to load chat history:', error);
    }
  };

  const saveChatHistory = (msgs: Message[]) => {
    try {
      localStorage.setItem('agro-chat-history', JSON.stringify(msgs));
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

  const handleSend = async () => {
    if (!input.trim() || sending) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: Date.now()
    };

    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    saveChatHistory(newMessages);
    setInput('');
    setSending(true);
    notifyTrace([], false, 'clear');
    startThinking();

    try {
      const streamingEnabled = streamPref && streamingSupportedRef.current !== false;
      if (streamingEnabled) {
        try {
          await handleStreamingResponse(userMessage);
          streamingSupportedRef.current = true;
        } catch (err) {
          streamingSupportedRef.current = false;
          await handleRegularResponse(userMessage);
        }
      } else {
        await handleRegularResponse(userMessage);
      }
    } catch (error) {
      console.error('[ChatInterface] Failed to send message:', error);
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `Error: ${error instanceof Error ? error.message : 'Failed to get response'}`,
        timestamp: Date.now()
      };
      const updatedMessages = [...newMessages, errorMessage];
      setMessages(updatedMessages);
      saveChatHistory(updatedMessages);
    } finally {
      setSending(false);
      setStreaming(false);
      stopThinking();
    }
  };

  const handleStreamingResponse = async (userMessage: Message) => {
    setStreaming(true);

    const params = new URLSearchParams(window.location.search || '');
    const fast = fastMode || params.get('fast') === '1' || params.get('smoke') === '1';

    // Use unified /api/chat endpoint with stream: true
    const response = await fetch(api('chat'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: userMessage.content,
        repo: queryRepoOverride || activeRepo || null,
        model,
        temperature,
        max_tokens: maxTokens,
        multi_query: 1,
        final_k: topK,
        top_p: topP,
        system_prompt: systemPrompt,
        fast_mode: fast,
        stream: true,
        include_reasoning: false,
        history: messages.map(m => ({ role: m.role, content: m.content }))
      })
    });

    if (!response.ok) {
      throw new Error('Failed to start streaming');
    }

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    let streamBuffer = '';
    let accumulatedContent = '';
    let thinkingContent = '';
    let assistantMessageId = `assistant-${Date.now()}`;
    let citations: string[] = [];
    let traceData: any = null;
    let confidence: number | undefined;
    let meta: any = undefined;
    let eventId: string | undefined;

    if (!reader) {
      throw new Error('Response body is not readable');
    }

    const processDataLine = (line: string) => {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) return;
      const data = trimmed.slice(5).trim();
      if (!data || data === '[DONE]') return;

      try {
        const parsed = JSON.parse(data);
        const chunkType = parsed.type;

        switch (chunkType) {
          case 'thinking':
            if (parsed.content) {
              thinkingContent += parsed.content;
            }
            break;

          case 'content':
            if (parsed.content) {
              accumulatedContent += parsed.content;
            }
            break;

          case 'citations':
            if (parsed.data?.citations) {
              citations = parsed.data.citations;
            }
            if (typeof parsed.data?.confidence === 'number') {
              confidence = parsed.data.confidence;
            }
            break;

          case 'trace':
            if (parsed.data) {
              traceData = parsed.data;
              const steps = parsed.data.steps || [];
              notifyTrace(steps, tracePreference, 'response');
            }
            break;

          case 'meta':
            if (parsed.data) {
              meta = parsed.data;
            }
            break;

          case 'done':
            if (parsed.data?.event_id) {
              eventId = parsed.data.event_id;
            }
            if (typeof parsed.data?.confidence === 'number') {
              confidence = parsed.data.confidence;
            }
            break;

          case 'error':
            console.error('[ChatInterface] Stream error:', parsed.data?.message);
            accumulatedContent = `Error: ${parsed.data?.message || 'Unknown error'}`;
            break;

          default:
            if (parsed.content) {
              accumulatedContent += parsed.content;
            }
            if (parsed.citations) {
              citations = parsed.citations;
            }
            if (typeof parsed.confidence === 'number') {
              confidence = parsed.confidence;
            }
        }

        const assistantMessage: Message = {
          id: assistantMessageId,
          role: 'assistant',
          content: accumulatedContent,
          timestamp: Date.now(),
          citations,
          traceData,
          confidence,
          meta,
          eventId
        };

        setMessages(prev => {
          const withoutLast = prev.filter(m => m.id !== assistantMessageId);
          return [...withoutLast, assistantMessage];
        });
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

    // Save final state
    setMessages(prev => {
      saveChatHistory(prev);
      return prev;
    });
  };

  const handleRegularResponse = async (userMessage: Message) => {
    const params = new URLSearchParams(window.location.search || '');
    const fast = fastMode || params.get('fast') === '1' || params.get('smoke') === '1';
    const response = await fetch(api('chat'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: userMessage.content,
        repo: queryRepoOverride || activeRepo || null,
        model,
        temperature,
        max_tokens: maxTokens,
        multi_query: 1,
        final_k: topK,
        top_p: topP,
        system_prompt: systemPrompt,
        fast_mode: fast
      })
    });

    if (!response.ok) {
      throw new Error('Failed to get response');
    }

    const data = await response.json();

    // Extract provider metadata for a separate accessibility line
    let meta: any = undefined;
    try {
      meta = data.meta && typeof data.meta === 'object' ? data.meta : {};
      if (!Object.keys(meta).length) {
        // Backward compat: some backends return flat fields
        const prov = data.provider || undefined;
        const backend = data.backend || prov || undefined;
        const modelUsed = data.model || undefined;
        const fail = data.failover || undefined;
        const ollama = data.ollama || undefined;
        meta = { backend, provider: prov, model: modelUsed, failover: fail, ollama };
      }
    } catch {}

    const confidenceValue = typeof data.confidence === 'number'
      ? data.confidence
      : (typeof (meta?.confidence) === 'number' ? meta.confidence : undefined);
    let citations: string[] = Array.isArray(data.citations) ? data.citations : [];
    if (!citations.length && Array.isArray(data.documents)) {
      citations = data.documents
        .map((d: any) => {
          const fp = d?.file_path || d?.path;
          const sl = d?.start_line ?? d?.start;
          const el = d?.end_line ?? d?.end;
          if (!fp) return null;
          return `${fp}:${sl ?? 0}-${el ?? sl ?? 0}`;
        })
        .filter(Boolean) as string[];
    }

    const assistantMessage: Message = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: (data.answer || ''),
      timestamp: Date.now(),
      meta,
      citations,
      confidence: confidenceValue,
      eventId: data.event_id // For feedback correlation
    };

    const updatedMessages = [...messages, userMessage, assistantMessage];
    setMessages(updatedMessages);
    saveChatHistory(updatedMessages);

    // Attach feedback controls and local trace when available
    try {
      // DISABLED: Legacy feedback buttons cause DOM conflicts with React
      // const evtId = data.event_id;
      // if (evtId && typeof (window as any).addFeedbackButtons === 'function') {
      //   requestAnimationFrame(() => {
      //     const target = document.getElementById(`feedback-${assistantMessage.id}`) || document.getElementById('chat-messages');
      //     if (target) {
      //       (window as any).addFeedbackButtons(target, evtId);
      //     }
      //   });
      // }
      if (data.trace && Array.isArray(data.trace.steps)) {
        const steps = data.trace.steps;
        notifyTrace(steps, tracePreference, 'response');
      } else {
        // Fallback: read latest persisted trace for richer detail
        try {
          const lt = await fetch(api('/traces/latest'));
          if (lt.ok) {
            const j = await lt.json();
            if (j && j.trace && Array.isArray(j.trace.events)) {
              const evs = j.trace.events.map((e: any) => ({ step: e.kind, duration: e.data?.duration_ms, details: e.data || {} }));
              if (evs.length) {
                notifyTrace(evs, tracePreference, 'response');
              }
            }
          }
        } catch {}
      }
      // DISABLED: Legacy trace loader causes DOM conflicts
      // if (tracePreference) {
      //   requestAnimationFrame(() => {
      //     try {
      //       (window as any).Trace?.loadLatestTrace?.('chat-trace-output');
      //     } catch {}
      //   });
      // }
    } catch {}
  };

  const handleClear = () => {
    if (confirm('Clear all messages?')) {
      setMessages([]);
      notifyTrace([], false, 'clear');
      localStorage.removeItem('agro-chat-history');
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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  };

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
          <RepoSelector
            id="chat-repo-select"
            value={queryRepoOverride}
            onChange={setQueryRepoOverride}
            showAutoDetect={true}
            compact={true}
          />

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
      {embeddingStatus && !embeddingStatus.hasIndex && embeddingStatus.totalChunks === 0 && (
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
                No Index Found
              </div>
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                You need to index your codebase before chat can search it. 
                Go to <a 
                  href="/#/rag?subtab=indexing" 
                  style={{ color: 'var(--link)', textDecoration: 'underline' }}
                >
                  RAG → Indexing
                </a> and click "INDEX NOW" to get started.
              </div>
            </div>
          </div>
        </div>
      )}

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
          <div id="chat-messages" style={{
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
                      <div className="chat-markdown" style={{
                        fontSize: '13px',
                        lineHeight: '1.7'
                      }}>
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            code({ node, inline, className, children, ...props }: any) {
                              const match = /language-(\w+)/.exec(className || '');
                              const codeString = String(children).replace(/\n$/, '');
                              return !inline && match ? (
                                <div style={{ margin: '12px 0', borderRadius: '8px', overflow: 'hidden' }}>
                                  <div style={{
                                    background: '#1e1e2e',
                                    padding: '6px 12px',
                                    fontSize: '10px',
                                    color: '#888',
                                    borderBottom: '1px solid #333',
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center'
                                  }}>
                                    <span>{match[1]}</span>
                                    <button
                                      onClick={() => navigator.clipboard.writeText(codeString)}
                                      style={{
                                        background: 'none',
                                        border: 'none',
                                        color: '#888',
                                        cursor: 'pointer',
                                        fontSize: '10px'
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
                                      background: '#1e1e2e'
                                    }}
                                    {...props}
                                  >
                                    {codeString}
                                  </SyntaxHighlighter>
                                </div>
                              ) : (
                                <code style={{
                                  background: 'rgba(0,0,0,0.3)',
                                  padding: '2px 6px',
                                  borderRadius: '4px',
                                  fontSize: '12px',
                                  fontFamily: 'monospace'
                                }} {...props}>
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
                              return <h1 style={{ fontSize: '18px', fontWeight: 600, margin: '16px 0 8px 0', color: 'var(--accent)' }}>{children}</h1>;
                            },
                            h2({ children }) {
                              return <h2 style={{ fontSize: '16px', fontWeight: 600, margin: '14px 0 6px 0', color: 'var(--accent)' }}>{children}</h2>;
                            },
                            h3({ children }) {
                              return <h3 style={{ fontSize: '14px', fontWeight: 600, margin: '12px 0 4px 0' }}>{children}</h3>;
                            },
                            strong({ children }) {
                              return <strong style={{ fontWeight: 600, color: 'var(--fg)' }}>{children}</strong>;
                            },
                            a({ href, children }) {
                              return <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--link)', textDecoration: 'underline' }}>{children}</a>;
                            },
                            blockquote({ children }) {
                              return (
                                <blockquote style={{
                                  borderLeft: '3px solid var(--accent)',
                                  margin: '12px 0',
                                  padding: '8px 16px',
                                  background: 'rgba(0,0,0,0.2)',
                                  borderRadius: '0 8px 8px 0',
                                  fontStyle: 'italic'
                                }}>
                                  {children}
                                </blockquote>
                              );
                            },
                            table({ children }) {
                              return (
                                <div style={{ overflowX: 'auto', margin: '12px 0' }}>
                                  <table style={{ 
                                    borderCollapse: 'collapse', 
                                    width: '100%',
                                    fontSize: '12px'
                                  }}>
                                    {children}
                                  </table>
                                </div>
                              );
                            },
                            th({ children }) {
                              return <th style={{ 
                                border: '1px solid var(--line)', 
                                padding: '8px', 
                                background: 'var(--bg-elev2)',
                                textAlign: 'left'
                              }}>{children}</th>;
                            },
                            td({ children }) {
                              return <td style={{ 
                                border: '1px solid var(--line)', 
                                padding: '8px' 
                              }}>{children}</td>;
                            }
                          }}
                        >
                          {message.content}
                        </ReactMarkdown>
                      </div>
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
                            {citation}
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
            <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
              <textarea
                id="chat-input"
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
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
                  maxHeight: '120px'
                }}
                rows={2}
                aria-label="Chat input"
              />
              <button
                id="chat-send"
                onClick={handleSend}
                disabled={!input.trim() || sending}
                style={{
                  background: input.trim() && !sending ? 'var(--accent)' : 'var(--bg-elev2)',
                  color: input.trim() && !sending ? 'var(--accent-contrast)' : 'var(--fg-muted)',
                  border: 'none',
                  padding: '12px 24px',
                  borderRadius: '6px',
                  fontSize: '14px',
                  fontWeight: '600',
                  cursor: input.trim() && !sending ? 'pointer' : 'not-allowed',
                  height: 'fit-content',
                  alignSelf: 'flex-end'
                }}
                aria-label="Send message"
              >
                {sending ? 'Sending...' : 'Send'}
              </button>
            </div>

            <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
              Press Ctrl+Enter to send • Citations appear as clickable file links when enabled in settings
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
                Model
              </label>
              {modelOptions.length > 0 ? (
                <select
                  value={model}
                  onChange={(e) => setConfigValue('GEN_MODEL', e.target.value)}
                  style={{
                    width: '100%',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    color: 'var(--fg)',
                    padding: '6px 8px',
                    borderRadius: '4px',
                    fontSize: '12px'
                  }}
                >
                  {modelOptions.map(m => (<option key={m} value={m}>{m}</option>))}
                </select>
              ) : (
                <input
                  type="text"
                  value={model}
                  onChange={(e) => setConfigValue('GEN_MODEL', e.target.value)}
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
              )}
            </div>

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
                onChange={(e) => setConfigValue('GEN_TEMPERATURE', parseFloat(e.target.value))}
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
                onChange={(e) => setConfigValue('GEN_MAX_TOKENS', parseInt(e.target.value))}
                min="1"
                max="32000"
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
                Top-p: {topP}
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={topP}
                onChange={(e) => setConfigValue('GEN_TOP_P', parseFloat(e.target.value))}
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
                Top-K (results)
              </label>
              <input
                type="number"
                value={topK}
                onChange={(e) => setConfigValue('FINAL_K', Math.max(1, parseInt(e.target.value) || 10))}
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

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
