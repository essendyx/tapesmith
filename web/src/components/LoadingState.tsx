import { makeStyles, mergeClasses, Skeleton, SkeletonItem, Spinner, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { space } from '../theme/layout';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', rowGap: space.section, minWidth: 0 },
  head: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS, maxWidth: '420px' },
  card: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalM,
    padding: `${tokens.spacingVerticalXL} ${tokens.spacingHorizontalXL}`,
    borderRadius: tokens.borderRadiusXLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  title: { width: '40%' },
  short: { width: '60%' },
  inline: {
    display: 'inline-flex',
    alignItems: 'center',
    columnGap: space.inline,
    color: tokens.colorNeutralForeground3,
  },
});

function Card(props: { lines: number }): JSX.Element {
  const styles = useStyles();
  return (
    <div className={styles.card}>
      <SkeletonItem size={20} className={styles.title} />
      {Array.from({ length: props.lines }, (_, i) => (
        <SkeletonItem key={i} size={16} className={i === props.lines - 1 ? styles.short : undefined} />
      ))}
    </div>
  );
}

/**
 * Ladezustand beim ersten Laden: Platzhalter (Fluent Skeleton) plus Text für Screenreader.
 * Varianten: `page` (Kopf und zwei Karten), `section` (eine Karte), `list` (`rows` Zeilen),
 * `inline` (kleiner Spinner mit Text).
 */
export function LoadingState(props: {
  label?: string;
  variant?: 'page' | 'section' | 'list' | 'inline';
  rows?: number;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('common');
  const label = props.label ?? t('a11y.loading');
  const variant = props.variant ?? 'section';
  const srText = <span className="p12-visually-hidden">{label}</span>;

  if (variant === 'inline') {
    return (
      <span className={styles.inline} aria-busy="true" role="status" data-variant="inline">
        <Spinner size="tiny" aria-hidden="true" />
        <span aria-hidden="true">{label}</span>
        {srText}
      </span>
    );
  }

  let body: JSX.Element;
  if (variant === 'page') {
    body = (
      <div className={styles.page}>
        <div className={styles.head}>
          <SkeletonItem size={40} />
          <SkeletonItem size={16} className={styles.short} />
        </div>
        <Card lines={3} />
        <Card lines={2} />
      </div>
    );
  } else if (variant === 'list') {
    body = (
      <div className={styles.list}>
        {Array.from({ length: Math.max(1, props.rows ?? 5) }, (_, i) => (
          <SkeletonItem key={i} size={36} />
        ))}
      </div>
    );
  } else {
    body = <Card lines={3} />;
  }

  return (
    <div className={mergeClasses(variant === 'page' && styles.page)} aria-busy="true" role="status" data-variant={variant}>
      {srText}
      <Skeleton aria-hidden="true">{body}</Skeleton>
    </div>
  );
}
