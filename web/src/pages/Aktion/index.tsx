/** /aktion: löst Kontextmenü- und URI-Aktionen auf (Server: `webapi.actions`) und leitet weiter. */
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '@fluentui/react-components';
import { ErrorCircle48Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { ApiError, apiPost } from '../../api/client';
import type { ActionJson } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { Section } from '../../components/Section';
import { useNotify } from '../../components/NotifyProvider';

export default function AktionPage(): JSX.Element {
  const { t } = useTranslation('aktion');
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const notify = useNotify();
  const [error, setError] = useState<ApiError | null>(null);
  const started = useRef<string | null>(null);
  const uri = params.get('uri');
  const open = params.get('open');
  const path = params.get('path');
  const key = JSON.stringify([uri, open, path]);

  useEffect(() => {
    if (started.current === key) return;
    started.current = key;
    const body: { uri?: string; open?: string; path?: string } = {};
    if (uri) body.uri = uri;
    if (open) body.open = open;
    if (path) body.path = path;
    if (!uri && !open) {
      setError(new ApiError(422, 'Validierung', t('error.noAction'), t('error.noActionHint')));
      return;
    }
    apiPost<ActionJson>('/api/v1/integration/resolve', body).then(
      (action) => {
        if (action.note) notify({ intent: 'info', title: action.note });
        navigate(action.route || '/schnelldruck', { replace: true });
      },
      (err: unknown) => {
        setError(err instanceof ApiError ? err : new ApiError(0, 'Fehler', String(err))); // i18n-ignore (interne Fehlerart, keine Anzeige)
      },
    );
    // t ist stabil zwischen Sprachwechseln (i18next-Instanz); nur die Query steuert den Effekt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, uri, open, path, navigate, notify]);

  return (
    <>
      <PageHeader title={t('title')} />
      <Section>
        {error ? (
          <EmptyState
            icon={<ErrorCircle48Regular />}
            title={error.message}
            body={error.hint || t('error.fallbackHint')}
            action={
              <Button appearance="primary" onClick={() => navigate('/schnelldruck', { replace: true })}>
                {t('backAction')}
              </Button>
            }
          />
        ) : (
          <LoadingState variant="section" label={t('loading')} />
        )}
      </Section>
    </>
  );
}
