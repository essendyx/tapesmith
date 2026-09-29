/** Endpunkte und Bildaufbereitung der Seite SnScan. */
import { apiPost } from '../../api/client';
import { i18n } from '../../i18n';
import type { CodescanResultJson } from './types';

const MAX_LONG_EDGE = 2400;
const JPEG_QUALITY = 0.9;

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error(i18n.t('snscan:errors.fileUnreadable')));
    reader.readAsDataURL(file);
  });
}

function loadImage(dataUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(i18n.t('snscan:errors.imageUnreadable')));
    img.src = dataUrl;
  });
}

function toBase64(dataUrl: string): string {
  const comma = dataUrl.indexOf(',');
  return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
}

/**
 * Liest die Datei ein und liefert reines Base64 (ohne data:-Präfix). Liegt die lange Kante über
 * MAX_LONG_EDGE, wird vorher im Browser über ein Canvas verkleinert (JPEG, Qualität 0.9).
 *
 * Eigene Exportfunktion, damit Tests sie ersetzen können (vi.mock dieses Moduls): jsdom lädt
 * Bilder nicht wirklich, ein echter Aufruf würde im Test nie auflösen.
 */
export async function prepareImage(file: File): Promise<string> {
  const dataUrl = await readAsDataUrl(file);
  const img = await loadImage(dataUrl);
  const width = img.naturalWidth || img.width;
  const height = img.naturalHeight || img.height;
  const longEdge = Math.max(width, height);
  if (!longEdge || longEdge <= MAX_LONG_EDGE) return toBase64(dataUrl);

  const scale = MAX_LONG_EDGE / longEdge;
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const ctx = canvas.getContext('2d');
  if (!ctx) return toBase64(dataUrl);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return toBase64(canvas.toDataURL('image/jpeg', JPEG_QUALITY));
}

export function postCodescan(imageB64: string, name?: string): Promise<CodescanResultJson> {
  return apiPost<CodescanResultJson>('/api/v1/homelab/codescan', { image_b64: imageB64, name });
}
