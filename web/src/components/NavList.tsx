/**
 * Senkrechte Auswahlliste (Vorlagen, Vault-Notizen): ein Eintrag je Zeile über die volle Breite,
 * linksbündig, der gewählte Eintrag dezent hervorgehoben (Hintergrund, Markierung links, halbfett)
 * statt als blauer Hauptknopf. Jeder Eintrag ist ein Knopf mit `aria-current`, damit Tastatur und
 * Screenreader den gewählten Eintrag erkennen.
 */
import { Button, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';

export interface NavListItem {
  key: string;
  label: string;
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
  return (
    <div className={mergeClasses(styles.list, props.className)} role={props.label ? 'group' : undefined} aria-label={props.label}>
      {props.items.map((item) => {
        const active = item.key === props.selected;
        return (
          <Button
            key={item.key}
            appearance="subtle"
            className={mergeClasses(styles.item, active && styles.selected)}
            aria-current={active ? 'true' : undefined}
            onClick={() => props.onSelect(item.key)}
          >
            {item.label}
          </Button>
        );
      })}
    </div>
  );
}
