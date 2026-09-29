import type { AppInfo, OutcomeJson, RenderJson, StatusJson, TapeInfo } from '../api/types';
import { MODULE_IDS } from '../modules';

/** Gültiges 1x1-PNG (Base64 ohne data:-Präfix). */
const pngB64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

const tapeW12: TapeInfo = {
  id: 'w12',
  name: 'Weiß 12 mm',
  background: '#ffffff',
  ink: '#000000',
  material: 'Papier',
  transparent: false,
  dark: false,
  code_mode: 'normal',
  density: null,
  current: true,
};

const tapeT12: TapeInfo = {
  ...tapeW12,
  id: 't12',
  name: 'Transparent 12 mm',
  background: '#e8e8e8',
  transparent: true,
  current: false,
};

const appInfo: AppInfo = {
  version: '0.9.0',
  home_key: 'test-home',
  pid: 4242,
  port: 8712,
  accent: '#0078d4',
  profile: {
    model: 'P12',
    head_dots: 96,
    content_dots: 80,
    content_offset: 8,
    dots_per_mm: 8,
    leader_mm: 5,
    trailer_mm: 5,
    length_factor: 1,
    verified: [],
    experimental: [],
  },
  tape: tapeW12,
  screen_px_per_mm: null,
  ctrl_enter_only: false,
  language: 'de',
  theme: 'system',
  // Standard in den Tests: alle Module eingeschaltet (Tests der Modulschalter setzen `modules` selbst).
  modules: [...MODULE_IDS],
};

const statusJson: StatusJson = {
  report: {
    state: { state: 'bereit', transport: 'bt:COM5', last_error: null, leased: false },
    status: null,
    checked_at: '2026-09-27T12:00:00',
  },
  view: {
    chip: 'Bereit',
    role: 'success',
    title: 'Drucker bereit',
    detail: 'Zustand: bereit\nVerbindung: bt:COM5',
    tooltip: 'Drucker bereit',
  },
};

function renderJson(o: Partial<RenderJson> = {}): RenderJson {
  return {
    ok: true,
    title: 'Testlabel',
    preview: {
      design_png: pngB64,
      raster_png: pngB64,
      width: 200,
      height: 80,
      info: '25 mm · 1 Label',
      content_mm: 25,
      tape_mm: 35,
      labels: 1,
      jobs: 1,
      estimated: false,
      balance_text: '',
      decision: { allowed: true, needs_confirmation: false, reasons: [] },
      warnings: [],
    },
    errors: [],
    warnings: [],
    issues: [],
    fixes: [],
    font_size: 24,
    qr: null,
    values: null,
    shortened: [],
    notes: [],
    tape_reason: null,
    missing_secrets: [],
    editor: null,
    ...o,
  };
}

function outcomeJson(o: Partial<OutcomeJson> = {}): OutcomeJson {
  return {
    status: 'ok',
    warnings: [],
    reasons: [],
    history_id: 1,
    consumed_mm: 35,
    results: [],
    printer_status: null,
    error: null,
    queue_id: null,
    job_key: 'job-1',
    title: 'Testlabel',
    balance_text: '',
    ...o,
  };
}

export const fixtures = {
  appInfo,
  statusJson,
  tapes: { tapes: [tapeW12, tapeT12], current: 'w12' },
  renderJson,
  outcomeJson,
  pngB64,
};
