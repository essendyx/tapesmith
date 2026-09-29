import {
  Button,
  makeStyles,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../api/client';
import { translateOr } from '../i18n';

const useStyles = makeStyles({
  body: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS },
  message: { overflowWrap: 'anywhere' },
  hint: { color: tokens.colorNeutralForeground2 },
});

export interface ErrorText {
  title: string;
  message: string;
  hint: string;
  code: string;
}

/** Codes ohne eigene Aussage: hier gewinnt ein von der Seite übergebener Titel. */
const GENERIC_CODES = new Set(['http.error', 'internal']);

function describe(error: unknown, fallbackTitle?: string): ErrorText {
  if (error instanceof ApiError) {
    const code = error.code || 'http.error';
    const pageTitle = fallbackTitle && GENERIC_CODES.has(code) ? fallbackTitle : undefined;
    const title = pageTitle ?? translateOr(`errors:${code}.title`, fallbackTitle ?? error.message);
    // Meldung und Hinweis kommen vom Dienst schon in der Sprache der Anfrage (Kopfzeile
    // `X-Tapesmith-Language`); ohne eigenen Hinweis gilt die Übersetzung des Codes.
    const message = error.message && error.message !== title ? error.message : '';
    const hint = error.hint || translateOr(`errors:${code}.hint`, '');
    return { title, message, hint, code };
  }
  const title = fallbackTitle ?? translateOr('errors:internal.title', 'Error');
  const text = error instanceof Error ? error.message : String(error);
  return { title, message: text !== title ? text : '', hint: translateOr('errors:internal.hint', ''), code: 'internal' };
}

/** Titel, Meldung, Hinweis und Code eines Fehlers in der aktuellen Sprache (rendert bei Sprachwechsel neu). */
export function useErrorText(): (error: unknown) => ErrorText {
  // useTranslation sorgt für das Neu-Rendern bei einem Sprachwechsel.
  useTranslation('errors');
  return describe;
}

/** Fehlermeldung (MessageBar): Titel aus dem Fehlercode, Server-Meldung, Hinweis, optional „Erneut versuchen“. */
export function ErrorMessage(props: { error: unknown; title?: string; onRetry?: () => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('common');
  useTranslation('errors');
  const text = describe(props.error, props.title);
  return (
    <MessageBar intent="error" layout="multiline" data-error-code={text.code}>
      <MessageBarBody className={styles.body}>
        <MessageBarTitle>{text.title}</MessageBarTitle>
        {text.message ? <div className={styles.message}>{text.message}</div> : null}
        {text.hint ? <div className={styles.hint}>{text.hint}</div> : null}
      </MessageBarBody>
      {props.onRetry ? (
        <MessageBarActions>
          <Button appearance="secondary" size="small" onClick={props.onRetry}>
            {t('actions.retry')}
          </Button>
        </MessageBarActions>
      ) : null}
    </MessageBar>
  );
}
