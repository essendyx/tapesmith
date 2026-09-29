/**
 * Kompakt (`/kompakt`, ohne App-Rahmen): kleines Schnelldruck-Fenster für den Hotkey. Derselbe
 * Fehldruckschutz wie Schnelldruck (`QuickGate`), aber ohne Optionen: immer 1 Label, Standard-
 * Schneidpause. Esc schließt das Fenster, ein erfolgreicher Druck schließt nach kurzer Zeit.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Caption1,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { useStatus } from '../../api/core';
import { useLabelRender } from '../../api/labels';
import type { TextSource } from '../../api/types';
import { formatCombo } from '../../commands/shortcuts';
import { TapePreview } from '../../components/TapePreview';
import { usePrint } from '../../components/usePrint';
import { closeWindow, setWindowTitle } from '../../platform';
import { gateReasonId } from '../Schnelldruck/gateMessages';
import { QuickGate } from '../Schnelldruck/quickGate';

const CLOSE_DELAY_MS = 800;

type Translate = (key: string, options?: Record<string, unknown>) => string;

const useStyles = makeStyles({
  root: {
    height: '100%',
    minHeight: '260px',
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalS,
    padding: tokens.spacingVerticalM,
    boxSizing: 'border-box',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  card: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalS,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow8,
    padding: tokens.spacingVerticalM,
    boxSizing: 'border-box',
  },
  hint: { color: tokens.colorNeutralForeground3 },
  textarea: {
    width: '100%',
    '& textarea': { fontSize: '20px', lineHeight: '1.3' },
  },
  message: { minHeight: '18px', color: tokens.colorPaletteDarkOrangeForeground1, fontSize: tokens.fontSizeBase200 },
  status: { color: tokens.colorNeutralForeground3 },
});

function trimmedLines(text: string): string[] {
  const lines = text.split('\n');
  while (lines.length > 0 && !(lines[lines.length - 1] ?? '').trim()) lines.pop();
  return lines;
}

function gateMessageText(t: Translate, reason: string): string {
  const id = gateReasonId(reason);
  if (!id) return '';
  return t(`gate.${id}`, { max: 3 });
}

export default function KompaktPage(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('kompakt');
  const tt: Translate = (key, opts) => String(t(key, opts));
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const gateRef = useRef<QuickGate>();
  if (!gateRef.current) gateRef.current = new QuickGate();
  const gate = gateRef.current;

  const [linesText, setLinesText] = useState('');
  const [revision, setRevision] = useState(0);
  const [message, setMessage] = useState('');
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    void setWindowTitle(tt('windowTitle'));
    textareaRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const linesArr = useMemo(() => trimmedLines(linesText), [linesText]);
  const hasContent = linesArr.some((l) => l.trim() !== '');
  const source = useMemo<TextSource | null>(() => (hasContent ? { kind: 'text', lines: linesArr } : null), [hasContent, linesArr]);
  const renderState = useLabelRender(source, undefined, { debounceMs: 150 });

  useEffect(() => {
    if (!source || renderState.loading || renderState.data === undefined) return;
    gate.previewReady(revision, renderState.data.ok);
  }, [gate, source, revision, renderState.loading, renderState.data]);

  const print = usePrint();
  useEffect(() => {
    gate.setBusy(print.busy);
  }, [gate, print.busy]);

  const status = useStatus().data;

  const markEdited = () => {
    gate.edited();
    setRevision(gate.revision);
    setMessage('');
  };

  const doPrint = async () => {
    if (!source) {
      setMessage(tt('gate.empty'));
      return;
    }
    const decision = gate.canPrint(linesText);
    if (decision.action !== 'print') {
      setMessage(gateMessageText(tt, decision.reason));
      return;
    }
    gate.markPrinted();
    setMessage('');
    const outcome = await print.run(source, { copies: 1, chain: false, cut_marks: true, cut_pause_s: null });
    if (outcome?.status === 'ok') {
      setMessage(tt('printed'));
      setClosing(true);
      setTimeout(() => {
        void closeWindow();
      }, CLOSE_DELAY_MS);
    }
  };

  const handleTextChange = (_e: unknown, data: { value: string }) => {
    setLinesText(data.value);
    markEdited();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      void closeWindow();
      return;
    }
    if (e.key !== 'Enter') return;
    const kind = e.shiftKey ? 'shift_enter' : e.ctrlKey || e.metaKey ? 'ctrl_enter' : 'enter';
    const decision = gate.key(kind, { text: linesText, autoRepeat: e.repeat });
    if (decision.action === 'newline') return;
    e.preventDefault();
    if (decision.action === 'print') void doPrint();
    else setMessage(gateMessageText(tt, decision.reason));
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    e.preventDefault();
    const el = e.currentTarget;
    const start = el.selectionStart ?? linesText.length;
    const end = el.selectionEnd ?? linesText.length;
    const before = linesText.slice(0, start);
    const after = linesText.slice(end);
    const currentLines = (before + after).split('\n').length;
    const result = gate.pasted(e.clipboardData.getData('text'), currentLines);
    if (result.error !== null) {
      setMessage(gateMessageText(tt, result.error));
      return;
    }
    setLinesText(before + result.lines.join('\n') + after);
    setRevision(gate.revision);
    setMessage(result.multiline ? tt('gate.review') : '');
  };

  const hint = tt('hint', { enter: formatCombo('Enter'), shift: formatCombo('Shift+Enter'), esc: formatCombo('Escape') });

  return (
    <div className={styles.root}>
      <h1 className="p12-visually-hidden">{tt('title')}</h1>
      <div className={styles.card}>
        <Caption1 className={styles.hint}>{hint}</Caption1>
        <Textarea
          ref={textareaRef}
          className={styles.textarea}
          value={linesText}
          onChange={handleTextChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={tt('field.placeholder')}
          aria-label={tt('field.label')}
          resize="none"
          disabled={closing}
          rows={Math.max(1, Math.min(3, linesText.split('\n').length))}
        />
        <TapePreview render={source ? renderState.data : undefined} loading={renderState.loading} compact />
        <div className={styles.message} role="status">
          {message}
        </div>
        {status ? <Caption1 className={styles.status}>{status.view.chip}</Caption1> : null}
      </div>
    </div>
  );
}
