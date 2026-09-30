/**
 * Schnelldruck: Startseite, schnellster Weg zum
 * Label. Vorschau und Druck kommen immer vom Server; der Fehldruckschutz entscheidet lokal über
 * `QuickGate` (Port von `quickgate.py`), 1:1 auch in `../Kompakt` genutzt.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Button,
  Caption1,
  Dropdown,
  Field,
  Input,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Option,
  SpinButton,
  Textarea,
  ToggleButton,
  Tooltip,
  makeStyles,
  mergeClasses,
  tokens,
  type SpinButtonOnChangeData,
} from '@fluentui/react-components';
import { ArrowExport20Regular, ChevronDown20Regular, ChevronUp20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { apiGet, apiPost } from '../../api/client';
import { qk, useAppInfo, useFonts } from '../../api/core';
import { exportLabel, useLabelRender } from '../../api/labels';
import { DEFAULT_PRINT_OPTIONS, type FixJson, type PrintOptions, type TextSource } from '../../api/types';
import { formatCombo } from '../../commands/shortcuts';
import { useRegisterCommands } from '../../commands/CommandProvider';
import { PageHeader } from '../../components/PageHeader';
import { PrintOptionsBar } from '../../components/PrintOptionsBar';
import { Section } from '../../components/Section';
import { TapePreview } from '../../components/TapePreview';
import { usePrint } from '../../components/usePrint';
import { WarningList } from '../../components/WarningList';
import { TEXT_SIZE_AUTO, TextSizeSelect } from '../../components/TextSizeSelect';
import { useNotify } from '../../components/NotifyProvider';
import { gateReasonId } from './gateMessages';
import { MAX_LINES, QuickGate } from './quickGate';

const PRECONNECT_INTERVAL_S = 30;
const EXAMPLE_TEXT = 'pmx10 SSD-1 · SN 274913';

type Align = 'left' | 'center' | 'right';
type Translate = (key: string, options?: Record<string, unknown>) => string;

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, maxWidth: '760px' },
  textarea: {
    width: '100%',
    '& textarea': { fontSize: '28px', lineHeight: '1.3' },
  },
  // Statuszeile bleibt als Live-Region im Baum, nimmt leer aber keinen Platz ein (keine Lücke unter dem Feld).
  message: {
    color: tokens.colorPaletteDarkOrangeForeground1,
    ':empty': { marginTop: `calc(-1 * ${tokens.spacingVerticalL})` },
  },
  example: { color: tokens.colorNeutralForeground3 },
  chips: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalXS },
  fixes: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalXS },
  optionsToggle: { alignSelf: 'flex-start' },
  optionsPanel: {
    display: 'grid',
    gridTemplateRows: '0fr',
    opacity: 0,
    overflow: 'hidden',
    transitionProperty: 'grid-template-rows, opacity',
    transitionDuration: tokens.durationSlow,
    transitionTimingFunction: tokens.curveEasyEase,
  },
  optionsPanelOpen: { gridTemplateRows: '1fr', opacity: 1 },
  optionsInner: {
    minHeight: 0,
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalM,
    paddingTop: tokens.spacingVerticalXS,
  },
  optionsRow: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalL, rowGap: tokens.spacingVerticalM },
  alignGroup: { display: 'flex', columnGap: tokens.spacingHorizontalXXS },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center', flexWrap: 'wrap' },
  qrInfo: { color: tokens.colorNeutralForeground3 },
});

function trimmedLines(text: string): string[] {
  const lines = text.split('\n');
  while (lines.length > 0 && !(lines[lines.length - 1] ?? '').trim()) lines.pop();
  return lines;
}

/** „3 Kopien“, „1 Label als Kette“ oder „3 Labels als Kette“. */
function amountText(t: Translate, copies: number, chain: boolean): string {
  if (chain) return copies > 1 ? t('amount.chainMany', { count: copies }) : t('amount.chainOne');
  return t('amount.copies', { count: copies });
}

function printActionLabel(t: Translate, copies: number, chain: boolean): string {
  if (copies === 1 && !chain) return t('printAction.one');
  return t('printAction.amount', { amount: amountText(t, copies, chain) });
}

/** Einziger Tastatur-Hinweis (Field-Hinweis, Kürzel sprachabhängig über `formatCombo`). */
function fieldHint(t: Translate, ctrlEnterOnly: boolean, copies: number, chain: boolean): string {
  const plain = copies === 1 && !chain;
  const enter = formatCombo('Enter');
  const shift = formatCombo('Shift+Enter');
  const ctrl = formatCombo('Ctrl+Enter');
  if (ctrlEnterOnly) {
    return plain
      ? t('field.hint.ctrlOnlyPlain', { ctrl, enter })
      : t('field.hint.ctrlOnlyAmount', { ctrl, enter, amount: amountText(t, copies, chain) });
  }
  return plain
    ? t('field.hint.plain', { enter, shift })
    : t('field.hint.plainAmount', { enter, ctrl, shift, amount: amountText(t, copies, chain) });
}

function gateMessageText(t: Translate, reason: string): string {
  const id = gateReasonId(reason);
  if (!id) return '';
  return t(`gate.${id}`, { max: MAX_LINES });
}

export default function SchnelldruckPage(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('schnelldruck');
  const tt: Translate = (key, opts) => String(t(key, opts));
  const notify = useNotify();
  const [params] = useSearchParams();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const gateRef = useRef<QuickGate>();
  if (!gateRef.current) gateRef.current = new QuickGate();
  const gate = gateRef.current;

  const ALIGNS = useMemo(
    () => [
      { value: 'left' as const, label: tt('options.alignLeft') },
      { value: 'center' as const, label: tt('options.alignCenter') },
      { value: 'right' as const, label: tt('options.alignRight') },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t],
  );

  const [linesText, setLinesText] = useState('');
  const [font, setFont] = useState<string | undefined>(undefined);
  /** Schriftgröße: 'auto' oder feste Texthöhe in mm als Text (kanonisch wie im Backend). */
  const [textHeight, setTextHeight] = useState<string>(TEXT_SIZE_AUTO);
  const [align, setAlign] = useState<Align>('left');
  const [maxLengthMm, setMaxLengthMm] = useState(0);
  const [fixedLengthMm, setFixedLengthMm] = useState(0);
  const [qrText, setQrText] = useState('');
  const [printOptions, setPrintOptions] = useState<PrintOptions>(DEFAULT_PRINT_OPTIONS);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [message, setMessage] = useState('');

  const fonts = useFonts();
  const app = useAppInfo().data;

  useEffect(() => {
    gate.ctrlEnterOnly = app?.ctrl_enter_only ?? false;
  }, [app?.ctrl_enter_only, gate]);

  const lastPreconnect = useRef<number | null>(null);
  const preconnect = useCallback(() => {
    const now = Date.now() / 1000;
    if (lastPreconnect.current === null || now - lastPreconnect.current >= PRECONNECT_INTERVAL_S) {
      lastPreconnect.current = now;
      void apiPost('/api/v1/connection/preconnect', {}).catch(() => undefined);
    }
  }, []);

  const markEdited = useCallback(() => {
    gate.edited();
    setRevision(gate.revision);
    setMessage('');
    preconnect();
  }, [gate, preconnect]);

  const linesArr = useMemo(() => trimmedLines(linesText), [linesText]);
  const hasContent = linesArr.some((l) => l.trim() !== '');
  const source = useMemo<TextSource | null>(
    () =>
      hasContent
        ? {
            kind: 'text',
            lines: linesArr,
            font,
            align,
            text_height_mm: textHeight === TEXT_SIZE_AUTO ? null : Number(textHeight),
            max_length_mm: maxLengthMm > 0 ? maxLengthMm : null,
            fixed_length_mm: fixedLengthMm > 0 ? fixedLengthMm : null,
            qr: qrText.trim() || null,
          }
        : null,
    [hasContent, linesArr, font, align, textHeight, maxLengthMm, fixedLengthMm, qrText],
  );

  const renderOptions = useMemo<Partial<PrintOptions>>(
    () => ({ copies: printOptions.copies, chain: printOptions.chain, cut_marks: printOptions.cut_marks }),
    [printOptions.copies, printOptions.chain, printOptions.cut_marks],
  );
  const renderState = useLabelRender(source, renderOptions);

  useEffect(() => {
    if (!source || renderState.loading || renderState.data === undefined) return;
    gate.previewReady(revision, renderState.data.ok);
  }, [gate, source, revision, renderState.loading, renderState.data]);

  const print = usePrint();
  useEffect(() => {
    gate.setBusy(print.busy);
  }, [gate, print.busy]);

  const recentTexts = useQuery({
    queryKey: qk.recentTexts,
    queryFn: ({ signal }) => apiGet<{ items: string[][] }>('/api/v1/labels/recent-texts?n=5', signal),
  });

  const setLines = useCallback((lines: string[]) => {
    setLinesText(lines.join('\n'));
  }, []);

  const applyFields = useCallback((src: TextSource) => {
    setLines(src.lines);
    setFont(src.font);
    setTextHeight(src.text_height_mm ? String(src.text_height_mm) : TEXT_SIZE_AUTO);
    if (src.align) setAlign(src.align);
    setMaxLengthMm(src.max_length_mm ?? 0);
    setFixedLengthMm(src.fixed_length_mm ?? 0);
    setQrText(src.qr ?? '');
  }, [setLines]);

  // Query ?text=… (Kommandopalette, Kontextmenü/URI): einmal je Wert übernehmen, nie drucken.
  const prefill = params.get('text');
  const appliedPrefill = useRef<string | null>(null);
  useEffect(() => {
    if (prefill === null || appliedPrefill.current === prefill) return;
    appliedPrefill.current = prefill;
    setLines(prefill.split('\n'));
    markEdited();
    textareaRef.current?.focus();
    notify({ intent: 'info', title: tt('prefillApplied') });
    // markEdited/notify/setLines sind stabil (useCallback) bzw. Kontext-Funktionen; nur `prefill` steuert den Effekt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill]);

  const doPrint = useCallback(
    async (withCopies: boolean) => {
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
      const opts: Partial<PrintOptions> = withCopies
        ? { copies: printOptions.copies, chain: printOptions.chain, cut_marks: printOptions.cut_marks, cut_pause_s: printOptions.cut_pause_s }
        : { copies: 1, chain: false, cut_marks: true, cut_pause_s: printOptions.cut_pause_s };
      const outcome = await print.run(source, opts);
      if (outcome?.status === 'ok') {
        textareaRef.current?.select();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [source, linesText, gate, printOptions, print],
  );

  const handleTextChange = (_e: unknown, data: { value: string }) => {
    setLinesText(data.value);
    markEdited();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter') return;
    const kind = e.shiftKey ? 'shift_enter' : e.ctrlKey || e.metaKey ? 'ctrl_enter' : 'enter';
    const decision = gate.key(kind, { text: linesText, autoRepeat: e.repeat });
    if (decision.action === 'newline') return;
    e.preventDefault();
    if (decision.action === 'print') void doPrint(kind === 'ctrl_enter');
    else setMessage(gateMessageText(tt, decision.reason));
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    e.preventDefault();
    const el = e.currentTarget;
    const start = el.selectionStart ?? linesText.length;
    const end = el.selectionEnd ?? linesText.length;
    const before = linesText.slice(0, start);
    const after = linesText.slice(end);
    const remaining = before + after;
    const currentLines = remaining.split('\n').length;
    const pastedText = e.clipboardData.getData('text');
    const result = gate.pasted(pastedText, currentLines);
    if (result.error !== null) {
      setMessage(gateMessageText(tt, result.error));
      return;
    }
    setLinesText(before + result.lines.join('\n') + after);
    setRevision(gate.revision);
    preconnect();
    setMessage(result.multiline ? tt('gate.review') : '');
  };

  const applyFix = useCallback(
    (fix: FixJson) => {
      if (fix.source.kind !== 'text') return;
      applyFields(fix.source);
      markEdited();
    },
    [applyFields, markEdited],
  );

  const clickChip = useCallback(
    (lines: string[], altKey: boolean) => {
      if (altKey) {
        setLines(lines);
        markEdited();
        textareaRef.current?.focus();
        return;
      }
      void print.run({ kind: 'text', lines }, { copies: 1, chain: false, cut_marks: true });
    },
    [print, setLines, markEdited],
  );

  const doExport = useCallback(
    (format: 'png' | 'pdf' | 'pbm') => {
      if (!source) return;
      void exportLabel(source, renderOptions, format).catch((err: unknown) => {
        notify({ intent: 'error', title: tt('export.failed'), body: err instanceof Error ? err.message : String(err) });
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [source, renderOptions, notify],
  );

  const handleOptionsChange = useCallback((next: PrintOptions) => {
    setPrintOptions((prev) => {
      if (next.copies !== prev.copies || next.chain !== prev.chain || next.cut_marks !== prev.cut_marks) {
        gate.edited();
        setRevision(gate.revision);
      }
      return next;
    });
  }, [gate]);

  const hint = fieldHint(tt, gate.ctrlEnterOnly, printOptions.copies, printOptions.chain);

  const commands = useMemo(
    () => [
      {
        id: 'druck.aktuell',
        title: tt('common:actions.print'),
        group: 'print',
        shortcut: formatCombo('Ctrl+P'),
        run: () => {
          void doPrint(true);
        },
        enabled: () => Boolean(source) && !print.busy,
      },
      {
        id: 'schnelldruck.leeren',
        title: tt('commands.clear'),
        group: 'schnelldruck',
        run: () => {
          setLinesText('');
          markEdited();
          textareaRef.current?.focus();
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [doPrint, source, print.busy, markEdited, t],
  );
  // Feste Befehlsliste (immer dieselben zwei Einträge): einmal registrieren und über die
  // ref-Indirektion von `useRegisterCommands` frisch halten, statt bei jeder Änderung von
  // `source`/`print.busy` neu zu registrieren (sonst würde diese Seite in der Kommandopalette
  // stets die zuletzt registrierte „druck.aktuell“-Fassung gewinnen).
  useRegisterCommands(commands, []);

  const recentItems = recentTexts.data?.items ?? [];

  return (
    <div className={styles.root}>
      <PageHeader title={tt('title')} />

      <Section>
        <Field label={tt('field.label')} hint={hint}>
          <Textarea
            ref={textareaRef}
            className={styles.textarea}
            value={linesText}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={tt('field.placeholder')}
            resize="none"
            rows={Math.max(1, Math.min(3, linesText.split('\n').length))}
          />
        </Field>
        <div className={styles.message} role="status">
          {message}
        </div>
        {!hasContent ? <Caption1 className={styles.example}>{tt('example', { text: EXAMPLE_TEXT })}</Caption1> : null}

        <TapePreview render={source ? renderState.data : undefined} loading={renderState.loading} />

        {renderState.data && renderState.data.fixes.length > 0 ? (
          <div className={styles.fixes}>
            {renderState.data.fixes.map((fix) => (
              <Button key={fix.id} appearance="outline" size="small" onClick={() => applyFix(fix)}>
                {tt('fixButton', { label: fix.label })}
              </Button>
            ))}
          </div>
        ) : null}

        {qrText.trim() && renderState.data?.qr ? (
          <Caption1
            className={styles.qrInfo}
            title={!renderState.data.qr.checked ? tt('qr.selfTestNotCheckedReason') : undefined}
          >
            {tt('qr.info', {
              version: renderState.data.qr.version,
              status: !renderState.data.qr.checked
                ? tt('qr.selfTestNotChecked')
                : renderState.data.qr.decodes
                  ? tt('qr.selfTestOk')
                  : tt('qr.selfTestFailed'),
            })}
          </Caption1>
        ) : null}

        {recentItems.length > 0 ? (
          <div className={styles.chips} role="group" aria-label={tt('recent.label')}>
            {recentItems.map((lines, i) => (
              <Tooltip key={`${i}-${lines.join('|')}`} content={tt('recent.tooltip')} relationship="description">
                <Button
                  appearance="outline"
                  size="small"
                  aria-label={tt('recent.chipLabel', { text: lines.join(' · ') })}
                  onClick={(e) => clickChip(lines, e.altKey)}
                >
                  {lines.join(' · ')}
                </Button>
              </Tooltip>
            ))}
          </div>
        ) : null}

        <Button
          className={styles.optionsToggle}
          appearance="subtle"
          icon={optionsOpen ? <ChevronUp20Regular /> : <ChevronDown20Regular />}
          onClick={() => setOptionsOpen((o) => !o)}
          aria-expanded={optionsOpen}
        >
          {tt('options.toggle')}
        </Button>
        <div className={mergeClasses(styles.optionsPanel, optionsOpen && styles.optionsPanelOpen)}>
          <div className={styles.optionsInner}>
            <div className={styles.optionsRow}>
              <Field label={tt('options.font')}>
                <Dropdown
                  value={fonts.data?.fonts.find((f) => f.id === font)?.name ?? tt('options.fontDefault')}
                  selectedOptions={font ? [font] : []}
                  onOptionSelect={(_e, data) => {
                    setFont(data.optionValue);
                    markEdited();
                  }}
                >
                  {(fonts.data?.fonts ?? []).map((f) => (
                    <Option key={f.id} value={f.id}>
                      {f.name}
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <Field label={tt('components:textSize.label')}>
                <TextSizeSelect
                  value={textHeight}
                  onChange={(v) => {
                    setTextHeight(v);
                    markEdited();
                  }}
                />
              </Field>
              <Field label={tt('options.align')}>
                <div className={styles.alignGroup} role="group" aria-label={tt('options.align')}>
                  {ALIGNS.map((a) => (
                    <ToggleButton
                      key={a.value}
                      size="small"
                      checked={align === a.value}
                      onClick={() => {
                        setAlign(a.value);
                        markEdited();
                      }}
                    >
                      {a.label}
                    </ToggleButton>
                  ))}
                </div>
              </Field>
              <Field label={tt('options.maxLength')}>
                <SpinButton
                  min={0}
                  max={500}
                  value={maxLengthMm}
                  onChange={(_e, data: SpinButtonOnChangeData) => {
                    const v = data.value ?? (data.displayValue !== undefined ? parseFloat(data.displayValue) : NaN);
                    if (v === null || Number.isNaN(v)) return;
                    setMaxLengthMm(Math.max(0, v));
                    markEdited();
                  }}
                />
              </Field>
              <Field label={tt('options.fixedLength')}>
                <SpinButton
                  min={0}
                  max={500}
                  value={fixedLengthMm}
                  onChange={(_e, data: SpinButtonOnChangeData) => {
                    const v = data.value ?? (data.displayValue !== undefined ? parseFloat(data.displayValue) : NaN);
                    if (v === null || Number.isNaN(v)) return;
                    setFixedLengthMm(Math.max(0, v));
                    markEdited();
                  }}
                />
              </Field>
              <Field label={tt('qr.contentLabel')}>
                <Input
                  value={qrText}
                  placeholder={tt('qr.contentLabel')}
                  onChange={(_e, data) => {
                    setQrText(data.value);
                    markEdited();
                  }}
                />
              </Field>
            </div>
            <PrintOptionsBar value={printOptions} onChange={handleOptionsChange} />
          </div>
        </div>

        <div className={styles.actions}>
          <Button appearance="primary" disabled={print.busy} onClick={() => void doPrint(true)}>
            {printActionLabel(tt, printOptions.copies, printOptions.chain)}
          </Button>
          <Menu>
            <MenuTrigger disableButtonEnhancement>
              <Button appearance="secondary" icon={<ArrowExport20Regular />} disabled={!source}>
                {tt('common:actions.export')}
              </Button>
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                <MenuItem onClick={() => doExport('png')}>PNG</MenuItem>
                <MenuItem onClick={() => doExport('pdf')}>PDF</MenuItem>
                <MenuItem onClick={() => doExport('pbm')}>PBM</MenuItem>
              </MenuList>
            </MenuPopover>
          </Menu>
        </div>

        {renderState.error ? <WarningList errors={[renderState.error.message]} /> : null}
      </Section>
    </div>
  );
}
