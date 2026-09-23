// Tips shown in the assistant bubble while an answer is being prepared and no model thinking
// is on screen. Every tip describes the product as it is: a tip that names a removed feature
// (VS Code citation links, a "fast mode", provider failover, pgvector) teaches the operator
// something false, so tips are checked against the code when features change.

export type ChatWaitingTipCategory = 'retrieval' | 'answers' | 'feedback' | 'quality' | 'corpus' | 'chat';

export type ChatWaitingTip = {
  tip: string;
  category: ChatWaitingTipCategory;
};

export const CHAT_WAITING_TIP_CATEGORY_LABELS: Record<ChatWaitingTipCategory, string> = {
  retrieval: 'Retrieval',
  answers: 'Answers',
  feedback: 'Feedback',
  quality: 'Quality',
  corpus: 'Corpus',
  chat: 'Chat',
};

export const CHAT_WAITING_TIPS: readonly ChatWaitingTip[] = [
  // Retrieval
  { tip: 'Every question runs up to three retrieval legs: dense vectors, sparse keyword search, and the knowledge graph. Their results are fused into one ranked list.', category: 'retrieval' },
  { tip: 'Sparse search catches exact names, codes and IDs; dense search catches meaning. Keeping both legs on covers either kind of question.', category: 'retrieval' },
  { tip: 'The graph leg expands from the entities your question matches to related ones, so it can surface evidence that shares no words with the question.', category: 'retrieval' },
  { tip: 'Turn the vector, sparse and graph legs on or off from the sources menu to see what each one contributes to an answer.', category: 'retrieval' },
  { tip: 'Top-K sets how many results this conversation retrieves. Raise it for broad questions, lower it for pinpoint ones.', category: 'retrieval' },
  { tip: 'When a reranker is configured, it re-orders the fused results before the model sees them.', category: 'retrieval' },
  { tip: 'Specific questions retrieve better: "Which flights were booked in October 2017?" beats "tell me about flights".', category: 'retrieval' },
  { tip: 'If an answer misses, rephrase with the words the documents would use. Different terms surface different passages.', category: 'retrieval' },

  // Answers
  { tip: 'Each answer lists its sources. Open one to see the cited passage in the document viewer in the Dock.', category: 'answers' },
  { tip: 'Check the cited passage before relying on a claim: the sources show exactly what the model was given.', category: 'answers' },
  { tip: 'Web search can be turned on per message. A web-grounded answer is marked and lists only citations that were validated.', category: 'answers' },
  { tip: 'Attach images to a message to ask a vision-capable model about them.', category: 'answers' },
  { tip: 'With "Show model thinking" on in Chat settings, models that share their reasoning show it here while they work.', category: 'answers' },

  // Feedback
  { tip: 'Helpful and Not helpful on an answer are recorded against its run and mined into training triplets for the learning reranker.', category: 'feedback' },
  { tip: 'The Trace button under an answer shows how that run retrieved and ranked its sources.', category: 'feedback' },

  // Quality
  { tip: 'Eval datasets are your benchmark: add the questions that matter and re-run them to see whether a settings change helped or hurt.', category: 'quality' },
  { tip: 'MRR measures how high the first relevant result ranks; compare eval runs to catch retrieval regressions early.', category: 'quality' },

  // Corpus
  { tip: 'Each corpus keeps its own configuration, so retrieval can be tuned per corpus.', category: 'corpus' },
  { tip: 'Re-index a corpus after its files change so answers reflect the current content.', category: 'corpus' },
  { tip: 'Chunk summaries give the model a quick, high-level view of long files and sections.', category: 'corpus' },
  { tip: 'Recall indexes your past conversations as a source, so later questions can draw on earlier answers.', category: 'corpus' },

  // Chat
  { tip: 'Press Ctrl+Enter to send a message.', category: 'chat' },
  { tip: 'Stop cancels a running answer. Nothing from a cancelled exchange is saved to the conversation.', category: 'chat' },
  { tip: 'Pick any model from the gateway catalog in the model picker; the choice sticks to this conversation.', category: 'chat' },
  { tip: 'Past conversations stay in the history sidebar; New chat starts a clean one.', category: 'chat' },
];

/** Fisher-Yates over a copy, with the random source injectable for tests. */
export function shuffleTips<T>(tips: readonly T[], random: () => number = Math.random): T[] {
  const shuffled = [...tips];
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

/** How long a tip stays up: reading time at ~200 words per minute plus a beat, 4 to 9 seconds. */
export function tipDurationMs(tip: string): number {
  const words = tip.trim().split(/\s+/).filter(Boolean).length;
  const readingMs = (words / 200) * 60_000;
  return Math.max(4_000, Math.min(readingMs + 1_500, 9_000));
}
