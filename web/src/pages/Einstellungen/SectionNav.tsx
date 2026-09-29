/** Seitenleiste der Einstellungsseite: Suchfeld und Sprungliste zu den Karten (ab 1024 px sichtbar). */
import { Input, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { Search20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';

const useStyles = makeStyles({
  root: {
    display: 'none',
    '@media (min-width: 1024px)': {
      display: 'flex',
      flexDirection: 'column',
      rowGap: tokens.spacingVerticalM,
      position: 'sticky',
      top: tokens.spacingVerticalL,
      alignSelf: 'flex-start',
      width: '220px',
      flexShrink: 0,
    },
  },
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, margin: 0, padding: 0, listStyle: 'none' },
  link: {
    display: 'block',
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground2,
    textDecoration: 'none',
    fontSize: tokens.fontSizeBase300,
    cursor: 'pointer',
    ':hover': { backgroundColor: tokens.colorNeutralBackground1Hover },
  },
  linkActive: { backgroundColor: tokens.colorBrandBackground2, color: tokens.colorBrandForeground1, fontWeight: tokens.fontWeightSemibold },
  linkIndent: { paddingLeft: tokens.spacingHorizontalXXL },
});

export interface NavItem {
  id: string;
  title: string;
  /** Unterpunkt (eingerückt), z. B. die Einstellungskarte eines Moduls unter „Module“. */
  indent?: boolean;
}

export function SettingsSearchBox(props: { value: string; onChange: (v: string) => void }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  return (
    <Input
      contentBefore={<Search20Regular aria-hidden="true" />}
      placeholder={t('search')}
      aria-label={t('search')}
      value={props.value}
      onChange={(_e, d) => props.onChange(d.value)}
    />
  );
}

export function SectionNav(props: { items: NavItem[]; activeId?: string | null; onJump: (id: string) => void }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  return (
    <nav className={styles.root} aria-label={t('nav.sections')}>
      <ul className={styles.list}>
        {props.items.map((item) => (
          <li key={item.id}>
            <a
              className={mergeClasses(styles.link, item.indent && styles.linkIndent, props.activeId === item.id && styles.linkActive)}
              href={`#${item.id}`}
              aria-current={props.activeId === item.id ? 'true' : undefined}
              onClick={(e) => {
                e.preventDefault();
                props.onJump(item.id);
              }}
            >
              {item.title}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
