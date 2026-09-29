/**
 * Seitenleiste mit Fluent-NavDrawer: 260 px ausgeklappt, 56 px nur Symbole, unter 640 px als Schublade.
 * Ruhige Fläche wie der Hintergrund, Einträge ohne Kachel (nur Hover- und Auswahlfläche mit Balken).
 */
import {
  Button,
  NavDrawer,
  NavDrawerBody,
  NavDrawerFooter,
  NavDrawerHeader,
  NavDivider,
  NavItem,
  Tooltip,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import { PanelLeftContract20Regular, PanelLeftExpand20Regular, Tag20Filled } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import { findRoute, isRouteVisible, ROUTES, routeShortcut, type RouteDef } from '../routes';
import { useModules } from '../modules';
import { FONT_FAMILY_DISPLAY } from '../theme/ThemeProvider';

export const NAV_WIDTH = 260;
export const NAV_WIDTH_COLLAPSED = 56;

const useStyles = makeStyles({
  drawer: {
    height: '100%',
    backgroundColor: tokens.colorNeutralBackground2,
    borderRight: 'none',
    transitionProperty: 'width, min-width, max-width',
    transitionDuration: '200ms',
    transitionTimingFunction: tokens.curveEasyEase,
    overflow: 'hidden',
    '@media (forced-colors: active)': { borderRight: `${tokens.strokeWidthThin} solid CanvasText` },
  },
  expanded: { width: `${NAV_WIDTH}px`, minWidth: `${NAV_WIDTH}px`, maxWidth: `${NAV_WIDTH}px` },
  collapsed: { width: `${NAV_WIDTH_COLLAPSED}px`, minWidth: `${NAV_WIDTH_COLLAPSED}px`, maxWidth: `${NAV_WIDTH_COLLAPSED}px` },
  header: {
    display: 'flex',
    flexDirection: 'row',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalS} ${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    minHeight: '52px',
    boxSizing: 'border-box',
  },
  headerCollapsed: { justifyContent: 'center', paddingLeft: 0, paddingRight: 0 },
  brand: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalS,
    flexGrow: 1,
    minWidth: 0,
  },
  logo: {
    display: 'grid',
    placeItems: 'center',
    width: '28px',
    height: '28px',
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    flexShrink: 0,
  },
  name: {
    fontFamily: FONT_FAMILY_DISPLAY,
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  toggle: { flexShrink: 0 },
  body: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '2px',
    paddingLeft: tokens.spacingHorizontalS,
    paddingRight: tokens.spacingHorizontalS,
  },
  bodyCollapsed: { paddingLeft: tokens.spacingHorizontalXS, paddingRight: tokens.spacingHorizontalXS },
  item: {
    minHeight: '36px',
    height: '36px',
    boxSizing: 'border-box',
    marginBottom: 0,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorTransparentBackground,
    color: tokens.colorNeutralForeground2,
    whiteSpace: 'nowrap',
    transitionProperty: 'background-color, color',
    transitionDuration: tokens.durationFaster,
    '& svg': { width: '20px', height: '20px', fontSize: '20px' },
    ':hover': { backgroundColor: tokens.colorSubtleBackgroundHover, color: tokens.colorNeutralForeground1 },
    ':active': { backgroundColor: tokens.colorSubtleBackgroundPressed },
    '&[aria-current="page"]': {
      backgroundColor: tokens.colorSubtleBackgroundSelected,
      color: tokens.colorNeutralForeground1,
      fontWeight: tokens.fontWeightSemibold,
    },
  },
  itemCollapsed: { justifyContent: 'center', paddingLeft: 0, paddingRight: 0, columnGap: 0 },
  divider: { marginTop: tokens.spacingVerticalXS, marginBottom: tokens.spacingVerticalXS },
  footer: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '2px',
    paddingLeft: tokens.spacingHorizontalS,
    paddingRight: tokens.spacingHorizontalS,
    paddingBottom: tokens.spacingVerticalM,
    paddingTop: tokens.spacingVerticalS,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke3}`,
    marginLeft: tokens.spacingHorizontalS,
    marginRight: tokens.spacingHorizontalS,
  },
  footerCollapsed: {
    paddingLeft: tokens.spacingHorizontalXXS,
    paddingRight: tokens.spacingHorizontalXXS,
    marginLeft: tokens.spacingHorizontalXS,
    marginRight: tokens.spacingHorizontalXS,
  },
});

export function Sidebar(props: {
  collapsed: boolean;
  onToggle?: () => void;
  canToggle: boolean;
  overlay?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const navigate = useNavigate();
  const location = useLocation();
  const selected = findRoute(location.pathname)?.key;
  const collapsed = props.collapsed && !props.overlay;

  const renderItem = (route: RouteDef) => {
    const isActive = route.key === selected;
    const Icon = isActive ? route.iconActive : route.icon;
    const title = t(route.titleKey);
    const shortcut = routeShortcut(route);
    const item = (
      <NavItem
        key={route.key}
        value={route.key}
        icon={<Icon />}
        className={mergeClasses(styles.item, collapsed && styles.itemCollapsed)}
        onClick={() => {
          navigate(route.path);
          props.onOpenChange?.(false);
        }}
        aria-label={collapsed ? title : undefined}
        data-route={route.key}
      >
        {collapsed ? null : title}
      </NavItem>
    );
    if (!collapsed) return item;
    return (
      <Tooltip
        key={route.key}
        content={shortcut ? t('nav.withShortcut', { title, shortcut }) : title}
        relationship="description"
        positioning="after"
      >
        {item}
      </Tooltip>
    );
  };

  const modules = useModules();
  const visible = ROUTES.filter((r) => isRouteVisible(r, modules));
  const core = visible.filter((r) => !r.bottom && !r.module && !r.homelab);
  // Seiten eingeschalteter Module unter einer Trennlinie nach der Kernapp.
  const moduleRoutes = visible.filter((r) => !r.bottom && (r.module || r.homelab));
  const bottom = visible.filter((r) => r.bottom);
  const toggleLabel = collapsed ? t('nav.expand') : t('nav.collapse');

  return (
    <NavDrawer
      type={props.overlay ? 'overlay' : 'inline'}
      open={props.overlay ? (props.open ?? false) : true}
      onOpenChange={(_e, data) => props.onOpenChange?.(data.open)}
      selectedValue={selected ?? ''}
      className={mergeClasses(styles.drawer, collapsed ? styles.collapsed : styles.expanded)}
      aria-label={t('nav.label')}
      // Als Schublade ist die Leiste ein modaler Dialog (aria-modal ist an role=navigation nicht erlaubt).
      {...(props.overlay ? { role: 'dialog' } : {})}
      density="medium"
    >
      <NavDrawerHeader className={mergeClasses(styles.header, collapsed && styles.headerCollapsed)}>
        {collapsed ? null : (
          <div className={styles.brand}>
            <span className={styles.logo} aria-hidden="true">
              <Tag20Filled />
            </span>
            <span className={styles.name}>{t('appName')}</span>
          </div>
        )}
        {props.canToggle && !props.overlay ? (
          <Tooltip content={toggleLabel} relationship="label">
            <Button
              className={styles.toggle}
              appearance="subtle"
              icon={collapsed ? <PanelLeftExpand20Regular /> : <PanelLeftContract20Regular />}
              onClick={props.onToggle}
              aria-expanded={!collapsed}
            />
          </Tooltip>
        ) : null}
      </NavDrawerHeader>
      <NavDrawerBody className={mergeClasses(styles.body, collapsed && styles.bodyCollapsed)}>
        {core.map(renderItem)}
        {moduleRoutes.length > 0 ? <NavDivider className={styles.divider} /> : null}
        {moduleRoutes.map(renderItem)}
      </NavDrawerBody>
      <NavDrawerFooter className={mergeClasses(styles.footer, collapsed && styles.footerCollapsed)}>
        {bottom.map(renderItem)}
      </NavDrawerFooter>
    </NavDrawer>
  );
}
