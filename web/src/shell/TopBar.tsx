/**
 * Kopfzeile: dezenter Pfad statt eines zweiten Seitentitels (den `<h1>` liefert die Seite),
 * rechts Statusanzeige, Tastenkürzel-Übersicht und Kommandopalette.
 */
import { Fragment } from 'react';
import { Button, Tooltip, makeStyles, tokens } from '@fluentui/react-components';
import { Keyboard20Regular, Navigation20Regular, Search20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useCommands } from '../commands/CommandProvider';
import { ariaCombo, formatCombo } from '../commands/shortcuts';
import type { Crumb } from '../routes';
import { StatusChip } from './StatusChip';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalM,
    height: '52px',
    flexShrink: 0,
    padding: `0 ${tokens.spacingHorizontalXL}`,
    backgroundColor: tokens.colorNeutralBackground2,
    '@media (max-width: 639px)': { padding: `0 ${tokens.spacingHorizontalM}`, columnGap: tokens.spacingHorizontalS },
  },
  path: { flexGrow: 1, minWidth: 0 },
  list: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalXS,
    margin: 0,
    padding: 0,
    listStyleType: 'none',
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    color: tokens.colorNeutralForeground3,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
  },
  crumb: { display: 'inline-flex', alignItems: 'center', columnGap: tokens.spacingHorizontalXS, minWidth: 0 },
  current: { overflow: 'hidden', textOverflow: 'ellipsis', color: tokens.colorNeutralForeground3 },
  link: {
    color: tokens.colorNeutralForeground3,
    textDecorationLine: 'none',
    borderRadius: tokens.borderRadiusSmall,
    ':hover': { color: tokens.colorNeutralForeground2, textDecorationLine: 'underline' },
  },
  separator: { color: tokens.colorNeutralForeground4 },
  right: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalXS, flexShrink: 0 },
  palette: { color: tokens.colorNeutralForeground2, fontWeight: tokens.fontWeightRegular },
  kbd: {
    marginLeft: tokens.spacingHorizontalXS,
    fontFamily: tokens.fontFamilyBase,
    fontSize: tokens.fontSizeBase100,
    padding: `0 ${tokens.spacingHorizontalXS}`,
    borderRadius: tokens.borderRadiusSmall,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    color: tokens.colorNeutralForeground3,
  },
});

export function TopBar(props: { crumbs: Crumb[]; onMenu?: () => void; compact?: boolean }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const commands = useCommands();
  const paletteKeys = formatCombo('Ctrl+K');
  const last = props.crumbs.length - 1;
  return (
    <header className={styles.root}>
      {props.onMenu ? (
        <Tooltip content={t('nav.menu')} relationship="label">
          <Button appearance="subtle" icon={<Navigation20Regular />} onClick={props.onMenu} />
        </Tooltip>
      ) : null}
      <nav className={styles.path} aria-label={t('topbar.breadcrumb')}>
        <ol className={styles.list} aria-live="polite">
          {props.crumbs.map((c, i) => (
            <Fragment key={c.path}>
              {i > 0 ? (
                <li className={styles.separator} aria-hidden="true">
                  {t('topbar.separator')}
                </li>
              ) : null}
              <li className={styles.crumb}>
                {i === last ? (
                  <span className={styles.current} data-testid="page-title" aria-current="page">
                    {c.label}
                  </span>
                ) : (
                  <Link to={c.path} className={styles.link}>
                    {c.label}
                  </Link>
                )}
              </li>
            </Fragment>
          ))}
        </ol>
      </nav>
      <div className={styles.right}>
        <StatusChip />
        <Tooltip content={t('topbar.shortcutsTooltip')} relationship="description">
          <Button
            appearance="subtle"
            icon={<Keyboard20Regular />}
            onClick={() => commands.openShortcuts()}
            aria-label={t('topbar.shortcuts')}
            aria-keyshortcuts="?"
            data-testid="shortcuts-button"
          />
        </Tooltip>
        <Button
          appearance="subtle"
          className={styles.palette}
          icon={<Search20Regular />}
          onClick={() => commands.open()}
          aria-label={t('topbar.commandsLabel', { shortcut: paletteKeys })}
          aria-keyshortcuts={ariaCombo('Ctrl+K')}
        >
          {props.compact ? null : (
            <>
              {t('topbar.commands')} <kbd className={styles.kbd}>{paletteKeys}</kbd>
            </>
          )}
        </Button>
      </div>
    </header>
  );
}
