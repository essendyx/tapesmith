/** Karte „MCP für Claude“: HTTP-Schalter, Adresse und stdio-Befehl mit Kopieren. */
import { Body1, Button, Field, Input, MessageBar, MessageBarBody, Switch, makeStyles, tokens } from '@fluentui/react-components';
import { Copy20Regular } from '@fluentui/react-icons';
import { Trans, useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import { useNotify } from '../../components/NotifyProvider';
import type { AccessJson, AccessMcp } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

const useStyles = makeStyles({
  grid: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  // Lange Befehle und Adressen in <code> umbrechen statt die Karte auf dem Handy zu sprengen.
  wrap: { overflowWrap: 'anywhere' },
  copyRow: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
});

export function McpCard(props: { data: AccessJson }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const notify = useNotify();
  const edit = useSectionEdit<AccessMcp>(props.data.mcp);
  const { save, saving, error } = useAccessSave();
  const v = edit.values;

  const onSave = async () => {
    const ok = await save(edit.changes('mcp'), t('mcp.saveSuccess'));
    if (ok) edit.discard();
  };

  const copy = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      notify({ intent: 'success', title: t('newToken.copied', { label }) });
    } catch {
      notify({ intent: 'error', title: t('newToken.copyFailed') });
    }
  };

  return (
    <Section
      id="mcp"
      title={t('mcp.title')}
      actions={
        edit.dirty ? (
          <>
            <Button appearance="primary" disabled={saving} aria-busy={saving} onClick={() => void onSave()}>
              {t('common:actions.save')}
            </Button>
            <Button appearance="secondary" disabled={saving} onClick={edit.discard}>
              {t('common:actions.cancel')}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className={styles.grid}>
        <Field label={t('mcp.httpLabel')}>
          <Switch checked={v.http} onChange={(_e, d) => edit.set('http', d.checked)} />
        </Field>
        <Field label={t('mcp.addressLabel')}>
          <div className={styles.copyRow}>
            <Input readOnly value={v.url} />
            <Button icon={<Copy20Regular />} aria-label={t('mcp.copyAddressAria')} onClick={() => void copy(v.url, t('mcp.addressLabel'))}>
              {t('common:actions.copy')}
            </Button>
          </div>
        </Field>
        <Field label={t('mcp.commandLabel')}>
          <div className={styles.copyRow}>
            <Input readOnly value={v.stdio_command} />
            <Button
              icon={<Copy20Regular />}
              aria-label={t('mcp.copyCommandAria')}
              onClick={() => void copy(v.stdio_command, t('mcp.commandLabel'))}
            >
              {t('common:actions.copy')}
            </Button>
          </div>
        </Field>
        <Body1 className={styles.wrap}>
          <Trans i18nKey="zugriff:mcp.claudeCodeHint" values={{ command: v.stdio_command }} components={{ code: <code /> }} />
        </Body1>
        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}
      </div>
    </Section>
  );
}
