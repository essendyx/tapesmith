/** Seite eines Moduls: ausgeschaltet zeigt sie nur einen Hinweis mit dem Weg zu den Modulen. */
import type { ReactNode } from 'react';
import { Button } from '@fluentui/react-components';
import { PuzzlePiece24Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { EmptyState } from '../components/EmptyState';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { moduleTexts, useModules } from './index';

export const MODULES_SETTINGS_PATH = '/einstellungen?abschnitt=module';

export function ModuleDisabledNotice(props: { module: string }): JSX.Element {
  const { t } = useTranslation('modules');
  const navigate = useNavigate();
  const name = moduleTexts(props.module).name;
  return (
    <>
      <PageHeader title={name} subtitle={moduleTexts(props.module).description} />
      <EmptyState
        icon={<PuzzlePiece24Regular />}
        title={t('gate.title', { name })}
        body={t('gate.body')}
        action={
          <Button appearance="primary" onClick={() => navigate(MODULES_SETTINGS_PATH)}>
            {t('gate.action')}
          </Button>
        }
      />
    </>
  );
}

export function ModuleGate(props: { module: string; children: ReactNode }): JSX.Element {
  const modules = useModules();
  if (!modules.loaded) return <LoadingState variant="page" />;
  if (!modules.isEnabled(props.module)) return <ModuleDisabledNotice module={props.module} />;
  return <>{props.children}</>;
}
