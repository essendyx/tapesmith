/** Dialog „Neues Token“: Name/Rolle anlegen, danach das Token genau einmal anzeigen. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Radio,
  RadioGroup,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Copy20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { useNotify } from '../../components/NotifyProvider';
import { ACCESS_KEY, createAccessToken } from './api';
import type { CreateTokenResponse, Role } from './types';
import { ROLES } from './types';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

const useStyles = makeStyles({
  form: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  roleOption: { display: 'flex', flexDirection: 'column' },
  roleHelp: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  copyRow: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
  linkList: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS, margin: 0, padding: 0, listStyle: 'none' },
});

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

export function NewTokenDialog(props: { open: boolean; onClose: () => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('drucken');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CreateTokenResponse | null>(null);
  useDialogFocusReturn(props.open);

  const roleLabel: Record<Role, string> = {
    admin: t('newToken.roleAdminLabel'),
    drucken: t('newToken.roleDruckenLabel'),
    familie: t('newToken.roleFamilieLabel'),
  };
  const roleHelp: Record<Role, string> = {
    admin: t('newToken.roleAdminHelp'),
    drucken: t('newToken.roleDruckenHelp'),
    familie: t('newToken.roleFamilieHelp'),
  };

  const reset = () => {
    setName('');
    setRole('drucken');
    setBusy(false);
    setError(null);
    setResult(null);
  };

  const close = () => {
    reset();
    props.onClose();
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await createAccessToken(name.trim(), role);
      setResult(r);
      void queryClient.invalidateQueries({ queryKey: ACCESS_KEY });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const copy = async (value: string, label: string) => {
    if (await copyText(value)) notify({ intent: 'success', title: t('newToken.copied', { label }) });
    else notify({ intent: 'error', title: t('newToken.copyFailed') });
  };

  return (
    <Dialog
      open={props.open}
      onOpenChange={(_e, data) => {
        if (!data.open) close();
      }}
    >
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{result ? t('newToken.titleResult') : t('newToken.titleCreate')}</DialogTitle>
          <DialogContent>
            {result ? (
              <div className={styles.form}>
                <MessageBar intent="warning" role="status">
                  <MessageBarBody>{t('newToken.warning')}</MessageBarBody>
                </MessageBar>
                <Field label={t('newToken.tokenLabel')}>
                  <div className={styles.copyRow}>
                    <Input readOnly value={result.secret} />
                    <Button
                      icon={<Copy20Regular />}
                      aria-label={t('newToken.copyTokenAria')}
                      onClick={() => void copy(result.secret, t('newToken.tokenLabel'))}
                    >
                      {t('common:actions.copy')}
                    </Button>
                  </div>
                </Field>
                {result.family_urls.length > 0 ? (
                  <Field label={t('newToken.familyLinkLabel')}>
                    <ul className={styles.linkList}>
                      {result.family_urls.map((url) => (
                        <li key={url} className={styles.copyRow}>
                          <a href={url}>{url}</a>
                          <Button
                            icon={<Copy20Regular />}
                            aria-label={t('newToken.copyLinkAria')}
                            onClick={() => void copy(url, t('newToken.familyLinkLabel'))}
                          >
                            {t('common:actions.copy')}
                          </Button>
                        </li>
                      ))}
                    </ul>
                  </Field>
                ) : null}
              </div>
            ) : (
              <div className={styles.form}>
                <Field label={t('newToken.nameLabel')}>
                  <Input value={name} onChange={(_e, d) => setName(d.value)} autoFocus />
                </Field>
                <Field label={t('newToken.roleLabel')}>
                  <RadioGroup value={role} onChange={(_e, d) => setRole(d.value as Role)}>
                    {ROLES.map((r) => (
                      <Radio
                        key={r}
                        value={r}
                        label={
                          <span className={styles.roleOption}>
                            {roleLabel[r]}
                            <span className={styles.roleHelp}>{roleHelp[r]}</span>
                          </span>
                        }
                      />
                    ))}
                  </RadioGroup>
                </Field>
                {error ? (
                  <MessageBar intent="error">
                    <MessageBarBody>{error}</MessageBarBody>
                  </MessageBar>
                ) : null}
              </div>
            )}
          </DialogContent>
          <DialogActions>
            {result ? (
              <Button appearance="primary" onClick={close}>
                {t('common:actions.close')}
              </Button>
            ) : (
              <>
                <Button
                  appearance="primary"
                  disabled={name.trim() === '' || busy}
                  icon={busy ? <Spinner size="tiny" /> : undefined}
                  aria-busy={busy}
                  onClick={() => void create()}
                >
                  {t('newToken.create')}
                </Button>
                <Button appearance="secondary" onClick={close}>
                  {t('common:actions.cancel')}
                </Button>
              </>
            )}
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
