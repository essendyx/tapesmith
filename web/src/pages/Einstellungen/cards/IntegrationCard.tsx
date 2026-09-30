/**
 * Karte „Windows-Integration“: Autostart (sichtbar) bzw. Kontextmenü und URI-Schema (unter
 * „Erweitert“). `parts` wählt die Einträge der Karte, „Übernehmen“ ändert nur diese.
 */
import { useEffect, useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Badge, Body1, Button, Caption1, MessageBar, MessageBarBody, makeStyles, tokens } from '@fluentui/react-components';
import { Info16Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { Section } from '../../../components/Section';
import { useConfirm } from '../../../components/ConfirmProvider';
import { useNotify } from '../../../components/NotifyProvider';
import { translateOr } from '../../../i18n';
import { postIntegrationInstall, postIntegrationUninstall, useIntegration, type IntegrationPayload } from '../api';
import type { IntegrationJson } from '../../../api/types';
import { FieldRow, FieldRows, ToggleControl } from '../../../components/FieldRow';

type PartStatus = 'installiert' | 'teilweise' | 'veraltet' | 'nicht installiert';  // i18n-ignore (Server-Wert)
export type PartKey = 'context' | 'uri' | 'autostart';

/** 'installiert' und 'teilweise' zählen als "derzeit vorhanden" (teilweise: mind. ein Registry-Zweig gesetzt). */
function isInstalled(status?: string): boolean {
  return status === 'installiert' || status === 'teilweise';
}

const BADGE_COLOR: Record<Exclude<PartStatus, 'veraltet'>, 'success' | 'warning' | 'subtle'> = {
  installiert: 'success',
  teilweise: 'warning',
  'nicht installiert': 'subtle',  // i18n-ignore (Server-Wert)
};

const useStyles = makeStyles({
  lines: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, whiteSpace: 'pre-wrap', margin: 0 },
  outdated: { display: 'flex', alignItems: 'flex-start', columnGap: tokens.spacingHorizontalXS, color: tokens.colorNeutralForeground2 },
  outdatedIcon: { flexShrink: 0, marginTop: '2px' },
});

/** Plakette für den Zustand; ein veralteter Eintrag bekommt statt einer Plakette einen Hinweis. */
function StatusBadge(props: { status?: string }): JSX.Element | null {
  const status = (props.status as PartStatus) ?? 'nicht installiert';  // i18n-ignore (Server-Wert)
  if (status === 'veraltet') return null;
  const color = BADGE_COLOR[status] ?? 'subtle';
  return (
    <Badge appearance="tint" color={color} size="small">
      {translateOr(`einstellungen:integration.status.${status}`, status)}
    </Badge>
  );
}

/** Neutraler Hinweis zu einem Eintrag einer älteren Version (statt einer roten Plakette). */
function OutdatedNote(props: { status?: string }): JSX.Element | null {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  if (props.status !== 'veraltet') return null;
  return (
    <Caption1 className={styles.outdated}>
      <Info16Regular className={styles.outdatedIcon} aria-hidden="true" />
      {t('integration.outdated')}
    </Caption1>
  );
}

export function IntegrationCard(props: { parts: PartKey[]; id: string; title?: string; hint?: string }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const client = useQueryClient();
  const confirm = useConfirm();
  const notify = useNotify();
  const integration = useIntegration();
  const [context, setContext] = useState(false);
  const [uri, setUri] = useState(false);
  const [autostart, setAutostart] = useState(false);
  const [preview, setPreview] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const initializedRef = useRef(false);
  const contextId = useId();
  const uriId = useId();
  const autostartId = useId();

  // Schalter beim ersten Laden auf den tatsächlichen Ist-Zustand setzen (nur einmal, damit
  // spätere Aktualisierungen der Abfrage, z. B. nach dem Übernehmen, laufende Eingaben nicht überschreiben).
  useEffect(() => {
    const status = integration.data?.status;
    if (!status || initializedRef.current) return;
    initializedRef.current = true;
    setContext(isInstalled(status.context));
    setUri(isInstalled(status.uri));
    setAutostart(isInstalled(status.autostart));
  }, [integration.data]);

  const targets: Record<PartKey, boolean> = { context, uri, autostart };
  const has = (part: PartKey) => props.parts.includes(part);

  const runInstall = async (dryRun: boolean) => {
    const status = integration.data?.status;
    const current: Record<PartKey, boolean> = {
      context: isInstalled(status?.context),
      uri: isInstalled(status?.uri),
      autostart: isInstalled(status?.autostart),
    };
    // Nur die Einträge dieser Karte; die übrigen bleiben, wie sie sind.
    const toInstall: IntegrationPayload = {
      context: has('context') && targets.context && !current.context,
      uri: has('uri') && targets.uri && !current.uri,
      autostart: has('autostart') && targets.autostart && !current.autostart,
      dry_run: dryRun,
    };
    const toUninstall: IntegrationPayload = {
      context: has('context') && !targets.context && current.context,
      uri: has('uri') && !targets.uri && current.uri,
      autostart: has('autostart') && !targets.autostart && current.autostart,
      dry_run: dryRun,
    };
    const needsUninstall = toUninstall.context || toUninstall.uri || toUninstall.autostart;

    setBusy(true);
    setError(null);
    try {
      const lines: string[] = [];
      // Install immer aufrufen (auch ohne aktive Flags: legt fest, was der Ist-Zustand tatsächlich ist);
      // Uninstall nur, wenn ein zuvor installierter Teil abgeschaltet wurde.
      let last: IntegrationJson = await postIntegrationInstall(toInstall);
      lines.push(...last.lines);
      if (needsUninstall) {
        last = await postIntegrationUninstall(toUninstall);
        lines.push(...last.lines);
      }
      if (dryRun) {
        setPreview(lines);
      } else {
        setPreview(null);
        client.setQueryData(['integration'], { status: last.status, lines });
        notify({ intent: 'success', title: t('integration.notify.applied') });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onApply = async () => {
    const ok = await confirm({
      title: t('integration.confirm.title'),
      message: t('integration.confirm.message'),
      confirmText: t('integration.confirm.confirm'),
    });
    if (ok) await runInstall(false);
  };

  const status = integration.data?.status;
  return (
    <div id={props.id}>
      <Section
        title={props.title ?? t('integration.title')}
        description={props.hint}
        actions={
          <>
            <Button appearance="secondary" disabled={busy} onClick={() => void runInstall(true)}>
              {t('integration.preview')}
            </Button>
            <Button appearance="primary" disabled={busy} onClick={() => void onApply()}>
              {t('integration.apply')}
            </Button>
          </>
        }
      >
        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}

        <FieldRows>
          {has('autostart') ? (
            <FieldRow
              htmlFor={autostartId}
              label={t('integration.autostart')}
              help={t('integration.autostartHelp')}
              badges={<StatusBadge status={status?.autostart} />}
              details={<OutdatedNote status={status?.autostart} />}
              align="end"
              control={<ToggleControl id={autostartId} checked={autostart} onChange={setAutostart} />}
            />
          ) : null}
          {has('context') ? (
            <FieldRow
              htmlFor={contextId}
              label={t('integration.context')}
              help={t('integration.contextHelp')}
              badges={<StatusBadge status={status?.context} />}
              details={<OutdatedNote status={status?.context} />}
              align="end"
              control={<ToggleControl id={contextId} checked={context} onChange={setContext} />}
            />
          ) : null}
          {has('uri') ? (
            <FieldRow
              htmlFor={uriId}
              label={t('integration.uri')}
              help={t('integration.uriHelp')}
              badges={<StatusBadge status={status?.uri} />}
              details={<OutdatedNote status={status?.uri} />}
              align="end"
              control={<ToggleControl id={uriId} checked={uri} onChange={setUri} />}
            />
          ) : null}
        </FieldRows>

        {preview ? (
          <Body1>
            <pre className={styles.lines}>{preview.join('\n')}</pre>
          </Body1>
        ) : null}
      </Section>
    </div>
  );
}
