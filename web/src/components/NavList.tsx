/**
 * Senkrechte Auswahlliste (Vorlagen, Vault-Notizen): ein Eintrag je Zeile über die volle Breite,
 * linksbündig, der gewählte Eintrag dezent hervorgehoben (Hintergrund, Markierung links, halbfett)
 * statt als blauer Hauptknopf. Jeder Eintrag ist ein Knopf mit `aria-current`, damit Tastatur und
 * Screenreader den gewählten Eintrag erkennen.
 */
import { useId } from 'react';
import { Button, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';

export interface NavListItem {
  key: string;
  label: string;
  /** Optionale Zweitzeile (einzeilig gekürzt, voller Text als Tooltip und Beschreibung). */
  description?: string;
}

const useStyles = makeStyles({
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, minWidth: 0 },
  item: {
    justifyContent: 'flex-start',
    textAlign: 'left',
    width: '100%',
    minWidth: 0,
    fontWeight: tokens.fontWeightRegular,
    position: 'relative',
    overflowWrap: 'anywhere',
  },
  /** Zweizeilige Einträge: Titel und gedämpfte Beschreibung untereinander. */
  itemTwoLine: { paddingTop: tokens.spacingVerticalS, paddingBottom: tokens.spacingVerticalS, alignItems: 'flex-start' },
  text: { display: 'flex', flexDirection: 'column', rowGap: '2px', minWidth: 0, width: '100%' },
  description: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightRegular,
    lineHeight: tokens.lineHeightBase200,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  selected: {
    backgroundColor: tokens.colorNeutralBackground1Selected,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    '::before': {
      content: '""',
      position: 'absolute',
      left: 0,
      top: '6px',
      bottom: '6px',
      width: '3px',
      borderRadius: tokens.borderRadiusCircular,
      backgroundColor: tokens.colorCompoundBrandStroke,
    },
  },
});

export function NavList(props: {
  items: NavListItem[];
  selected: string | null | undefined;
  onSelect: (key: string) => void;
  label?: string;
  className?: string;
}): JSX.Element {
  const styles = useStyles();
  const idBase = useId();
  return (
    <div className={mergeClasses(styles.list, props.className)} role={props.label ? 'group' : undefined} aria-label={props.label}>
      {props.items.map((item) => {
        const active = item.key === props.selected;
        return (
          item.description ? (
            <Button
              key={item.key}
              appearance="subtle"
              className={mergeClasses(styles.item, styles.itemTwoLine, active && styles.selected)}
              aria-current={active ? 'true' : undefined}
              aria-labelledby={`${idBase}-${item.key}-l`}
              aria-describedby={`${idBase}-${item.key}-d`}
              title={item.description}
              onClick={() => props.onSelect(item.key)}
            >
              <span className={styles.text}>
                <span id={`${idBase}-${item.key}-l`}>{item.label}</span>
                <span id={`${idBase}-${item.key}-d`} className={styles.description}>
                  {item.description}
                </span>
              </span>
            </Button>
          ) : (
            <Button
              key={item.key}
              appearance="subtle"
              className={mergeClasses(styles.item, active && styles.selected)}
              aria-current={active ? 'true' : undefined}
              onClick={() => props.onSelect(item.key)}
            >
              {item.label}
            </Button>
          )
        );
      })}
    </div>
  );
}
