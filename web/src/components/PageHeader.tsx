import type { ReactNode } from 'react';
import { makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { FONT_FAMILY_DISPLAY } from '../theme/ThemeProvider';
import { space } from '../theme/layout';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXS,
    marginBottom: space.section,
    minWidth: 0,
  },
  main: {
    display: 'flex',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalM,
    minWidth: 0,
  },
  breadcrumb: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
  },
  text: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS, minWidth: 0 },
  title: {
    margin: 0,
    fontFamily: FONT_FAMILY_DISPLAY,
    fontSize: tokens.fontSizeHero700,
    lineHeight: tokens.lineHeightHero700,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    letterSpacing: '-0.01em',
    overflowWrap: 'anywhere',
  },
  subtitle: {
    margin: 0,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
    color: tokens.colorNeutralForeground3,
    maxWidth: '80ch',
  },
  actions: {
    display: 'flex',
    alignItems: 'center',
    columnGap: space.inline,
    rowGap: space.tight,
    flexWrap: 'wrap',
  },
});

/** Seitenkopf mit dem einzigen `<h1>` der Seite, optional Pfad, Untertitel und Aktionen. */
export function PageHeader(props: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('common');
  return (
    <header className={styles.root}>
      {props.breadcrumb ? (
        <nav aria-label={t('a11y.breadcrumb')} className={styles.breadcrumb}>
          {props.breadcrumb}
        </nav>
      ) : null}
      <div className={styles.main}>
        <div className={styles.text}>
          <h1 className={styles.title}>{props.title}</h1>
          {props.subtitle ? <div className={styles.subtitle}>{props.subtitle}</div> : null}
        </div>
        {props.actions ? <div className={styles.actions}>{props.actions}</div> : null}
      </div>
    </header>
  );
}
