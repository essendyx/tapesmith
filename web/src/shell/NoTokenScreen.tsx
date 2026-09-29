/** Vollflächige Hinweiskarten: ohne Token, Sitzung abgelaufen, Dienst nicht erreichbar. */
import { useEffect, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { Button, Checkbox, Field, Input, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowClockwise20Regular, LockClosed48Regular, PlugDisconnected48Regular } from '@fluentui/react-icons';
import { Trans, useTranslation } from 'react-i18next';
import { clearToken, setToken } from '../api/client';
import { isAppWindow, reconnectService } from '../platform';
import { motion } from '../theme/motion';
import { FONT_FAMILY_DISPLAY } from '../theme/ThemeProvider';

const useStyles = makeStyles({
  page: {
    minHeight: '100%',
    display: 'grid',
    placeItems: 'center',
    padding: tokens.spacingHorizontalXXL,
    boxSizing: 'border-box',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  card: {
    width: 'min(460px, 100%)',
    boxSizing: 'border-box',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    textAlign: 'center',
    rowGap: tokens.spacingVerticalL,
    padding: `${tokens.spacingVerticalXXXL} ${tokens.spacingHorizontalXXXL}`,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow16,
    ...motion.slideUp,
    '@media (forced-colors: active)': { border: `${tokens.strokeWidthThin} solid CanvasText` },
  },
  icon: {
    display: 'grid',
    placeItems: 'center',
    width: '80px',
    height: '80px',
    borderRadius: tokens.borderRadiusCircular,
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground1,
  },
  title: {
    margin: 0,
    fontFamily: FONT_FAMILY_DISPLAY,
    fontSize: tokens.fontSizeBase600,
    lineHeight: tokens.lineHeightBase600,
    fontWeight: tokens.fontWeightSemibold,
  },
  body: { margin: 0, color: tokens.colorNeutralForeground2, lineHeight: tokens.lineHeightBase400 },
  code: {
    fontFamily: tokens.fontFamilyMonospace,
    padding: `1px ${tokens.spacingHorizontalXS}`,
    borderRadius: tokens.borderRadiusSmall,
    backgroundColor: tokens.colorNeutralBackground3,
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalM,
    width: '100%',
    textAlign: 'left',
  },
});

export function CenteredCard(props: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }): JSX.Element {
  const styles = useStyles();
  return (
    <div className={styles.page}>
      <div className={styles.card} role="alert">
        <div className={styles.icon} aria-hidden="true">
          {props.icon}
        </div>
        <h1 className={styles.title}>{props.title}</h1>
        {props.children}
        {props.action ?? null}
      </div>
    </div>
  );
}

/**
 * Im App-Fenster: startet den Druckdienst neu und lädt die Oberfläche mit frischem Token auf der
 * aktuellen Route. `null` im Browser (dort gibt es keine Brücke zum Fenster-Prozess).
 */
function useReconnect(): { run: () => void; busy: boolean } | null {
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  if (!isAppWindow()) return null;
  return {
    busy,
    run: () => {
      setBusy(true);
      void reconnectService(location.pathname + location.search).finally(() => setBusy(false));
    },
  };
}

/**
 * Anmeldeformular für die Nutzung aus dem LAN (ohne App-Fenster): Zugangstoken eingeben, optional
 * auf diesem Gerät merken. `onLogin` lädt die Oberfläche standardmäßig neu, damit die Sitzung mit
 * dem frisch gesetzten Token startet (in Tests austauschbar).
 */
function LoginForm(props: { onLogin: () => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const [value, setValue] = useState('');
  const [remember, setRemember] = useState(false);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setToken(trimmed, remember);
    props.onLogin();
  };

  return (
    <form
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <Field label={t('noToken.tokenField')}>
        <Input type="password" value={value} onChange={(_e, d) => setValue(d.value)} autoComplete="off" />
      </Field>
      <Checkbox
        label={t('noToken.remember')}
        checked={remember}
        onChange={(_e, d) => setRemember(Boolean(d.checked))}
      />
      <Button appearance="primary" type="submit" disabled={value.trim() === ''}>
        {t('noToken.login')}
      </Button>
      <p className={styles.body}>
        <Trans i18nKey="shell:noToken.tokenHint" components={{ code: <code className={styles.code} /> }} />
      </p>
    </form>
  );
}

export function NoTokenScreen(props: { expired?: boolean; onLogin?: () => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const reconnect = useReconnect();
  const onLogin = props.onLogin ?? (() => window.location.reload());
  const [showForm, setShowForm] = useState(!props.expired);

  if (isAppWindow()) {
    return (
      <CenteredCard
        icon={<LockClosed48Regular />}
        title={props.expired ? t('noToken.expired') : t('noToken.openViaApp')}
        action={
          reconnect ? (
            <Button appearance="primary" icon={<ArrowClockwise20Regular />} onClick={reconnect.run} disabled={reconnect.busy}>
              {t('noToken.reconnect')}
            </Button>
          ) : undefined
        }
      >
        <p className={styles.body}>
          {props.expired ? t('noToken.appExpired') : t('noToken.appNeedsSession')}{' '}
          <Trans i18nKey="shell:noToken.appStart" components={{ code: <code className={styles.code} /> }} />
        </p>
      </CenteredCard>
    );
  }

  return (
    <CenteredCard icon={<LockClosed48Regular />} title={props.expired ? t('noToken.expired') : t('noToken.loginNeeded')}>
      {props.expired ? (
        <>
          <p className={styles.body}>{t('noToken.tokenInvalid')}</p>
          {!showForm ? (
            <Button
              appearance="secondary"
              onClick={() => {
                clearToken();
                setShowForm(true);
              }}
            >
              {t('noToken.otherToken')}
            </Button>
          ) : null}
        </>
      ) : (
        <p className={styles.body}>{t('noToken.needsToken')}</p>
      )}
      {showForm ? <LoginForm onLogin={onLogin} /> : null}
    </CenteredCard>
  );
}

export function OfflineScreen(props: { onRetry: () => void; retrying?: boolean }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const { onRetry } = props;
  const reconnect = useReconnect();
  useEffect(() => {
    const timer = setInterval(onRetry, 3000);
    return () => clearInterval(timer);
  }, [onRetry]);
  return (
    <CenteredCard
      icon={<PlugDisconnected48Regular />}
      title={t('offline.title')}
      action={
        <Button
          appearance="primary"
          icon={<ArrowClockwise20Regular />}
          onClick={reconnect ? reconnect.run : onRetry}
          disabled={props.retrying || reconnect?.busy}
        >
          {t('offline.retry')}
        </Button>
      }
    >
      <p className={styles.body}>
        {reconnect ? (
          t('offline.appHint')
        ) : (
          <Trans i18nKey="shell:offline.browserHint" components={{ code: <code className={styles.code} /> }} />
        )}
      </p>
    </CenteredCard>
  );
}
