/** Tab Garantie: Rechnung suchen, Garantie-Etikett mit QR vorschauen und drucken. */
import { useMemo, useState } from 'react';
import {
  Button,
  Field,
  Input,
  Table,
  TableBody,
  TableCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Trans, useTranslation } from 'react-i18next';
import type { TemplateSource } from '../../api/types';
import { useLabelRender } from '../../api/labels';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { Section } from '../../components/Section';
import { WarningList } from '../../components/WarningList';
import { usePrint } from '../../components/usePrint';
import { useLayoutStyles } from '../../theme/layout';
import { useDocumentSearch, useWarranty } from './api';
import type { DocumentSearchParams } from './types';

const useStyles = makeStyles({
  field: { minWidth: '160px' },
  preview: { maxWidth: '100%', border: `1px solid ${tokens.colorNeutralStroke2}`, borderRadius: tokens.borderRadiusMedium },
  selectedRow: { backgroundColor: tokens.colorBrandBackground2 },
});

const EMPTY_SEARCH: DocumentSearchParams = { query: '', correspondent: '', date_from: '', date_to: '' };

interface GarantieLabelValues {
  geraet: string;
  kaufdatum: string;
  ende: string;
  link: string;
}

export function GarantieView(): JSX.Element {
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { t } = useTranslation('paperless');
  const { t: tc } = useTranslation('common');
  const [form, setForm] = useState(EMPTY_SEARCH);
  const [activeSearch, setActiveSearch] = useState<DocumentSearchParams>(EMPTY_SEARCH);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [geraet, setGeraet] = useState('');
  const [monateText, setMonateText] = useState('');

  const results = useDocumentSearch(activeSearch, true);
  const monate = monateText.trim() === '' ? null : Number(monateText);
  const validMonate = monateText.trim() === '' || (Number.isInteger(monate) && (monate as number) > 0);
  const warranty = useWarranty(selectedId, validMonate ? monate : null, '');

  const labelValues = useMemo<GarantieLabelValues | null>(() => {
    if (!warranty.data) return null;
    const v = warranty.data.label.values;
    return {
      geraet: geraet || v.geraet || '',
      kaufdatum: v.kaufdatum || '',
      ende: v.ende || '',
      link: v.link || '',
    };
  }, [warranty.data, geraet]);

  const source: TemplateSource | null = useMemo(() => {
    if (!labelValues) return null;
    return { kind: 'template', template: 'garantie-qr', values: labelValues as unknown as Record<string, string> };
  }, [labelValues]);

  const render = useLabelRender(source);
  const printFlow = usePrint();

  function selectDocument(id: number): void {
    setSelectedId(id);
    setGeraet('');
    setMonateText('');
  }

  function onSearch(): void {
    setActiveSearch(form);
  }

  async function onPrint(): Promise<void> {
    if (!source) return;
    await printFlow.run(source);
  }

  return (
    <div className={layout.stack}>
      <Section title={t('garantie.searchTitle')}>
        <div className={layout.rowWrap}>
          <Field label={t('garantie.fields.text')} className={styles.field}>
            <Input value={form.query} onChange={(_e, data) => setForm((f) => ({ ...f, query: data.value }))} />
          </Field>
          <Field label={t('garantie.fields.dealer')} className={styles.field}>
            <Input value={form.correspondent} onChange={(_e, data) => setForm((f) => ({ ...f, correspondent: data.value }))} />
          </Field>
          <Field label={t('garantie.fields.from')} hint={t('garantie.fields.fromToHint')} className={styles.field}>
            <Input type="date" value={form.date_from} onChange={(_e, data) => setForm((f) => ({ ...f, date_from: data.value }))} />
          </Field>
          <Field label={t('garantie.fields.to')} hint={t('garantie.fields.fromToHint')} className={styles.field}>
            <Input type="date" value={form.date_to} onChange={(_e, data) => setForm((f) => ({ ...f, date_to: data.value }))} />
          </Field>
          <Button appearance="primary" onClick={onSearch} disabled={results.isFetching}>
            {t('garantie.search')}
          </Button>
        </div>
        {results.isLoading ? <LoadingState variant="inline" /> : null}
        {results.error ? <ErrorMessage error={results.error} title={t('garantie.searchFailedTitle')} /> : null}
        {results.data ? (
          results.data.documents.length ? (
            <Table size="small" aria-label={t('garantie.resultsAriaLabel')}>
              <TableBody>
                {results.data.documents.map((doc) => (
                  <TableRow
                    key={doc.id}
                    className={doc.id === selectedId ? styles.selectedRow : undefined}
                    onClick={() => selectDocument(doc.id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <TableCell>{doc.created}</TableCell>
                    <TableCell>{doc.correspondent ?? ''}</TableCell>
                    <TableCell>{doc.title}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState title={t('garantie.empty.title')} body={t('garantie.empty.body')} />
          )
        ) : null}
      </Section>

      {selectedId !== null ? (
        <Section title={t('garantie.labelTitle')}>
          <div className={layout.rowWrap}>
            <Field label={t('garantie.deviceField')} className={styles.field}>
              <Input
                value={geraet || warranty.data?.label.values.geraet || ''}
                onChange={(_e, data) => setGeraet(data.value)}
              />
            </Field>
            <Field label={t('garantie.monthsField')} hint={t('garantie.monthsHint')} className={styles.field}>
              <Input value={monateText} onChange={(_e, data) => setMonateText(data.value)} />
            </Field>
          </div>

          {warranty.isLoading ? <LoadingState variant="inline" /> : null}
          {warranty.error ? <ErrorMessage error={warranty.error} title={t('garantie.warrantyFailedTitle')} /> : null}
          {labelValues ? (
            <p>
              <Trans i18nKey="paperless:garantie.until" values={{ ende: labelValues.ende }} components={{ strong: <strong /> }} />
              {warranty.data?.warranty.quelle_ende ? ` (${warranty.data.warranty.quelle_ende})` : ''}
            </p>
          ) : null}
          <WarningList warnings={warranty.data?.warnings} />

          {render.data?.preview?.design_png ? (
            <img
              className={styles.preview}
              alt={t('garantie.previewAlt')}
              src={`data:image/png;base64,${render.data.preview.design_png}`}
            />
          ) : null}

          <Button appearance="primary" onClick={() => void onPrint()} disabled={!source || printFlow.busy}>
            {printFlow.busy ? t('garantie.printing') : tc('actions.print')}
          </Button>
        </Section>
      ) : null}
    </div>
  );
}
