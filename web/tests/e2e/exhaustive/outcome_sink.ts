import { mkdir, appendFile, writeFile, readFile } from 'node:fs/promises';
import path from 'node:path';
import type { OutcomeRecord } from './types';

function resolveOutputDir(): string {
  return process.env.EXHAUSTIVE_OUTPUT_DIR || path.resolve('output/playwright/exhaustive');
}

export class OutcomeSink {
  private readonly outputDir = resolveOutputDir();
  private readonly ndjsonPath = path.join(this.outputDir, 'outcomes.ndjson');
  private readonly summaryPath = path.join(this.outputDir, 'summary.json');
  private readonly rows: OutcomeRecord[] = [];

  async init(opts?: { truncate?: boolean }): Promise<void> {
    await mkdir(this.outputDir, { recursive: true });
    if (opts?.truncate !== false) {
      await writeFile(this.ndjsonPath, '', 'utf8');
    }
  }

  async loadResumeKeys(): Promise<Set<string>> {
    const seen = new Set<string>();
    try {
      const raw = await readFile(this.ndjsonPath, 'utf8');
      const lines = raw.split('\n').map((l) => l.trim()).filter(Boolean);
      for (const line of lines) {
        try {
          const row = JSON.parse(line) as OutcomeRecord;
          if (!row || (row.status !== 'ok' && row.status !== 'skipped')) continue;
          if (!row.surface_key || !row.control_fingerprint) continue;
          seen.add(`${row.surface_key}|${row.control_fingerprint}`);
        } catch {
          // ignore malformed lines
        }
      }
    } catch {
      // no previous run artifact
    }
    return seen;
  }

  async add(row: OutcomeRecord): Promise<void> {
    this.rows.push(row);
    await appendFile(this.ndjsonPath, `${JSON.stringify(row)}\n`, 'utf8');
  }

  async finalize(run: Record<string, unknown> = {}): Promise<void> {
    const ok = this.rows.filter((r) => r.status === 'ok').length;
    const failed = this.rows.filter((r) => r.status === 'failed').length;
    const skipped = this.rows.filter((r) => r.status === 'skipped').length;

    const bySurface = this.rows.reduce<Record<string, { ok: number; failed: number; skipped: number }>>(
      (acc, row) => {
        const key = row.surface;
        if (!acc[key]) acc[key] = { ok: 0, failed: 0, skipped: 0 };
        acc[key][row.status] += 1;
        return acc;
      },
      {}
    );

    await writeFile(
      this.summaryPath,
      JSON.stringify(
        {
          generated_at: new Date().toISOString(),
          run,
          totals: {
            total: this.rows.length,
            ok,
            failed,
            skipped,
          },
          by_surface: bySurface,
        },
        null,
        2
      ),
      'utf8'
    );
  }
}
