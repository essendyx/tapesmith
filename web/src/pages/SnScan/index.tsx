/** Seite SnScan: Seriennummer vom Foto des Herstelleraufklebers lesen. */
import { useRef, useState } from 'react';
import {
  Button,
  Field,
  Input,
  Radio,
  RadioGroup,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { Section } from '../../components/Section';
import { useLayoutStyles } from '../../theme/layout';
import { prepareImage, postCodescan } from './api';
import type { CodescanResultJson } from './types';

const useStyles = makeStyles({
  page: { maxWidth: '640px' },
  photoRow: { display: 'flex', flexDirection: 'column', alignItems: 'center', rowGap: tokens.spacingVerticalM },
  preview: {
    maxWidth: '100%',
    maxHeight: '260px',
    borderRadius: tokens.borderRadiusLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  candidate: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS },
  candidateSerial: { fontWeight: tokens.fontWeightSemibold, fontSize: tokens.fontSizeBase400 },
  candidateReason: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  labelPreview: { fontSize: tokens.fontSizeBase300, color: tokens.colorNeutralForeground2 },
  fieldsRow: {
    display: 'flex',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
    flexWrap: 'wrap',
  },
  fieldsCol: { flex: '1 1 160px', minWidth: 0 },
  visuallyHidden: {
    position: 'absolute',
    width: '1px',
    height: '1px',
    padding: 0,
    margin: '-1px',
    overflow: 'hidden',
    clip: 'rect(0, 0, 0, 0)',
    whiteSpace: 'nowrap',
    border: 0,
  },
});

function last6(serial: string): string {
  return serial.length > 6 ? serial.slice(-6) : serial;
}

export default function SnScanPage(): JSX.Element {
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { t } = useTranslation('snscan');
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<CodescanResultJson | null>(null);
  const [selectedSerial, setSelectedSerial] = useState('');
  const [host, setHost] = useState('');
  const [slot, setSlot] = useState('');
  const [copied, setCopied] = useState(false);

  function reset(): void {
    setResult(null);
    setError(null);
    setSelectedSerial('');
    setCopied(false);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
  }

  async function onFileChosen(file: File): Promise<void> {
    reset();
    setPreviewUrl(URL.createObjectURL(file));
    setLoading(true);
    try {
      const imageB64 = await prepareImage(file);
      const body = await postCodescan(imageB64, file.name);
      setResult(body);
      setSelectedSerial(body.best ?? '');
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>): void {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (file) void onFileChosen(file);
  }

  async function copySerial(): Promise<void> {
    try {
      await navigator.clipboard.writeText(selectedSerial);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  function useForDatentraeger(): void {
    const werte = { sn: selectedSerial, host: host.trim(), slot: slot.trim() };
    navigate(`/vorlagen?vorlage=datentraeger&werte=${encodeURIComponent(JSON.stringify(werte))}`);
  }

  const hasHits = (result?.hits.length ?? 0) > 0;

  return (
    <div className={`${layout.stack} ${styles.page}`}>
      <PageHeader title={moduleTexts('snscan').name} subtitle={moduleTexts('snscan').description} />

      <Section title={t('photo.sectionTitle')}>
        <div className={styles.photoRow}>
          <input
            ref={inputRef}
            id="sn-scan-datei-input"
            className={styles.visuallyHidden}
            type="file"
            accept="image/*"
            capture="environment"
            onChange={onInputChange}
            aria-label={t('photo.chooseAriaLabel')}
          />
          <Button appearance="primary" size="large" onClick={() => inputRef.current?.click()}>
            {t('photo.take')}
          </Button>
          {previewUrl ? <img className={styles.preview} src={previewUrl} alt={t('photo.previewAlt')} /> : null}
          {loading ? <LoadingState variant="inline" label={t('photo.analyzing')} /> : null}
        </div>
      </Section>

      {error ? <ErrorMessage error={error} /> : null}

      {result && !hasHits ? <EmptyState title={t('noHits.title')} body={t('noHits.body')} compact /> : null}

      {result && hasHits ? (
        <Section title={t('candidates.sectionTitle')} description={t('candidates.description')}>
          <RadioGroup value={selectedSerial} onChange={(_e, data) => setSelectedSerial(data.value)}>
            {result.candidates.map((candidate) => (
              <Radio
                key={candidate.serial}
                value={candidate.serial}
                label={
                  <div className={styles.candidate}>
                    <span className={styles.candidateSerial}>{candidate.serial}</span>
                    <span className={styles.candidateReason}>
                      {candidate.reason} · {candidate.format} · {t('candidates.points', { score: candidate.score })}
                    </span>
                  </div>
                }
              />
            ))}
          </RadioGroup>

          <Field label={t('fields.serial')}>
            <Input value={selectedSerial} onChange={(_e, data) => setSelectedSerial(data.value)} />
          </Field>

          {selectedSerial ? (
            <Text className={styles.labelPreview}>{t('labelPreview', { short: last6(selectedSerial) })}</Text>
          ) : null}

          <div className={styles.fieldsRow}>
            <Field className={styles.fieldsCol} label={t('fields.host')}>
              <Input value={host} onChange={(_e, data) => setHost(data.value)} />
            </Field>
            <Field className={styles.fieldsCol} label={t('fields.slot')}>
              <Input value={slot} onChange={(_e, data) => setSlot(data.value)} />
            </Field>
          </div>

          <div className={layout.actions}>
            <Button appearance="primary" disabled={!selectedSerial} onClick={useForDatentraeger}>
              {t('actions.useForDatentraeger')}
            </Button>
            <Button disabled={!selectedSerial} onClick={() => void copySerial()}>
              {copied ? t('actions.copied') : t('actions.copy')}
            </Button>
            <Button onClick={() => inputRef.current?.click()}>{t('photo.newPhoto')}</Button>
          </div>
        </Section>
      ) : null}
    </div>
  );
}
