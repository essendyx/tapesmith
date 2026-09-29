/** Gemeinsamer Dialog für Box-, Inhalts- und Verleih-Label: Vorschau und Druck (usePrintFlow). */
import { useEffect, useState } from 'react';
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
import { useTranslation } from 'react-i18next';
import { usePrintFlow } from '../../components/usePrint';
import { useNotify } from '../../components/NotifyProvider';
import { PrintOptionsBar } from '../../components/PrintOptionsBar';
import { TapePreview } from '../../components/TapePreview';
import { DEFAULT_PRINT_OPTIONS, type InventoryLabelRequest, type PrintOptions, type RenderJson } from '../../api/types';
import { printInventoryLabel, renderInventoryLabel } from './api';
import { errorText } from './errors';

const useStyles = makeStyles({
  surface: { maxWidth: '560px' },
  content: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL },
});

export function LabelDialog(props: {
  open: boolean;
  title: string;
  request: InventoryLabelRequest | null;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation('inventar');
  const styles = useStyles();
  const notify = useNotify();
  const { open, request } = props;
  const [render, setRender] = useState<RenderJson | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [options, setOptions] = useState<PrintOptions>(DEFAULT_PRINT_OPTIONS);
  const printFlow = usePrintFlow<InventoryLabelRequest>((req, opts) => printInventoryLabel(req, opts));

  useEffect(() => {
    if (!open || !request) {
      setRender(undefined);
      return;
    }
    let active = true;
    setLoading(true);
    renderInventoryLabel(request).then(
      (data) => {
        if (active) {
          setRender(data);
          setLoading(false);
        }
      },
      (err: unknown) => {
        if (active) {
          setLoading(false);
          notify({ intent: 'error', ...errorText(err) });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [open, request, notify]);

  const canPrint = Boolean(request) && !printFlow.busy;

  return (
    <Dialog open={open} onOpenChange={(_e, data) => !data.open && props.onClose()}>
      <DialogSurface className={styles.surface}>
        <DialogBody>
          <DialogTitle>{props.title}</DialogTitle>
          <DialogContent className={styles.content}>
            <TapePreview render={render} loading={loading} compact />
            <PrintOptionsBar value={options} onChange={setOptions} />
          </DialogContent>
          <DialogActions>
            <Button
              appearance="primary"
              disabled={!canPrint}
              onClick={() => {
                if (!request) return;
                void printFlow.run(request, options).then((outcome) => {
                  if (outcome && (outcome.status === 'ok' || outcome.status === 'wartet')) props.onClose();
                });
              }}
            >
              {t('label.print')}
            </Button>
            <Button appearance="secondary" onClick={props.onClose}>
              {t('label.close')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
