/**
 * Tableiste des Editors: ein Fluent-Tab je Etikett mit Punkt für „ungespeichert“, Schließen-Knopf
 * (nur Maus; Tastatur über Strg+Alt+W und das Kontextmenü), Mittelklick schließt, Kontextmenü,
 * Knopf „Neuer Tab“ und ab sechs Tabs ein Überlaufmenü.
 */
import type { MouseEvent } from 'react';
import {
  Button,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Tab,
  TabList,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Add20Regular, ChevronDown20Regular, Circle12Filled, Dismiss12Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { isTabDirty, type EditorTab } from './useEditorTabs';

/** Ab so vielen Tabs wandern die übrigen ins Überlaufmenü. */
export const VISIBLE_TABS = 5;

const useStyles = makeStyles({
  root: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalXS,
    minWidth: 0,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  list: { minWidth: 0, flexWrap: 'wrap' },
  inner: { display: 'inline-flex', alignItems: 'center', columnGap: tokens.spacingHorizontalXS, maxWidth: '220px' },
  title: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  dot: { display: 'inline-flex', color: tokens.colorPaletteDarkOrangeForeground1, fontSize: tokens.fontSizeBase100 },
  close: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '20px',
    height: '20px',
    borderRadius: tokens.borderRadiusSmall,
    color: tokens.colorNeutralForeground3,
    ':hover': { backgroundColor: tokens.colorSubtleBackgroundHover, color: tokens.colorNeutralForeground1 },
  },
});

export interface EditorTabsProps {
  tabs: EditorTab[];
  activeId: string;
  onSelect(id: string): void;
  onClose(id: string): void;
  onCloseOthers(id: string): void;
  onNew(): void;
}

function visibleTabs(tabs: EditorTab[], activeId: string): { visible: EditorTab[]; hidden: EditorTab[] } {
  if (tabs.length <= VISIBLE_TABS) return { visible: tabs, hidden: [] };
  const visible = tabs.slice(0, VISIBLE_TABS);
  if (!visible.some((t) => t.id === activeId)) {
    const active = tabs.find((t) => t.id === activeId);
    if (active) visible[VISIBLE_TABS - 1] = active;
  }
  const shown = new Set(visible.map((t) => t.id));
  return { visible, hidden: tabs.filter((t) => !shown.has(t.id)) };
}

export function EditorTabs(props: EditorTabsProps): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const { visible, hidden } = visibleTabs(props.tabs, props.activeId);

  const tabLabel = (tab: EditorTab) => (isTabDirty(tab) ? t('tabs.unsaved', { title: tab.title }) : tab.title);

  const onAux = (id: string) => (e: MouseEvent) => {
    if (e.button !== 1) return;
    e.preventDefault();
    props.onClose(id);
  };

  return (
    <div className={styles.root}>
      <TabList
        className={styles.list}
        appearance="subtle"
        size="small"
        selectedValue={props.activeId}
        onTabSelect={(_e, d) => props.onSelect(String(d.value))}
        aria-label={t('tabs.list')}
      >
        {visible.map((tab) => (
          <Menu key={tab.id} openOnContext>
            <MenuTrigger disableButtonEnhancement>
              <Tab
                value={tab.id}
                aria-label={tabLabel(tab)}
                onAuxClick={onAux(tab.id)}
                onMouseDown={(e) => {
                  // Mittelklick: kein automatisches Scrollen
                  if (e.button === 1) e.preventDefault();
                }}
              >
                <span className={styles.inner}>
                  <span className={styles.title}>{tab.title}</span>
                  {isTabDirty(tab) ? (
                    <span className={styles.dot} aria-hidden="true">
                      <Circle12Filled />
                    </span>
                  ) : null}
                  <span
                    className={styles.close}
                    role="button"
                    aria-hidden="true"
                    aria-label={t('tabs.close', { title: tab.title })}
                    title={t('tabs.close', { title: tab.title })}
                    onClick={(e) => {
                      e.stopPropagation();
                      props.onClose(tab.id);
                    }}
                  >
                    <Dismiss12Regular />
                  </span>
                </span>
              </Tab>
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                <MenuItem onClick={() => props.onClose(tab.id)}>{t('tabs.menuClose')}</MenuItem>
                <MenuItem disabled={props.tabs.length < 2} onClick={() => props.onCloseOthers(tab.id)}>
                  {t('tabs.menuCloseOthers')}
                </MenuItem>
                <MenuItem onClick={props.onNew}>{t('tabs.menuNew')}</MenuItem>
              </MenuList>
            </MenuPopover>
          </Menu>
        ))}
      </TabList>
      {hidden.length ? (
        <Menu>
          <MenuTrigger disableButtonEnhancement>
            <Tooltip content={t('tabs.more')} relationship="label">
              <Button appearance="subtle" size="small" icon={<ChevronDown20Regular />} iconPosition="after">
                {`+${hidden.length}`}
              </Button>
            </Tooltip>
          </MenuTrigger>
          <MenuPopover>
            <MenuList>
              {hidden.map((tab) => (
                <MenuItem key={tab.id} onClick={() => props.onSelect(tab.id)} icon={isTabDirty(tab) ? <Circle12Filled className={styles.dot} /> : undefined}>
                  {tabLabel(tab)}
                </MenuItem>
              ))}
            </MenuList>
          </MenuPopover>
        </Menu>
      ) : null}
      <Tooltip content={t('toolbar.withKey', { label: t('tabs.new'), key: t('keys.newTab') })} relationship="description">
        <Button appearance="subtle" size="small" icon={<Add20Regular />} aria-label={t('tabs.new')} onClick={props.onNew} />
      </Tooltip>
    </div>
  );
}
