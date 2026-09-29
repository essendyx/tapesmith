/** Bestätigungsdialog als Promise: `const ok = await confirm({...})`. */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Warning20Filled } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useDialogFocusReturn } from './useDialogFocusReturn';

export interface ConfirmOptions {
  title: string;
  message?: string;
  reasons?: string[];
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}

type ConfirmFn = (o: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

const useStyles = makeStyles({
  surface: { maxWidth: '480px', borderRadius: tokens.borderRadiusXLarge },
  title: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
  icon: { color: tokens.colorPaletteDarkOrangeForeground1, flexShrink: 0 },
  message: { margin: `0 0 ${tokens.spacingVerticalS}`, color: tokens.colorNeutralForeground2 },
  reasons: {
    margin: 0,
    paddingLeft: tokens.spacingHorizontalXL,
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXS,
  },
  danger: {
    backgroundColor: tokens.colorPaletteRedBackground3,
    color: tokens.colorNeutralForegroundOnBrand,
    ':hover': { backgroundColor: tokens.colorPaletteRedForeground1, color: tokens.colorNeutralForegroundOnBrand },
    ':hover:active': { backgroundColor: tokens.colorPaletteRedForeground1 },
  },
});

interface Pending {
  options: ConfirmOptions;
  resolve: (ok: boolean) => void;
}

export function ConfirmProvider(props: { children: ReactNode }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('components');
  const [pending, setPending] = useState<Pending | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  // Nach dem Schließen zurück zum Auslöser (z. B. dem Knopf „Drucken“).
  useDialogFocusReturn(pending !== null);

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        setPending((prev) => {
          prev?.resolve(false);
          return { options, resolve };
        });
      }),
    [],
  );

  // Fehldruckschutz: Fokus immer auf „Abbrechen“, damit Eingabe nicht versehentlich druckt.
  useEffect(() => {
    if (!pending) return undefined;
    const timer = setTimeout(() => cancelRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [pending]);

  const close = (ok: boolean) => {
    setPending((prev) => {
      prev?.resolve(ok);
      return null;
    });
  };

  const o = pending?.options;
  return (
    <ConfirmContext.Provider value={confirm}>
      {props.children}
      <Dialog
        open={pending !== null}
        modalType="alert"
        onOpenChange={(_e, data) => {
          if (!data.open) close(false);
        }}
      >
        <DialogSurface
          className={styles.surface}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              close(false);
            }
          }}
        >
          <DialogBody>
            <DialogTitle>
              <span className={styles.title}>
                {o?.danger ? (
                  <>
                    <Warning20Filled className={styles.icon} aria-hidden="true" />
                    <span className="p12-visually-hidden">{t('confirm.danger')}: </span>
                  </>
                ) : null}
                {o?.title}
              </span>
            </DialogTitle>
            <DialogContent>
              {o?.message ? <p className={styles.message}>{o.message}</p> : null}
              {o?.reasons && o.reasons.length > 0 ? (
                <ul className={styles.reasons}>
                  {o.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : null}
            </DialogContent>
            <DialogActions>
              <Button
                appearance="primary"
                className={o?.danger ? styles.danger : undefined}
                onClick={() => close(true)}
              >
                {o?.confirmText ?? t('confirm.ok')}
              </Button>
              <Button ref={cancelRef} appearance="secondary" onClick={() => close(false)}>
                {o?.cancelText ?? t('confirm.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error('useConfirm without ConfirmProvider');
  return ctx;
}
