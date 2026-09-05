import { execFileSync } from 'node:child_process';
import { expect, test } from '@playwright/test';
import type { Entity, GraphEntitySourcesResponse } from '../../../src/types/generated';
import { API_BASE, activateCorpusInBrowser } from './corpus_fixture';

const CORPUS = 'nasa-apollo-11';

function sourceFixture(operation: 'create' | 'advance' | 'delete', fixture?: Record<string, string>): string {
  return execFileSync(process.env.RAGWELD_TEST_PYTHON || '.venv/bin/python', [
    'web/tests/e2e/exhaustive/graph_sources_fixture.py', operation, API_BASE,
    ...(fixture ? [JSON.stringify(fixture)] : []),
  ], { cwd: process.cwd(), encoding: 'utf8', timeout: 30_000 });
}

test('Graph Explorer opens the actual entity mention in the document viewer', async ({ page, request, baseURL }) => {
  const entitiesResponse = await request.get(`${API_BASE}/graph/${CORPUS}/entities`, { params: { q: 'fuel', limit: 100 } });
  expect(entitiesResponse.ok()).toBeTruthy();
  const entities = await entitiesResponse.json() as Entity[];
  const entity = entities.find((item) => /fuel\s*tank\s*2/i.test(item.name));
  expect(entity, 'the indexed Apollo corpus must contain Fuel Tank2').toBeTruthy();
  const sourceResponse = await request.get(`${API_BASE}/graph/${CORPUS}/entity/sources`, { params: { entity_id: entity!.entity_id } });
  expect(sourceResponse.ok()).toBeTruthy();
  const sourcePage = await sourceResponse.json() as GraphEntitySourcesResponse;
  const source = sourcePage.sources[0];
  expect(source, 'Fuel Tank2 must retain its actual FROM_CHUNK mention').toBeTruthy();

  await activateCorpusInBrowser(page, CORPUS);
  await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname === `/api/graph/${CORPUS}/subgraph`),
    page.goto(new URL(`rag?subtab=graph&corpus=${CORPUS}`, baseURL).toString()),
  ]);
  await expect(page.getByTestId('graph-stats')).toBeVisible({ timeout: 60_000 });
  await page.getByTestId('graph-entity-search').fill(entity!.name);
  await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname === `/api/graph/${CORPUS}/subgraph`
      && new URL(response.url()).searchParams.get('q') === entity!.name),
    page.getByTestId('graph-search-btn').click(),
  ]);
  await page.getByTestId(`graph-entity-${entity!.entity_id}`).click();
  await expect(page.getByTestId('graph-viz-panel')).toBeVisible();
  const mentions = page.getByTestId('graph-entity-sources');
  await expect(mentions).toContainText('A mention alone does not verify a relationship.');
  await expect(mentions.getByTestId('graph-source-open').first()).toContainText(source.file_path);
  await expect(mentions).toContainText(source.content.slice(0, 80));
  await mentions.getByTestId('graph-source-open').first().click();
  const viewer = page.getByTestId('document-viewer');
  await expect(viewer).toBeVisible();
  await expect(viewer.getByTestId('document-viewer-title')).toHaveAttribute('title', source.file_path);
  if (source.file_path.toLowerCase().endsWith('.pdf')) {
    expect(source.provenance?.page_start, 'the indexed PDF mention must carry a captured page').toBeGreaterThan(0);
    await expect(viewer.getByTestId('document-page-indicator')).toContainText(`p. ${source.provenance!.page_start} /`, { timeout: 30_000 });
    await expect.poll(() => viewer.getByTestId('document-page-image').evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    await expect(viewer.getByTestId('document-cited-text')).toContainText(source.content.slice(0, 80));
    expect(await viewer.getByTestId('document-region').count()).toBeGreaterThan(0);
  } else {
    await expect(viewer.getByTestId('document-text-view')).toBeVisible({ timeout: 30_000 });
    await expect(viewer.getByTestId('document-highlight-line').first()).toHaveAttribute('data-line', String(source.start_line));
    const expected = source.content.split('\n').find((line) => line.trim().length > 8)!.trim();
    await expect(viewer.getByTestId('document-text-view')).toContainText(expected);
  }
  await page.getByTestId('graph-view-table').click();
  await expect(page.getByTestId('graph-entity-sources')).toHaveCount(1);
  await expect(page.getByTestId('graph-relationships-table')).toContainText('Edge-specific evidence not recorded');
});

test('a changed manifest removes stale source actions until the operator reloads', async ({ page, baseURL }) => {
  const fixture = JSON.parse(sourceFixture('create')) as Record<string, string>;
  try {
    await activateCorpusInBrowser(page, fixture.corpus);
    await Promise.all([
      page.waitForResponse((response) => new URL(response.url()).pathname === `/api/graph/${fixture.corpus}/subgraph`),
      page.goto(new URL(`rag?subtab=graph&corpus=${fixture.corpus}`, baseURL).toString()),
    ]);
    await page.getByTestId(`graph-entity-${fixture.entity}`).click();
    const mentions = page.getByTestId('graph-entity-sources');
    await expect(mentions.getByTestId('graph-source-open')).toHaveCount(25);
    sourceFixture('advance', fixture);
    await mentions.getByRole('button', { name: 'Load more sources' }).click();
    await expect(mentions.getByRole('alert')).toContainText('graph generation changed');
    await expect(mentions.getByTestId('graph-source-open')).toHaveCount(0);
    await mentions.getByRole('button', { name: 'Reload sources' }).click();
    await expect(mentions.getByTestId('graph-source-open')).toHaveCount(25);
    await mentions.getByRole('button', { name: 'Load more sources' }).click();
    await expect(mentions.getByTestId('graph-source-open')).toHaveCount(26);
    await expect(mentions.getByRole('button', { name: 'Load more sources' })).toHaveCount(0);
  } finally {
    sourceFixture('delete', fixture);
  }
});
