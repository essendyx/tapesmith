/**
 * Zeilenaktionen einer Liste oder Tabelle nach einem einheitlichen Muster: höchstens EIN
 * sichtbarer Hauptknopf (z. B. „Nachdrucken“), alle weiteren Aktionen in einem „Mehr“-Menü
 * (Fluent Menu, Symbol MoreHorizontal). Der Menüknopf trägt den Zeilentitel im zugänglichen
 * Namen („Weitere Aktionen für pmx10“), damit jede Zeile eindeutig ansprechbar bleibt; das Menü
 * ist vollständig per Tastatur bedienbar (Enter/Leertaste öffnet, Pfeiltasten wählen, Escape schließt).
 * Einträge mit `items` öffnen ein Untermenü (z. B. Export als PNG, PDF oder PBM).
 */
import type { ReactNode } from 'react';
import {
  Button,
  Menu,
  MenuDivider,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { MoreHorizontal20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';

export interface RowAction {
  /** Stabiler Schlüssel (auch für Tests). */
  key: string;
  label: string;
  icon?: JSX.Element;
  onClick?: () => void;
  disabled?: boolean;
  /** Gefährliche Aktion (Löschen, Abbrechen): rot und durch einen Trenner abgesetzt am Ende. */
  danger?: boolean;
  /** Untermenü statt eigener Aktion. */
  items?: RowAction[];
  /** Ausblenden, ohne die Reihenfolge der übrigen Einträge zu ändern. */
  hidden?: boolean;
}

const useStyles = makeStyles({
  root: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    columnGap: tokens.spacingHorizontalXS,
    flexWrap: 'nowrap',
  },
  danger: { color: tokens.colorPaletteRedForeground1 },
});

function ActionItem(props: { action: RowAction; dangerClass: string }): JSX.Element {
  const { action } = props;
  const visibleSub = (action.items ?? []).filter((a) => !a.hidden);
  if (visibleSub.length > 0) {
    return (
      <Menu>
        <MenuTrigger disableButtonEnhancement>
          <MenuItem icon={action.icon} disabled={action.disabled}>
            {action.label}
          </MenuItem>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            {visibleSub.map((sub) => (
              <ActionItem key={sub.key} action={sub} dangerClass={props.dangerClass} />
            ))}
          </MenuList>
        </MenuPopover>
      </Menu>
    );
  }
  return (
    <MenuItem
      icon={action.icon}
      disabled={action.disabled}
      className={action.danger ? props.dangerClass : undefined}
      data-action={action.key}
      onClick={() => {
        // Erst schließen lassen (Fokus zurück auf den Menüknopf), dann die Aktion: ein Dialog, den
        // sie öffnet, gibt den Fokus beim Schließen so an den Menüknopf der Zeile zurück.
        if (action.onClick) setTimeout(action.onClick, 0);
      }}
    >
      {action.label}
    </MenuItem>
  );
}

/**
 * `title` ist der Titel der Zeile (für den zugänglichen Namen des Menüknopfs), `primary` der eine
 * sichtbare Hauptknopf, `actions` die Einträge des „Mehr“-Menüs. Ohne Einträge entfällt der Menüknopf.
 */
export function RowActions(props: { title: string; primary?: ReactNode; actions?: RowAction[] }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('common');
  const visible = (props.actions ?? []).filter((a) => !a.hidden);
  const normal = visible.filter((a) => !a.danger);
  const danger = visible.filter((a) => a.danger);
  const label = t('rowActions.more', { title: props.title });
  return (
    <div className={styles.root}>
      {props.primary}
      {visible.length > 0 ? (
        <Menu positioning={{ position: 'below', align: 'end' }}>
          <MenuTrigger disableButtonEnhancement>
            <Tooltip content={t('rowActions.tooltip')} relationship="description" withArrow>
              <Button appearance="subtle" icon={<MoreHorizontal20Regular />} aria-label={label} />
            </Tooltip>
          </MenuTrigger>
          <MenuPopover>
            <MenuList aria-label={label}>
              {normal.map((a) => (
                <ActionItem key={a.key} action={a} dangerClass={styles.danger} />
              ))}
              {normal.length > 0 && danger.length > 0 ? <MenuDivider /> : null}
              {danger.map((a) => (
                <ActionItem key={a.key} action={a} dangerClass={styles.danger} />
              ))}
            </MenuList>
          </MenuPopover>
        </Menu>
      ) : null}
    </div>
  );
}
