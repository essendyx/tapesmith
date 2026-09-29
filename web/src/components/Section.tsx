import { useId, type ReactNode } from 'react';
import { makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { space } from '../theme/layout';

const useStyles = makeStyles({
  root: {
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusXLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    padding: `${tokens.spacingVerticalXL} ${tokens.spacingHorizontalXL}`,
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalL,
    minWidth: 0,
  },
  flush: { padding: 0, overflow: 'hidden', rowGap: 0 },
  head: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    columnGap: tokens.spacingHorizontalM,
    rowGap: space.tight,
    flexWrap: 'wrap',
  },
  headFlush: { padding: `${tokens.spacingVerticalL} ${tokens.spacingHorizontalXL}` },
  text: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, minWidth: 0, flex: '1 1 16rem' },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  titleSmall: { fontSize: tokens.fontSizeBase300, lineHeight: tokens.lineHeightBase300 },
  description: { margin: 0, color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  actions: { display: 'flex', columnGap: space.inline, alignItems: 'center', flexWrap: 'wrap' },
});

/**
 * Karte mit optionalem Titel (`<h2>` bzw. `<h3>`), Beschreibung und Aktionen. `flush` lässt den
 * Inhalt ohne Innenabstand bis an den Rand laufen (Tabellen).
 */
export function Section(props: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  id?: string;
  headingLevel?: 2 | 3;
  flush?: boolean;
}): JSX.Element {
  const styles = useStyles();
  const headingId = useId();
  const hasHead = Boolean(props.title || props.description || props.actions);
  const Heading = props.headingLevel === 3 ? 'h3' : 'h2';
  return (
    <section
      id={props.id}
      aria-labelledby={props.title ? headingId : undefined}
      className={mergeClasses('p12-card', styles.root, props.flush && styles.flush)}
    >
      {hasHead ? (
        <div className={mergeClasses(styles.head, props.flush && styles.headFlush)}>
          <div className={styles.text}>
            {props.title ? (
              <Heading id={headingId} className={mergeClasses(styles.title, props.headingLevel === 3 && styles.titleSmall)}>
                {props.title}
              </Heading>
            ) : null}
            {props.description ? <div className={styles.description}>{props.description}</div> : null}
          </div>
          {props.actions ? <div className={styles.actions}>{props.actions}</div> : null}
        </div>
      ) : null}
      {props.children}
    </section>
  );
}
