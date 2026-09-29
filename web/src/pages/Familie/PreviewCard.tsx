/** Vorschau-Karte der Familienseite: PNG auf weißem Band, Länge, Fehler/Warnungen. */
import { Caption1, Spinner, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import type { FamilyPreview } from './types';

const useStyles = makeStyles({
  card: {
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow4,
    padding: tokens.spacingVerticalL,
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalS,
    minHeight: '96px',
  },
  stage: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '80px',
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackgroundStatic,
    padding: tokens.spacingVerticalM,
    overflow: 'auto',
  },
  image: { display: 'block', maxWidth: '100%', height: 'auto', imageRendering: 'pixelated' },
  length: { color: tokens.colorNeutralForeground2 },
  errors: { color: tokens.colorPaletteRedForeground1 },
  warnings: { color: tokens.colorPaletteDarkOrangeForeground1, fontSize: tokens.fontSizeBase200 },
  placeholder: { color: tokens.colorNeutralForeground3 },
});

export function PreviewCard(props: { preview: FamilyPreview | null; loading: boolean }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('familie');
  const { preview, loading } = props;

  return (
    <div className={styles.card}>
      <div className={styles.stage} aria-busy={loading}>
        {loading && !preview ? (
          <Spinner size="small" label={t('preview.loading')} />
        ) : preview?.ok && preview.design_png ? (
          <img className={styles.image} src={`data:image/png;base64,${preview.design_png}`} alt={t('preview.alt')} draggable={false} />
        ) : preview && !preview.ok ? (
          <div className={styles.errors} role="alert">
            {preview.errors.length > 0 ? preview.errors.map((e, i) => <div key={i}>{e}</div>) : <div>{t('preview.notPossible')}</div>}
          </div>
        ) : (
          <span className={styles.placeholder}>{t('preview.empty')}</span>
        )}
      </div>
      {preview?.ok && preview.length_mm != null ? (
        <Caption1 className={styles.length}>{t('preview.length', { mm: Math.round(preview.length_mm) })}</Caption1>
      ) : null}
      {preview?.warnings && preview.warnings.length > 0 ? (
        <div className={styles.warnings}>
          {preview.warnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
