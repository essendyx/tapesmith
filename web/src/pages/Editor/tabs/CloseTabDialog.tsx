/** Rückfrage beim Schließen eines Tabs mit ungespeicherten Änderungen: Speichern, Nicht speichern, Abbrechen. */
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  makeStyles,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';

const useStyles = makeStyles({
  surface: { maxWidth: '480px' },
});

export function CloseTabDialog(props: { title: string; busy?: boolean; onSave(): void; onDiscard(): void; onCancel(): void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  return (
    <Dialog open onOpenChange={(_e, d) => (d.open ? undefined : props.onCancel())}>
      <DialogSurface className={styles.surface}>
        <DialogBody>
          <DialogTitle>{t('closeDialog.title', { title: props.title })}</DialogTitle>
          <DialogContent>{t('closeDialog.body')}</DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={props.busy} onClick={props.onSave}>
              {t('closeDialog.save')}
            </Button>
            <Button disabled={props.busy} onClick={props.onDiscard}>
              {t('closeDialog.discard')}
            </Button>
            <Button onClick={props.onCancel}>{t('closeDialog.cancel')}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
