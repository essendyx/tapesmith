/** Entprellte Eingabe: lokaler Entwurf, Senden nach `delay` ms, Serverwert übernimmt nur ohne offene Eingabe. */
import { useCallback, useEffect, useRef, useState } from 'react';

export function useDraft<T>(value: T, onCommit: (v: T) => void, delay = 250): [T, (v: T) => void, () => void] {
  const [draft, setDraft] = useState<T>(value);
  const pending = useRef<{ value: T } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;

  useEffect(() => {
    if (!pending.current) setDraft(value);
  }, [value]);

  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const p = pending.current;
    pending.current = null;
    if (p) commitRef.current(p.value);
  }, []);

  const change = useCallback(
    (v: T) => {
      setDraft(v);
      pending.current = { value: v };
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(flush, delay);
    },
    [delay, flush],
  );

  // offene Eingabe beim Verlassen noch senden
  useEffect(() => flush, [flush]);

  return [draft, change, flush];
}
