/** Typen der Seite SnScan. */

export interface CodeHitJson {
  text: string;
  format: string;
  position: [number, number, number, number] | null;
}

export interface SerialCandidateJson {
  serial: string;
  score: number;
  reason: string;
  text: string;
  format: string;
}

export interface CodescanResultJson {
  width: number;
  height: number;
  hits: CodeHitJson[];
  candidates: SerialCandidateJson[];
  best: string | null;
  shortened: string | null;
}
