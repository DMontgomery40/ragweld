import type React from 'react';
import type { Message } from '@/components/Chat/chatSessions';

type MessageFeedback = Record<string, { type: string; rating?: number }>;

type ChatMessageThreadProps = {
  messages: Message[];
  showConfidence: boolean;
  showCitations: boolean;
  showDebugFooter: boolean;
  showRecallGateSignals: boolean;
  messageFeedback: MessageFeedback;
  onCopy: (content: string) => void;
  onSendFeedback: (message: Message, signal: string) => void;
  onViewTraceAndLogs: (message: Message) => void;
  renderAssistantContent: (content: string) => React.ReactNode;
};

function formatConfidence(value?: number | null): string | null {
  if (value === undefined || value === null || Number.isNaN(value)) return null;
  const percent = value <= 1 ? value * 100 : value;
  return `${percent.toFixed(1)}%`;
}

function citationToVscodeHref(citation: string): string {
  const match = citation.match(/^(.*?):(\d+)(?:-(\d+))?$/);
  if (!match) return `vscode://file/${citation}`;
  const filePath = match[1];
  const startLine = match[2];
  return `vscode://file/${filePath}:${startLine}`;
}

export function ChatMessageThread({
  messages,
  showConfidence,
  showCitations,
  showDebugFooter,
  showRecallGateSignals,
  messageFeedback,
  onCopy,
  onSendFeedback,
  onViewTraceAndLogs,
  renderAssistantContent,
}: ChatMessageThreadProps) {
  if (messages.length === 0) {
    return (
      <div
        style={{
          textAlign: 'center',
          color: 'var(--fg-muted)',
          padding: '40px 20px',
        }}
      >
        <svg
          width="48"
          height="48"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          style={{ opacity: 0.3, marginBottom: '12px' }}
        >
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <div style={{ fontSize: '14px' }}>Start a conversation with your codebase</div>
        <div style={{ fontSize: '11px', marginTop: '8px' }}>
          Try: "Where is OAuth token validated?" or "How do we handle API errors?"
        </div>
      </div>
    );
  }

  return (
    <>
      {messages.map((message) => (
        <div
          key={message.id}
          data-role={message.role}
          style={{
            marginBottom: '16px',
            display: 'flex',
            justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start',
          }}
        >
          <div
            style={{
              maxWidth: message.role === 'user' ? '70%' : '85%',
              background:
                message.role === 'user'
                  ? 'linear-gradient(135deg, var(--accent) 0%, var(--link) 100%)'
                  : 'linear-gradient(135deg, var(--bg-elev1) 0%, var(--bg-elev2) 100%)',
              color: message.role === 'user' ? 'var(--accent-contrast)' : 'var(--fg)',
              padding: message.role === 'user' ? '12px 16px' : '16px 20px',
              borderRadius: message.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
              position: 'relative',
              boxShadow:
                message.role === 'user'
                  ? '0 2px 8px rgba(0,0,0,0.2)'
                  : '0 2px 12px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.05)',
              border: message.role === 'assistant' ? '1px solid var(--line)' : 'none',
            }}
          >
            <div
              style={{
                fontSize: '11px',
                opacity: 0.7,
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              {message.role === 'assistant' && <span style={{ fontSize: '14px' }}>🤖</span>}
              {message.role === 'user' ? 'You' : 'Assistant'} · {new Date(message.timestamp).toLocaleTimeString()}
              {message.role === 'assistant' && message.meta?.repo && (
                <span
                  style={{
                    background: 'var(--accent)',
                    color: 'var(--accent-contrast)',
                    padding: '1px 6px',
                    borderRadius: '4px',
                    fontSize: '10px',
                    fontWeight: 500,
                  }}
                >
                  repo: {message.meta.repo}
                </span>
              )}
            </div>

            {message.role === 'assistant' && showConfidence && message.confidence !== undefined && (
              <div
                style={{
                  display: 'inline-block',
                  background:
                    message.confidence > 0.7
                      ? 'var(--success)'
                      : message.confidence > 0.4
                        ? 'var(--warn)'
                        : 'var(--error)',
                  color: '#000',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  fontSize: '10px',
                  fontWeight: 600,
                  marginBottom: '10px',
                }}
              >
                Confidence: {formatConfidence(message.confidence)}
              </div>
            )}

            {message.role === 'user' ? (
              <div>
                <div
                  style={{
                    fontSize: '13px',
                    lineHeight: '1.6',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {message.content}
                </div>
                {Array.isArray(message.images) && message.images.length > 0 && (
                  <div
                    data-testid="chat-message-images"
                    style={{
                      marginTop: '8px',
                      display: 'flex',
                      gap: '8px',
                      flexWrap: 'wrap',
                    }}
                  >
                    {message.images.map((attachment, index) => (
                      <img
                        key={index}
                        src={`data:${attachment.mime_type};base64,${attachment.base64}`}
                        alt={`Sent image ${index + 1}`}
                        style={{
                          width: '88px',
                          height: '88px',
                          objectFit: 'cover',
                          borderRadius: '8px',
                          border: '1px solid rgba(255,255,255,0.25)',
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
            ) : (
              renderAssistantContent(message.content)
            )}

            {showCitations && message.citations && message.citations.length > 0 && (
              <div
                style={{
                  marginTop: '8px',
                  paddingTop: '8px',
                  borderTop: '1px solid var(--line)',
                  fontSize: '11px',
                  opacity: 0.8,
                }}
              >
                <strong>Citations:</strong>
                {message.citations.map((citation, index) => (
                  <div key={index} style={{ marginTop: '4px' }}>
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

            <div
              style={{
                marginTop: '8px',
                fontSize: '10px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '8px',
                opacity: 0.75,
              }}
            >
              <button
                onClick={() => onCopy(message.content)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'inherit',
                  cursor: 'pointer',
                  padding: '2px 6px',
                  fontSize: '10px',
                  borderRadius: '4px',
                  transition: 'background 0.15s',
                }}
                aria-label="Copy message"
                title="Copy to clipboard"
              >
                📋
              </button>

              {message.role === 'assistant' && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    marginLeft: 'auto',
                  }}
                >
                  {messageFeedback[message.id] ? (
                    <span
                      style={{
                        fontSize: '10px',
                        color:
                          messageFeedback[message.id].type === 'thumbsup'
                            ? 'var(--success)'
                            : messageFeedback[message.id].type === 'thumbsdown'
                              ? 'var(--warn)'
                              : 'var(--accent)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '3px',
                      }}
                    >
                      {messageFeedback[message.id].type === 'thumbsup' && '👍'}
                      {messageFeedback[message.id].type === 'thumbsdown' && '👎'}
                      {messageFeedback[message.id].rating && '⭐'.repeat(messageFeedback[message.id].rating!)}
                      <span style={{ opacity: 0.7, marginLeft: '2px' }}>Thanks!</span>
                    </span>
                  ) : (
                    <>
                      <button
                        onClick={() => onSendFeedback(message, 'thumbsup')}
                        style={{
                          background: 'none',
                          border: 'none',
                          cursor: 'pointer',
                          padding: '2px 4px',
                          fontSize: '12px',
                          borderRadius: '4px',
                          transition: 'all 0.15s',
                          opacity: 0.6,
                        }}
                        aria-label="Helpful"
                        title="This was helpful - trains the reranker"
                      >
                        👍
                      </button>
                      <button
                        onClick={() => onSendFeedback(message, 'thumbsdown')}
                        style={{
                          background: 'none',
                          border: 'none',
                          cursor: 'pointer',
                          padding: '2px 4px',
                          fontSize: '12px',
                          borderRadius: '4px',
                          transition: 'all 0.15s',
                          opacity: 0.6,
                        }}
                        aria-label="Not helpful"
                        title="Not helpful - trains the reranker"
                      >
                        👎
                      </button>

                      <span
                        style={{
                          borderLeft: '1px solid var(--line)',
                          paddingLeft: '6px',
                          marginLeft: '2px',
                          display: 'flex',
                          gap: '1px',
                        }}
                      >
                        {[1, 2, 3, 4, 5].map((star) => (
                          <button
                            key={star}
                            onClick={() => onSendFeedback(message, `star${star}`)}
                            style={{
                              background: 'none',
                              border: 'none',
                              cursor: 'pointer',
                              padding: '1px 2px',
                              fontSize: '11px',
                              borderRadius: '2px',
                              transition: 'all 0.15s',
                              opacity: 0.4,
                              lineHeight: 1,
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

            {message.role === 'assistant' && showDebugFooter && (() => {
              const debug = message.debug;
              if (!debug && !message.runId) return null;

              const confidence =
                typeof debug?.confidence === 'number'
                  ? debug.confidence
                  : typeof message.confidence === 'number'
                    ? message.confidence
                    : undefined;

              const legs: string[] = [];
              if (debug?.include_vector && debug.vector_enabled !== false) legs.push('vector');
              if (debug?.include_sparse && debug.sparse_enabled !== false) legs.push('sparse');
              if (debug?.include_graph && debug.graph_enabled !== false) legs.push('graph');
              const legsText = legs.length ? legs.join(' + ') : '—';

              let fusionText = '—';
              if (debug?.fusion_method === 'rrf') {
                fusionText = `rrf(k=${debug.rrf_k ?? '—'})`;
              } else if (debug?.fusion_method === 'weighted') {
                const vectorWeight = typeof debug.vector_weight === 'number' ? debug.vector_weight.toFixed(2) : '—';
                const sparseWeight = typeof debug.sparse_weight === 'number' ? debug.sparse_weight.toFixed(2) : '—';
                const graphWeight = typeof debug.graph_weight === 'number' ? debug.graph_weight.toFixed(2) : '—';
                fusionText = `weighted(v=${vectorWeight}, s=${sparseWeight}, g=${graphWeight}${debug.normalize_scores ? ', norm' : ''})`;
              }

              const resultCountText = debug
                ? `v:${debug.vector_results ?? '—'} s:${debug.sparse_results ?? '—'} g:${debug.graph_hydrated_chunks ?? '—'} final:${debug.final_results ?? '—'}`
                : '—';
              const runShort = message.runId ? message.runId.slice(0, 8) : '—';
              const recallPlan = (debug as any)?.recall_plan;
              const recallIntensity = typeof recallPlan?.intensity === 'string' ? (recallPlan.intensity as string) : null;
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
                  <span>conf {typeof confidence === 'number' ? formatConfidence(confidence) : '—'}</span>
                  <span>legs {legsText}</span>
                  <span>fusion {fusionText}</span>
                  <span>k {debug?.final_k_used ?? '—'}</span>
                  <span>{resultCountText}</span>
                  {recallIntensity ? <span>recall {recallIntensity}</span> : null}
                  {recallReason ? (
                    <span title={recallReason} style={{ maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      gate {recallReason}
                    </span>
                  ) : null}
                  <span>run {runShort}</span>
                  {showRecallGateSignals && recallPlan ? (
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
                    onClick={() => onViewTraceAndLogs(message)}
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
      ))}

      <div
        style={{
          marginTop: '8px',
          fontSize: '11px',
          color: 'var(--fg-muted)',
        }}
      >
        {(() => {
          const last = messages[messages.length - 1];
          const meta = last && last.meta ? last.meta : null;
          if (!meta) return null;
          const parts: string[] = [];
          const backend = meta.backend || meta.provider;
          if (backend) parts.push(`backend: ${backend}`);
          if (meta.model) parts.push(`model: ${meta.model}`);
          if (meta.failover && meta.failover.from && meta.failover.to) {
            parts.push(`failover: ${meta.failover.from} → ${meta.failover.to}`);
          }
          if (!parts.length) return null;
          return <span>— [{parts.join(' • ')}]</span>;
        })()}
      </div>
    </>
  );
}
