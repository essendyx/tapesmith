/** Meldungen (Toasts) über Fluent `Toaster`. */
import { createContext, useCallback, useContext, useId, type ReactNode } from 'react';
import {
  Toast,
  ToastBody,
  Toaster,
  ToastFooter,
  ToastTitle,
  makeStyles,
  tokens,
  useToastController,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';

export interface Notification {
  intent: 'success' | 'info' | 'warning' | 'error';
  title: string;
  body?: string;
  hint?: string;
}

type NotifyFn = (n: Notification) => void;

const NotifyContext = createContext<NotifyFn | null>(null);

const useStyles = makeStyles({
  hint: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  body: { whiteSpace: 'pre-line' },
});

export function NotifyProvider(props: { children: ReactNode }): JSX.Element {
  const toasterId = useId();
  const { dispatchToast } = useToastController(toasterId);
  const styles = useStyles();
  const { t } = useTranslation('components');
  const notify = useCallback<NotifyFn>(
    (n) => {
      dispatchToast(
        <Toast>
          <ToastTitle>{n.title}</ToastTitle>
          {n.body ? <ToastBody className={styles.body}>{n.body}</ToastBody> : null}
          {n.hint ? (
            <ToastFooter>
              <span className={styles.hint}>{n.hint}</span>
            </ToastFooter>
          ) : null}
        </Toast>,
        { intent: n.intent, timeout: n.intent === 'error' ? 9000 : n.intent === 'warning' ? 7000 : 4000, politeness: n.intent === 'error' ? 'assertive' : 'polite' },
      );
    },
    [dispatchToast, styles.body, styles.hint],
  );
  return (
    <NotifyContext.Provider value={notify}>
      {props.children}
      <Toaster
        toasterId={toasterId}
        position="bottom-end"
        pauseOnHover
        pauseOnWindowBlur
        limit={4}
        aria-label={t('notify.region')}
      />
    </NotifyContext.Provider>
  );
}

export function useNotify(): NotifyFn {
  const ctx = useContext(NotifyContext);
  if (!ctx) throw new Error('useNotify without NotifyProvider');
  return ctx;
}
