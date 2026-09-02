// Staged commit model (T6) invariant: merely VISITING a config surface must stage nothing.
// The flip made `useConfigField` stage instead of debounce-PATCH, so a component that "self-heals"
// config in a mount effect (setX(normalizedValue)) would, under the new model, stage a permanent
// edit the operator never made -- the footer would read "Apply 1 change" on a page they only
// opened, and Apply would PUT a mutation nobody intended (worst on PathsSubtab, whose fields are
// the live DB connection endpoints). This drives every config-consuming surface with NO
// interaction and asserts the dirty count is exactly 0.
import { expect, test } from '@playwright/test';

const CORPUS = process.env.CS_CORPUS ?? 'nasa-apollo-11';

const SURFACES = [
  'rag?subtab=indexing&component=chunking',
  'rag?subtab=retrieval',
  'rag?subtab=reranker',
  'rag?subtab=data-quality',
  'chat?subtab=settings',
  'infrastructure?subtab=paths',
  'grafana?subtab=config',
  'admin?subtab=general',
];

for (const surface of SURFACES) {
  test(`visiting ${surface} stages nothing (dirty count stays 0)`, async ({ page, baseURL }) => {
    const configWrites: string[] = [];
    page.on('request', (req) => {
      const url = req.url();
      if ((req.method() === 'PATCH' || req.method() === 'PUT') && /\/api\/config/.test(url)) {
        configWrites.push(`${req.method()} ${url}`);
      }
    });

    await page.goto(new URL(`${surface}&corpus=${CORPUS}`, baseURL).toString());
    await page.waitForSelector('#save-btn', { timeout: 60_000 });
    // Give mount effects time to run (the old debounce window was 300ms; staging is synchronous).
    await page.waitForTimeout(1500);

    const count = await page.getByTestId('apply-changes').getAttribute('data-dirty-count');
    expect(count, `${surface} shows a phantom staged change`).toBe('0');
    // And nothing was written to the server just by visiting.
    expect(configWrites, `${surface} wrote config on mount: ${configWrites.join(' | ')}`).toEqual([]);
  });
}
