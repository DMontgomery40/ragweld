/**
 * Tooltip registry
 *
 * Centralizes access to tooltip definitions for TooltipIcon + Glossary.
 *
 * NOTE: We still source definitions from the legacy tooltip file, but it no
 * longer attaches itself to `window.*` globals.
 */
import {
  buildTooltipMap as buildLegacyTooltipMap,
  tooltipMap as legacyTooltipMap,
} from '../modules/_archived/tooltips.js';

export type TooltipMap = Record<string, string>;

export function buildTooltipMap(): TooltipMap {
  try {
    return buildLegacyTooltipMap();
  } catch {
    return {};
  }
}

// Eagerly build a single in-memory map for the app session.
export const tooltipMap: TooltipMap = legacyTooltipMap || buildTooltipMap();

