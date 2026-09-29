/** Sprungmarke „Zum Inhalt springen“: erstes fokussierbares Element, nur bei Fokus sichtbar. */
import { makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';

export const CONTENT_ID = 'inhalt';

const useStyles = makeStyles({
  link: {
    position: 'absolute',
    top: tokens.spacingVerticalS,
    left: tokens.spacingHorizontalS,
    zIndex: 1000,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalL}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorBrandForegroundLink,
    boxShadow: tokens.shadow16,
    fontWeight: tokens.fontWeightSemibold,
    textDecorationLine: 'none',
    transform: 'translateY(-200%)',
    ':focus': { transform: 'none', outline: `${tokens.strokeWidthThick} solid ${tokens.colorStrokeFocus2}` },
    '@media (forced-colors: active)': { border: `${tokens.strokeWidthThin} solid CanvasText` },
  },
});

export function SkipLink(props: { targetId?: string }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const target = props.targetId ?? CONTENT_ID;
  return (
    <a
      className={styles.link}
      href={`#${target}`}
      onClick={(e) => {
        e.preventDefault();
        const el = document.getElementById(target);
        if (el) {
          el.focus();
          el.scrollIntoView?.({ block: 'start' });
        }
      }}
    >
      {t('skipLink')}
    </a>
  );
}
