import type { ReactNode } from 'react';
import { makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { Sparkle24Regular } from '@fluentui/react-icons';
import { space } from '../theme/layout';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    textAlign: 'center',
    rowGap: tokens.spacingVerticalS,
    padding: `${tokens.spacingVerticalXXL} ${tokens.spacingHorizontalXL}`,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    color: tokens.colorNeutralForeground2,
  },
  compact: {
    padding: `${tokens.spacingVerticalL} ${tokens.spacingHorizontalM}`,
    backgroundColor: 'transparent',
    border: 'none',
    borderRadius: 0,
  },
  icon: {
    display: 'grid',
    placeItems: 'center',
    width: '48px',
    height: '48px',
    borderRadius: tokens.borderRadiusCircular,
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground3,
    fontSize: '24px',
    '& svg': { width: '24px', height: '24px' },
  },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  body: { margin: 0, maxWidth: '52ch', color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase300 },
  action: {
    display: 'flex',
    flexWrap: 'wrap',
    justifyContent: 'center',
    columnGap: space.inline,
    rowGap: space.tight,
    marginTop: tokens.spacingVerticalS,
  },
});

/**
 * Leerer Zustand: Symbol, Titel, ein Satz, optional eine Hauptaktion. `compact` ohne eigene Karte
 * (innerhalb einer Section, Titel dann als `<h3>`).
 */
export function EmptyState(props: {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}): JSX.Element {
  const styles = useStyles();
  const Heading = props.compact ? 'h3' : 'h2';
  return (
    <div className={mergeClasses(styles.root, props.compact && styles.compact)} role="status">
      <div className={styles.icon} aria-hidden="true">
        {props.icon ?? <Sparkle24Regular />}
      </div>
      <Heading className={styles.title}>{props.title}</Heading>
      {props.body ? <div className={styles.body}>{props.body}</div> : null}
      {props.action ? <div className={styles.action}>{props.action}</div> : null}
    </div>
  );
}
