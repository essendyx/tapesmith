/**
 * QR-Assistent: Inhalt (URL/Text/WLAN/vCard) erfassen, Größenlogik
 * anzeigen, Vorschau und Druck über den Server (`render.qr`). Baut den QR-Inhalt nie selbst,
 * das übernimmt ausschließlich der Server (`/api/v1/labels/render`).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Caption1,
  Checkbox,
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
  Tab,
  TabList,
  Tooltip,
  makeStyles,
  tokens,
  type SpinButtonOnChangeData,
} from '@fluentui/react-components';
import {
  ArrowExport20Regular,
  CheckmarkCircle20Filled,
  ErrorCircle20Filled,
  Eye20Regular,
  EyeOff20Regular,
  Info20Regular,
} from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { exportLabel, useLabelRender } from '../../api/labels';
import { DEFAULT_PRINT_OPTIONS, type FixJson, type PrintOptions, type QrContentInput, type QrSource } from '../../api/types';
import { formatCombo } from '../../commands/shortcuts';
import { useRegisterCommands } from '../../commands/CommandProvider';
import { useNotify } from '../../components/NotifyProvider';
import { PageHeader } from '../../components/PageHeader';
import { PrintOptionsBar } from '../../components/PrintOptionsBar';
import { Section } from '../../components/Section';
import { TapePreview } from '../../components/TapePreview';
import { usePrint } from '../../components/usePrint';

type Kind = 'url' | 'text' | 'wifi' | 'vcard';
type ErrorLevel = 'auto' | 'l' | 'm' | 'q' | 'h';
type Translate = (key: string, options?: Record<string, unknown>) => string;

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL },
  layout: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalXL, rowGap: tokens.spacingVerticalL },
  left: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM, flex: '1 1 320px', minWidth: '280px' },
  right: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM, flex: '1 1 320px', minWidth: '280px' },
  /** Einheitliches Feldraster: gleich breite Spalten, jedes Feld füllt seine Spalte. */
  fieldsRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
    alignItems: 'end',
    '& .fui-Input, & .fui-Dropdown, & .fui-SpinButton': { width: '100%', minWidth: 0 },
  },
  fieldsStack: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXS,
    '& .fui-Input': { width: '100%' },
  },
  message: {
    color: tokens.colorPaletteDarkOrangeForeground1,
    ':empty': { marginTop: `calc(-1 * ${tokens.spacingVerticalM})` },
  },
  infoCard: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXS,
    padding: tokens.spacingVerticalM,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground3,
  },
  infoRow: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  fixes: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalXS },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center', flexWrap: 'wrap' },
});

function isUrlLike(text: string): boolean {
  const t = text.trim().toLowerCase();
  return t.startsWith('http://') || t.startsWith('https://') || t.startsWith('\\\\');
}

export default function QrPage(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('qr');
  const tt: Translate = (key, opts) => String(t(key, opts));
  const notify = useNotify();
  const [params] = useSearchParams();

  const KINDS = useMemo<{ value: Kind; label: string }[]>(
    () => [
      { value: 'url', label: tt('tabs.url') },
      { value: 'text', label: tt('tabs.text') },
      { value: 'wifi', label: tt('tabs.wifi') },
      { value: 'vcard', label: tt('tabs.vcard') },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t],
  );
  const ERROR_LEVELS = useMemo<{ value: ErrorLevel; label: string }[]>(
    () => [
      { value: 'auto', label: tt('errorLevels.auto') },
      { value: 'l', label: tt('errorLevels.l') },
      { value: 'm', label: tt('errorLevels.m') },
      { value: 'q', label: tt('errorLevels.q') },
      { value: 'h', label: tt('errorLevels.h') },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t],
  );
  const SECURITIES = useMemo<{ value: 'WPA' | 'WEP' | 'nopass'; label: string }[]>(
    () => [
      { value: 'WPA', label: tt('security.wpa') },
      { value: 'WEP', label: tt('security.wep') },
      { value: 'nopass', label: tt('security.open') },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t],
  );

  const [kind, setKind] = useState<Kind>('url');
  const [url, setUrl] = useState('');
  const [urlUppercase, setUrlUppercase] = useState(false);
  const [text, setText] = useState('');
  const [ssid, setSsid] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [security, setSecurity] = useState<'WPA' | 'WEP' | 'nopass'>('WPA');
  const [hidden, setHidden] = useState(false);
  const [vcName, setVcName] = useState('');
  const [vcPhone, setVcPhone] = useState('');
  const [vcEmail, setVcEmail] = useState('');
  const [vcOrg, setVcOrg] = useState('');
  const [vcUrl, setVcUrl] = useState('');
  const [line1, setLine1] = useState('');
  const [line2, setLine2] = useState('');
  const [errorLevel, setErrorLevel] = useState<ErrorLevel>('auto');
  const [maxLengthMm, setMaxLengthMm] = useState(0);
  const [printOptions, setPrintOptions] = useState<PrintOptions>(DEFAULT_PRINT_OPTIONS);
  const [message, setMessage] = useState('');

  const content = useMemo<QrContentInput>(() => {
    if (kind === 'url') return { type: 'url', url, uppercase: urlUppercase };
    if (kind === 'text') return { type: 'text', text };
    if (kind === 'wifi') return { type: 'wifi', ssid, password, security, hidden };
    return { type: 'vcard', name: vcName, phone: vcPhone, email: vcEmail, org: vcOrg, url: vcUrl };
  }, [kind, url, urlUppercase, text, ssid, password, security, hidden, vcName, vcPhone, vcEmail, vcOrg, vcUrl]);

  const hasContent = useMemo(() => {
    if (kind === 'url') return url.trim() !== '';
    if (kind === 'text') return text.trim() !== '';
    if (kind === 'wifi') return ssid.trim() !== '';
    return [vcName, vcPhone, vcEmail, vcOrg, vcUrl].some((v) => v.trim() !== '');
  }, [kind, url, text, ssid, vcName, vcPhone, vcEmail, vcOrg, vcUrl]);

  const source = useMemo<QrSource | null>(() => {
    if (!hasContent) return null;
    const lines = [line1, line2].filter((l) => l.trim() !== '').slice(0, 2);
    return { kind: 'qr', content, lines, error: errorLevel, max_length_mm: maxLengthMm > 0 ? maxLengthMm : null };
  }, [hasContent, content, line1, line2, errorLevel, maxLengthMm]);

  const renderOptions = useMemo<Partial<PrintOptions>>(
    () => ({ copies: printOptions.copies, chain: printOptions.chain, cut_marks: printOptions.cut_marks }),
    [printOptions.copies, printOptions.chain, printOptions.cut_marks],
  );
  const renderState = useLabelRender(source, renderOptions, { debounceMs: 200 });
  const printable = Boolean(source) && !renderState.loading && renderState.data?.ok === true;

  const print = usePrint();

  const applyContent = useCallback((c: QrContentInput, lines: string[] = []) => {
    if (c.type === 'url') {
      setKind('url');
      setUrl(c.url);
      setUrlUppercase(c.uppercase ?? false);
    } else if (c.type === 'text') {
      setKind('text');
      setText(c.text);
    } else if (c.type === 'wifi') {
      setKind('wifi');
      setSsid(c.ssid);
      setPassword(c.password);
      setSecurity(c.security);
      setHidden(c.hidden);
    } else {
      setKind('vcard');
      setVcName(c.name);
      setVcPhone(c.phone ?? '');
      setVcEmail(c.email ?? '');
      setVcOrg(c.org ?? '');
      setVcUrl(c.url ?? '');
    }
    setLine1(lines[0] ?? '');
    setLine2(lines[1] ?? '');
  }, []);

  // Query ?inhalt=…&zeilen=[…]: URL-artiger Inhalt (http/https/UNC) auf den Reiter URL, sonst Text.
  const inhalt = params.get('inhalt');
  const zeilenParam = params.get('zeilen');
  const appliedQuery = useRef<string | null>(null);
  useEffect(() => {
    const key = `${inhalt ?? ''}\u0000${zeilenParam ?? ''}`;
    if (inhalt === null || appliedQuery.current === key) return;
    appliedQuery.current = key;
    let lines: string[] = [];
    if (zeilenParam) {
      try {
        const parsed = JSON.parse(zeilenParam) as unknown;
        if (Array.isArray(parsed)) lines = parsed.filter((v): v is string => typeof v === 'string');
      } catch {
        lines = [];
      }
    }
    if (isUrlLike(inhalt)) applyContent({ type: 'url', url: inhalt.trim() }, lines);
    else applyContent({ type: 'text', text: inhalt }, lines);
    // applyContent ist stabil (useCallback ohne Abhängigkeiten außer setState); nur die Query steuert den Effekt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inhalt, zeilenParam]);

  const applyFix = useCallback(
    (fix: FixJson) => {
      if (fix.source.kind !== 'qr') return;
      applyContent(fix.source.content, fix.source.lines);
      setErrorLevel(fix.source.error);
      setMaxLengthMm(fix.source.max_length_mm ?? 0);
      setMessage('');
    },
    [applyContent],
  );

  const doPrint = useCallback(async () => {
    if (!source) {
      setMessage(tt('message.empty'));
      return;
    }
    if (renderState.loading) {
      setMessage(tt('message.rendering'));
      return;
    }
    if (renderState.data?.ok !== true) {
      setMessage(tt('message.notPrintable'));
      return;
    }
    setMessage('');
    const outcome = await print.run(source, {
      copies: printOptions.copies,
      chain: printOptions.chain,
      cut_marks: printOptions.cut_marks,
      cut_pause_s: printOptions.cut_pause_s,
    });
    if (outcome && outcome.status !== 'ok') setMessage('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, renderState.loading, renderState.data, print, printOptions]);

  const doExport = useCallback(
    (format: 'png' | 'pdf' | 'pbm') => {
      if (!source) return;
      void exportLabel(source, renderOptions, format).catch((err: unknown) => {
        notify({ intent: 'error', title: tt('exportFailed'), body: err instanceof Error ? err.message : String(err) });
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [source, renderOptions, notify],
  );

  const commands = useMemo(
    () => [
      {
        id: 'druck.aktuell',
        title: tt('common:actions.print'),
        group: 'print',
        shortcut: formatCombo('Ctrl+P'),
        run: () => void doPrint(),
        enabled: () => printable,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, doPrint, printable],
  );
  useRegisterCommands(commands, []);

  const qr = renderState.data?.qr ?? null;

  return (
    <div className={styles.root}>
      <PageHeader title={tt('title')} />
      <Section>
        <div className={styles.layout}>
          <div className={styles.left}>
            <TabList selectedValue={kind} onTabSelect={(_e, data) => setKind(data.value as Kind)} aria-label={tt('tabs.label')}>
              {KINDS.map((k) => (
                <Tab key={k.value} value={k.value}>
                  {k.label}
                </Tab>
              ))}
            </TabList>

            {kind === 'url' ? (
              <div className={styles.fieldsStack}>
                <Field label={tt('fields.link')}>
                  <Input value={url} onChange={(_e, d) => setUrl(d.value)} placeholder={tt('fields.linkPlaceholder')} />
                </Field>
                <Checkbox
                  label={tt('fields.uppercase')}
                  checked={urlUppercase}
                  onChange={(_e, d) => setUrlUppercase(Boolean(d.checked))}
                />
              </div>
            ) : null}

            {kind === 'text' ? (
              <Field label={tt('fields.text')}>
                <Input value={text} onChange={(_e, d) => setText(d.value)} />
              </Field>
            ) : null}

            {kind === 'wifi' ? (
              <div className={styles.fieldsRow}>
                <Field label={tt('fields.ssid')}>
                  <Input value={ssid} onChange={(_e, d) => setSsid(d.value)} />
                </Field>
                <Field label={tt('fields.password')}>
                  <Input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(_e, d) => setPassword(d.value)}
                    contentAfter={
                      <Button
                        appearance="transparent"
                        size="small"
                        icon={showPassword ? <EyeOff20Regular /> : <Eye20Regular />}
                        aria-label={showPassword ? tt('fields.passwordHide') : tt('fields.passwordShow')}
                        aria-pressed={showPassword}
                        onClick={() => setShowPassword((s) => !s)}
                      />
                    }
                  />
                </Field>
                <Field label={tt('fields.security')}>
                  <Dropdown
                    value={SECURITIES.find((s) => s.value === security)?.label ?? ''}
                    selectedOptions={[security]}
                    onOptionSelect={(_e, data) => setSecurity(data.optionValue as 'WPA' | 'WEP' | 'nopass')}
                  >
                    {SECURITIES.map((s) => (
                      <Option key={s.value} value={s.value}>
                        {s.label}
                      </Option>
                    ))}
                  </Dropdown>
                </Field>
                <Checkbox label={tt('fields.hidden')} checked={hidden} onChange={(_e, d) => setHidden(Boolean(d.checked))} />
              </div>
            ) : null}

            {kind === 'vcard' ? (
              <div className={styles.fieldsRow}>
                <Field label={tt('fields.name')}>
                  <Input value={vcName} onChange={(_e, d) => setVcName(d.value)} />
                </Field>
                <Field label={tt('fields.phone')}>
                  <Input value={vcPhone} onChange={(_e, d) => setVcPhone(d.value)} />
                </Field>
                <Field label={tt('fields.email')}>
                  <Input value={vcEmail} onChange={(_e, d) => setVcEmail(d.value)} />
                </Field>
                <Field label={tt('fields.company')}>
                  <Input value={vcOrg} onChange={(_e, d) => setVcOrg(d.value)} />
                </Field>
                <Field label={tt('fields.url')}>
                  <Input value={vcUrl} onChange={(_e, d) => setVcUrl(d.value)} />
                </Field>
              </div>
            ) : null}

            <div className={styles.fieldsRow}>
              <Field label={tt('fields.line1')}>
                <Input value={line1} onChange={(_e, d) => setLine1(d.value)} />
              </Field>
              <Field label={tt('fields.line2')}>
                <Input value={line2} onChange={(_e, d) => setLine2(d.value)} />
              </Field>
            </div>

            <div className={styles.fieldsRow}>
              <Field label={tt('fields.errorLevel')}>
                <Dropdown
                  value={ERROR_LEVELS.find((l) => l.value === errorLevel)?.label ?? ''}
                  selectedOptions={[errorLevel]}
                  onOptionSelect={(_e, data) => setErrorLevel(data.optionValue as ErrorLevel)}
                >
                  {ERROR_LEVELS.map((l) => (
                    <Option key={l.value} value={l.value}>
                      {l.label}
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <Field label={tt('fields.maxLength')}>
                <SpinButton
                  min={0}
                  max={500}
                  value={maxLengthMm}
                  onChange={(_e, data: SpinButtonOnChangeData) => {
                    const v = data.value ?? (data.displayValue !== undefined ? parseFloat(data.displayValue) : NaN);
                    if (v === null || Number.isNaN(v)) return;
                    setMaxLengthMm(Math.max(0, v));
                  }}
                />
              </Field>
            </div>

            {qr ? (
              <div className={styles.infoCard}>
                <div className={styles.infoRow}>
                  <Caption1>{tt('info.version', { version: qr.version })}</Caption1>
                  <Caption1>{tt('info.moduleSize', { dots: qr.module_dots })}</Caption1>
                  <Caption1>{tt('info.errorCorrection', { level: qr.error.toUpperCase() })}</Caption1>
                </div>
                <div className={styles.infoRow}>
                  {!qr.checked ? (
                    <Tooltip content={tt('info.selfTestNotCheckedReason')} relationship="description">
                      <Badge appearance="filled" color="informative" icon={<Info20Regular />}>
                        {tt('info.selfTestNotChecked')}
                      </Badge>
                    </Tooltip>
                  ) : qr.decodes ? (
                    <Badge appearance="filled" color="success" icon={<CheckmarkCircle20Filled />}>
                      {tt('info.selfTestOk')}
                    </Badge>
                  ) : (
                    <Badge appearance="filled" color="danger" icon={<ErrorCircle20Filled />}>
                      {tt('info.selfTestFailed')}
                    </Badge>
                  )}
                </div>
              </div>
            ) : null}

            {renderState.data && renderState.data.fixes.length > 0 ? (
              <div className={styles.fixes}>
                {renderState.data.fixes.map((fix) => (
                  <Button key={fix.id} appearance="outline" size="small" onClick={() => applyFix(fix)}>
                    {tt('fixButton', { label: fix.label })}
                  </Button>
                ))}
              </div>
            ) : null}

            <div className={styles.message} role="status">
              {message}
            </div>

            <PrintOptionsBar value={printOptions} onChange={setPrintOptions} />

            <div className={styles.actions}>
              <Button appearance="primary" disabled={print.busy} onClick={() => void doPrint()}>
                {tt('common:actions.print')}
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
          </div>

          <div className={styles.right}>
            <TapePreview render={source ? renderState.data : undefined} loading={renderState.loading} />
          </div>
        </div>
      </Section>
    </div>
  );
}
