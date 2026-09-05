import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { TraceExternalLinks } from '../../src/components/Observability/TraceExternalLinks';

// Render the actual shared Chat/Eval component against the real API. This fixture
// supplies trace identities only; it never intercepts or fabricates HTTP responses.
const params = new URLSearchParams(window.location.search);
const ids = params.getAll('trace');
const traceBase = params.get('traceBase')!;

function TraceLinkAcceptance() {
  const [index, setIndex] = useState(0);
  const traceId = ids[index];
  return <main>
    <h1>Trace link acceptance</h1>
    <div data-testid="fixture-trace-id">{traceId}</div>
    {ids.length > 1 ? <button onClick={() => setIndex((current) => (current + 1) % ids.length)}>Next trace</button> : null}
    <TraceExternalLinks traceId={traceId} links={[{
      kind: 'langfuse', label: 'Langfuse trace', url: `${traceBase}/${traceId}`,
    }]} />
  </main>;
}

createRoot(document.getElementById('root')!).render(<TraceLinkAcceptance />);
