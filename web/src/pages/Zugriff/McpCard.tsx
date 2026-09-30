/** Karte „MCP für Claude“: HTTP-Schalter, Adresse und stdio-Befehl mit Kopieren. */
import { useId } from 'react';
import { Input, MessageBar, MessageBarBody, makeStyles } from '@fluentui/react-components';
import { Copy16Regular } from '@fluentui/react-icons';
import { Trans, useTranslation } from 'react-i18next';
import { FieldRow, FieldRows, InlineAction, ToggleControl } from '../../components/FieldRow';
import { Section } from '../../components/Section';
import { CardActions } from './CardActions';
import type { AccessJson, AccessMcp } from './types';
import { useCopy } from './useCopy';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

const useStyles = makeStyles({
  // Lange Befehle und Adressen in <code> umbrechen statt die Karte auf dem Handy zu sprengen.
  wrap: { overflowWrap: 'anywhere' },
});

export function McpCard(props: { data: AccessJson }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const copy = useCopy();
  const edit = useSectionEdit<AccessMcp>(props.data.mcp);
  const { save, saving, error } = useAccessSave();
  const v = edit.values;
  const idBase = useId();
  const title = t('mcp.title');
  const claudeCommand = `claude mcp add p12 -- ${v.stdio_command}`;

  const onSave = async () => {
    const ok = await save(edit.changes('mcp'), t('mcp.saveSuccess'));
    if (ok) edit.discard();
  };

  return (
    <Section
      id="mcp"
      title={title}
      actions={
        edit.dirty ? (
          <CardActions title={title} dirty={edit.dirty} saving={saving} onSave={() => void onSave()} onDiscard={edit.discard} />
        ) : undefined
      }
    >
      <FieldRows>
        <FieldRow
          htmlFor={`${idBase}-http`}
          label={t('mcp.httpLabel')}
          help={t('mcp.httpHint')}
          align="end"
          control={<ToggleControl id={`${idBase}-http`} checked={v.http} onChange={(on) => edit.set('http', on)} />}
        />
        <FieldRow
          htmlFor={`${idBase}-url`}
          label={t('mcp.addressLabel')}
          help={t('mcp.addressHint')}
          control={
            <Input
              id={`${idBase}-url`}
              readOnly
              value={v.url}
              title={v.url}
              contentAfter={
                <InlineAction label={t('mcp.copyAddressAria')} icon={<Copy16Regular />} onClick={() => void copy(v.url, t('mcp.addressLabel'))} />
              }
            />
          }
        />
        <FieldRow
          htmlFor={`${idBase}-cmd`}
          label={t('mcp.commandLabel')}
          help={
            <span className={styles.wrap}>
              <Trans i18nKey="zugriff:mcp.commandHint" values={{ command: claudeCommand }} components={{ code: <code /> }} />
            </span>
          }
          control={
            <Input
              id={`${idBase}-cmd`}
              readOnly
              value={claudeCommand}
              title={claudeCommand}
              contentAfter={
                <InlineAction
                  label={t('mcp.copyCommandAria')}
                  icon={<Copy16Regular />}
                  onClick={() => void copy(claudeCommand, t('mcp.commandLabel'))}
                />
              }
            />
          }
        />
      </FieldRows>
      {error ? (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      ) : null}
    </Section>
  );
}
