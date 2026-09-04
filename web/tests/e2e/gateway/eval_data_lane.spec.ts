/**
 * Eval data lane surfaces: the Synthetic Lab renders the grounded_qa provider and the
 * grounding/curation counts of a real completed run, and the Reranker config surface
 * offers the LiteLLM gateway provider with its catalog aliases.
 *
 * Real app, real API, real persisted runs. No request interception.
 */
import fs from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import type { SyntheticRun, SyntheticRunsResponse } from '../../../src/types/generated';

function writeSyntheticRun(root: string, run: SyntheticRun, tripletsBytes: Buffer): string {
  const runDir = path.join(root, 'data', 'synthetic_runs', run.run_id);
  const artifactsDir = path.join(runDir, 'artifacts');
  fs.mkdirSync(artifactsDir, { recursive: true });
  fs.writeFileSync(path.join(artifactsDir, 'triplets.jsonl'), tripletsBytes);
  fs.writeFileSync(path.join(runDir, 'run.json'), JSON.stringify(run, null, 2), 'utf8');
  return runDir;
}


const API_BASE = process.env.GATEWAY_API_BASE_URL ?? 'http://127.0.0.1:58012/api';
const CORPUS_ID = process.env.GATEWAY_E2E_CORPUS_ID ?? 'epstein-files-1';

test.describe('eval data lane surfaces', () => {
  test('Synthetic Lab shows the grounded_qa provider and the grounding counts of the latest completed run', async ({ page }) => {
    const runs = await page.request.get(`${API_BASE}/synthetic/runs?corpus_id=${encodeURIComponent(CORPUS_ID)}&limit=20`);
    expect(runs.ok(), `GET /api/synthetic/runs -> ${runs.status()}`).toBeTruthy();
    const payload = (await runs.json()) as SyntheticRunsResponse;
    const completedMeta = payload.runs.find((run) => run.status === 'completed' && run.provider === 'grounded_qa');
    // Precondition, not a skip: this spec proves the rendered panel against a real completed run.
    expect(completedMeta, `no completed grounded_qa run for ${CORPUS_ID}; run the Synthetic Lab first`).toBeTruthy();
    const detail = await page.request.get(`${API_BASE}/synthetic/run/${encodeURIComponent(completedMeta!.run_id)}`);
    expect(detail.ok(), `GET /api/synthetic/run/{id} -> ${detail.status()}`).toBeTruthy();
    const run = (await detail.json()) as SyntheticRun;
    const summary = run.summary;
    expect(summary.items_generated).toBeGreaterThan(0);
    expect(summary.items_curated_out).toBeGreaterThan(0);

    await page.goto(`rag?subtab=synthetic&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    const providerSelect = page.locator('select').filter({ has: page.locator('option[value="grounded_qa"]') }).first();
    await expect(providerSelect).toBeVisible({ timeout: 60_000 });
    await expect(providerSelect).toHaveValue('grounded_qa');
    await expect(providerSelect.locator('option')).toHaveCount(1);

    await page.getByText(run.run_id, { exact: true }).first().click();
    const grounding = page.getByTestId('synthetic-grounding-summary');
    await expect(grounding).toBeVisible({ timeout: 30_000 });
    const text = (await grounding.innerText()).replace(/\s+/g, ' ');
    // The panel must show exactly the persisted run summary, not defaults.
    expect(text).toContain(`sources=${summary.sources_used}`);
    expect(text).toContain(`generated=${summary.items_generated}`);
    expect(text).toContain(`ungrounded=${summary.items_rejected_ungrounded}`);
    expect(text).toContain(`malformed=${summary.items_rejected_malformed}`);
    expect(text).toContain(`judged=${summary.items_curated_in}`);
    expect(text).toContain(`kept=${summary.items_curated_out}`);
    expect(text).toContain(`triplets=${summary.triplets_mined}`);
    expect(text).not.toContain('Degraded Run');
  });

  test('Reranker config offers the LiteLLM gateway provider with catalog aliases', async ({ page }) => {
    await page.goto(`rag?subtab=reranker&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    const cloudMode = page.getByTestId('reranker-mode-cloud');
    await expect(cloudMode).toBeVisible({ timeout: 60_000 });
    await cloudMode.click();
    const providerSelect = page.getByTestId('reranker-cloud-provider');
    await expect(providerSelect).toBeVisible({ timeout: 60_000 });
    await expect(providerSelect.locator('option[value="litellm"]')).toHaveCount(1);
    await providerSelect.selectOption('litellm');
    await expect(providerSelect).toHaveValue('litellm');
    const modelSelect = page.locator('select').filter({ has: page.locator('option[value="openai.gpt-5.6-luna"]') }).first();
    await expect(modelSelect).toBeVisible();
    await expect(page.getByText('LITELLM_API_KEY')).toBeVisible();
  });

  test('Training Studio surfaces the server failure semantics when the triplets file is corrupt', async ({ page }) => {
    // Real corpus, real config, real corrupt artifact: the server answers 409 with repair guidance
    // and the studio must show that instead of a generic message.
    const stamp = Date.now();
    const corpusId = `e2e-mine-corrupt-${stamp}`;
    const root = process.cwd();
    const corpusDir = path.join(root, 'output', 'playwright', `corpus-${stamp}`);
    const tripletsRel = path.posix.join('output', 'playwright', `corrupt-triplets-${stamp}.jsonl`);
    fs.mkdirSync(corpusDir, { recursive: true });
    fs.writeFileSync(path.join(root, tripletsRel), '{"query": "broken\n', 'utf8');
    const created = await page.request.post(`${API_BASE}/corpora`, {
      data: { corpus_id: corpusId, name: corpusId, path: corpusDir },
    });
    expect(created.ok(), `POST /api/corpora -> ${created.status()}`).toBeTruthy();
    try {
      const patched = await page.request.patch(`${API_BASE}/config/training?corpus_id=${encodeURIComponent(corpusId)}`, {
        data: { tribrid_triplets_path: tripletsRel, triplets_mine_mode: 'append' },
      });
      expect(patched.ok(), `PATCH /api/config/training -> ${patched.status()}`).toBeTruthy();

      await page.goto(`rag?subtab=learning-reranker&corpus=${encodeURIComponent(corpusId)}`, { waitUntil: 'domcontentloaded' });
      const mine = page.getByRole('button', { name: /mine triplets/i }).first();
      await expect(mine).toBeVisible({ timeout: 60_000 });
      await expect(mine).toBeEnabled();
      await mine.click();
      await expect(page.getByText(/Triplet mining failed \(HTTP 409\)/)).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText(/corrupt/i).first()).toBeVisible();
    } finally {
      await page.request.delete(`${API_BASE}/corpora/${encodeURIComponent(corpusId)}`);
      fs.rmSync(corpusDir, { recursive: true, force: true });
      fs.rmSync(path.join(root, tripletsRel), { force: true });
      // the server keeps an flock sibling (".<name>.lock") next to every triplets artifact it touches
      fs.rmSync(path.join(root, path.posix.dirname(tripletsRel), `.${path.posix.basename(tripletsRel)}.lock`), { force: true });
    }
  });

  test('Synthetic Lab surfaces the publish boundary (corrupt artifact -> 409 detail) and lists unreadable runs', async ({ page }) => {
    // Real corpus, real run directories on disk, real publish: the server refuses a byte-corrupt
    // triplets artifact with a 409 and the lab must show that detail, not "status code 409".
    // A run.json written by the replaced provider must be listed as unreadable, not hidden.
    const stamp = Date.now();
    const corpusId = `e2e-synth-publish-${stamp}`;
    const root = process.cwd();
    const corpusDir = path.join(root, 'output', 'playwright', `corpus-${stamp}`);
    const tripletsRel = path.posix.join('output', 'playwright', `live-triplets-${stamp}.jsonl`);
    const liveRow = '{"query":"Which buoy reported the largest salinity drift in March?","positive":"a.txt","negative":"b.txt"}\n';
    fs.mkdirSync(corpusDir, { recursive: true });
    fs.writeFileSync(path.join(root, tripletsRel), liveRow, 'utf8');
    const startedAt = new Date(stamp).toISOString();
    const corruptRunId = `${corpusId}__corrupt_artifact`;
    const runDirs: string[] = [];
    const corruptRun: SyntheticRun = {
      run_id: corruptRunId,
      corpus_id: corpusId,
      status: 'completed',
      started_at: startedAt,
      completed_at: startedAt,
      provider: 'grounded_qa',
      recipe: 'full_stack',
      config_snapshot: {},
      config: {},
      request: {
        corpus_id: corpusId,
        provider: 'grounded_qa',
        recipe: 'full_stack',
        generator_model: 'litellm:openai.gpt-5.6-luna',
        judge_model: 'litellm:openai.gpt-5.6-luna',
      },
      artifacts: [
        {
          kind: 'triplets_jsonl',
          path: path.join(root, 'data', 'synthetic_runs', corruptRunId, 'artifacts', 'triplets.jsonl'),
          bytes: 0,
          created_at: startedAt,
        },
      ],
      summary: {
        sources_used: 1,
        items_generated: 1,
        items_curated_in: 1,
        items_curated_out: 1,
        triplets_mined: 1,
        quality_top1_accuracy: 0.8,
        quality_topk_accuracy: 0.9,
        quality_mrr: 0.85,
        quality_sample_size: 50,
        quality_gate_threshold: 0.4,
        quality_gate_passed: true,
        quality_failure_reason: null,
      },
      error: null,
    };
    runDirs.push(writeSyntheticRun(root, corruptRun, Buffer.concat([Buffer.from(liveRow, 'utf8'), Buffer.from([0xff, 0xfe, 0x0a])])));
    const staleRunId = `${corpusId}__stale_provider`;
    const stale = JSON.parse(JSON.stringify(corruptRun)) as Record<string, unknown>;
    stale.run_id = staleRunId;
    stale.provider = 'synthetic_data_kit';
    (stale.request as Record<string, unknown>).provider = 'synthetic_data_kit';
    runDirs.push(writeSyntheticRun(root, stale as unknown as SyntheticRun, Buffer.from(liveRow, 'utf8')));

    const created = await page.request.post(`${API_BASE}/corpora`, {
      data: { corpus_id: corpusId, name: corpusId, path: corpusDir },
    });
    expect(created.ok(), `POST /api/corpora -> ${created.status()}`).toBeTruthy();
    try {
      const patched = await page.request.patch(`${API_BASE}/config/training?corpus_id=${encodeURIComponent(corpusId)}`, {
        data: { tribrid_triplets_path: tripletsRel },
      });
      expect(patched.ok(), `PATCH /api/config/training -> ${patched.status()}`).toBeTruthy();

      await page.goto(`rag?subtab=synthetic&corpus=${encodeURIComponent(corpusId)}`, { waitUntil: 'domcontentloaded' });
      const unreadable = page.getByTestId('synthetic-unreadable-runs');
      await expect(unreadable).toBeVisible({ timeout: 60_000 });
      await expect(unreadable).toContainText(staleRunId);
      await expect(unreadable).toContainText(/provider/i);

      await page.getByText(corruptRunId, { exact: true }).first().click();
      const publish = page.getByTestId('synthetic-publish-triplets_jsonl');
      await expect(publish).toBeVisible({ timeout: 30_000 });
      await expect(publish).toBeEnabled();
      await publish.click();

      const notifications = page.getByTestId('synthetic-lab-notifications');
      await expect(notifications).toContainText(/Publish failed \(HTTP 409\)/, { timeout: 30_000 });
      await expect(notifications).toContainText(/TRIPLETS_ARTIFACT_CORRUPT/);
      // the refused publish left the live triplets file exactly as it was
      expect(fs.readFileSync(path.join(root, tripletsRel), 'utf8')).toBe(liveRow);
    } finally {
      await page.request.delete(`${API_BASE}/corpora/${encodeURIComponent(corpusId)}`);
      for (const dir of runDirs) fs.rmSync(dir, { recursive: true, force: true });
      fs.rmSync(corpusDir, { recursive: true, force: true });
      fs.rmSync(path.join(root, tripletsRel), { force: true });
      fs.rmSync(path.join(root, path.posix.dirname(tripletsRel), `.${path.posix.basename(tripletsRel)}.lock`), { force: true });
    }
  });
});
