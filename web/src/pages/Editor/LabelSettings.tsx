/** Label-Einstellungen (ohne Auswahl): Länge, Rand, Spiegeln/Drehen, Zielobjekt. */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Caption1, MessageBar, MessageBarBody, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import type { LabelDocumentJson, TargetJson } from '../../api/types';
import { listTargets } from './editorApi';
import { ChoiceField, NumberField, SwitchField } from './fields';

type LengthMode = 'auto' | 'fixed' | 'max';

const MODES: LengthMode[] = ['auto', 'fixed', 'max'];

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  heading: { margin: 0, fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  hint: { color: tokens.colorNeutralForeground3 },
});

export function LabelSettings(props: {
  doc: LabelDocumentJson;
  contentMm: number | null;
  onSetLength: (mode: LengthMode, lengthMm: number | null) => void;
  onMargin: (mm: number) => void;
  onTransform: (change: { mirror?: boolean; rotate180?: boolean }) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const { doc } = props;
  const targets = useQuery({ queryKey: ['targets'], queryFn: ({ signal }) => listTargets(signal), staleTime: 5 * 60_000 });
  const [target, setTarget] = useState<TargetJson | null>(null);
  const mode: LengthMode = doc.length_mode ?? 'auto';
  const fallbackMm = Math.max(5, Math.round(props.contentMm ?? 30));

  return (
    <div className={styles.root}>
      <h2 className={styles.heading}>{t('label.heading')}</h2>
      <Caption1 className={styles.hint}>{t('label.hint')}</Caption1>
      <ChoiceField
        label={t('label.length')}
        value={mode}
        options={MODES.map((m) => ({ value: m, label: t(`label.${m}`) }))}
        onChange={(m) => props.onSetLength(m, m === 'auto' ? null : (doc.length_mm ?? fallbackMm))}
      />
      {mode !== 'auto' ? (
        <NumberField
          key={`len-${mode}`}
          label={mode === 'fixed' ? t('label.fixedLength') : t('label.maxLength')}
          value={doc.length_mm ?? fallbackMm}
          min={1}
          max={2000}
          step={1}
          onCommit={(v) => {
            if (v !== null) props.onSetLength(mode, v);
          }}
        />
      ) : null}
      <NumberField
        label={t('label.margin')}
        value={doc.margin_mm ?? 1}
        min={0}
        max={20}
        step={0.5}
        onCommit={(v) => {
          if (v !== null) props.onMargin(v);
        }}
      />
      <SwitchField label={t('label.mirror')} checked={doc.mirror ?? false} onChange={(v) => props.onTransform({ mirror: v })} />
      <SwitchField label={t('label.rotate180')} checked={doc.rotate180 ?? false} onChange={(v) => props.onTransform({ rotate180: v })} />
      <ChoiceField
        label={t('label.target')}
        value={target?.id ?? null}
        placeholder={targets.isLoading ? t('label.targetLoading') : t('label.targetNone')}
        options={(targets.data?.targets ?? []).map((t) => ({ value: t.id, label: t.name }))}
        onChange={(id) => {
          const t = targets.data?.targets.find((x) => x.id === id) ?? null;
          setTarget(t);
          if (t?.max_length_mm != null) props.onSetLength('max', t.max_length_mm);
        }}
      />
      {target?.note ? (
        <MessageBar intent="info" layout="multiline">
          <MessageBarBody>{target.note}</MessageBarBody>
        </MessageBar>
      ) : null}
    </div>
  );
}
