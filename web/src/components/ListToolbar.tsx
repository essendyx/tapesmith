/**
 * Werkzeugleiste über einer Liste: links Suche und Filter, rechts die Aktionen der Liste
 * (z. B. „Neu“). Auf schmalen Bildschirmen umbrechend, Suche dann über die volle Breite.
 */
import type { ReactNode } from 'react';
import { makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { space } from '../theme/layout';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
    marginBottom: space.field,
    minWidth: 0,
  },
  start: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
    flex: '1 1 320px',
    minWidth: 0,
  },
  end: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'flex-end',
    columnGap: space.inline,
    rowGap: tokens.spacingVerticalS,
    marginLeft: 'auto',
  },
});

/** Einheitliche Breite des Suchfelds in einer Werkzeugleiste (Klasse für `Input`/`SearchBox`). */
export const useToolbarSearchStyles = makeStyles({
  search: { flex: '1 1 240px', maxWidth: '420px', minWidth: 0 },
});

export function ListToolbar(props: {
  /** Suche und Filter (links). */
  children?: ReactNode;
  /** Aktionen der Liste (rechts). */
  actions?: ReactNode;
  label?: string;
  className?: string;
}): JSX.Element {
  const styles = useStyles();
  return (
    <div className={mergeClasses(styles.root, props.className)} role={props.label ? 'group' : undefined} aria-label={props.label}>
      {props.children ? <div className={styles.start}>{props.children}</div> : null}
      {props.actions ? <div className={styles.end}>{props.actions}</div> : null}
    </div>
  );
}
