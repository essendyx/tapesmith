/** Box-Detail: Gegenstandsliste (hinzufügen, verschieben, löschen), Box bearbeiten/löschen, Labels. */
import { useEffect, useState } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  Option,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Delete16Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { errorText } from './errors';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import type { BoxDetailJson, BoxJson, InventoryLabelRequest, ItemJson } from '../../api/types';
import { createItem, deleteBox, deleteItem, fetchBoxDetail, moveItem, updateBox } from './api';
import { LabelDialog } from './LabelDialog';

const useStyles = makeStyles({
  content: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, minWidth: '420px' },
  row: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'flex-end', flexWrap: 'wrap' },
  itemRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    columnGap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalXS} 0`,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  itemName: { flex: 1, minWidth: 0 },
});

type LabelKind = 'box' | 'content' | null;

export function BoxDetailDialog(props: { boxId: string | null; boxes: BoxJson[]; onClose: () => void; onChanged: () => void }): JSX.Element {
  const { t } = useTranslation('inventar');
  const styles = useStyles();
  const confirm = useConfirm();
  const notify = useNotify();
  const { boxId } = props;
  const open = boxId !== null;

  const [detail, setDetail] = useState<BoxDetailJson | null>(null);
  const [location, setLocation] = useState('');
  const [note, setNote] = useState('');
  const [newItemName, setNewItemName] = useState('');
  const [newItemQty, setNewItemQty] = useState('1');
  const [moveTarget, setMoveTarget] = useState<Record<number, string>>({});
  const [labelKind, setLabelKind] = useState<LabelKind>(null);

  const load = () => {
    if (!boxId) return;
    fetchBoxDetail(boxId)
      .then((d) => {
        setDetail(d);
        setLocation(d.location);
        setNote(d.note);
      })
      .catch((err: unknown) => notify({ intent: 'error', ...errorText(err) }));
  };

  useEffect(() => {
    if (open) load();
    else {
      setDetail(null);
      setLabelKind(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boxId, open]);

  const saveHeader = async () => {
    if (!boxId) return;
    try {
      await updateBox(boxId, { location, note });
      load();
      props.onChanged();
    } catch (err) {
      notify({ intent: 'error', ...errorText(err) });
    }
  };

  const onAddItem = async () => {
    if (!boxId || !newItemName.trim()) return;
    const qty = Math.max(1, parseInt(newItemQty, 10) || 1);
    try {
      await createItem({ name: newItemName, box_id: boxId, qty, note: '' });
      setNewItemName('');
      setNewItemQty('1');
      load();
      props.onChanged();
    } catch (err) {
      notify({ intent: 'error', ...errorText(err) });
    }
  };

  const onDeleteItem = async (item: ItemJson) => {
    const ok = await confirm({
      title: t('detail.confirm.deleteItemTitle'),
      message: t('detail.confirm.deleteItemMessage', { name: item.name }),
      danger: true,
      confirmText: t('detail.confirm.delete'),
    });
    if (!ok) return;
    try {
      await deleteItem(item.id);
      load();
      props.onChanged();
    } catch (err) {
      notify({ intent: 'error', ...errorText(err) });
    }
  };

  const onMoveItem = async (item: ItemJson) => {
    const target = moveTarget[item.id];
    if (!target) return;
    try {
      await moveItem(item.id, target);
      notify({ intent: 'success', title: t('detail.moved', { target }) });
      load();
      props.onChanged();
    } catch (err) {
      notify({ intent: 'error', ...errorText(err) });
    }
  };

  const onDeleteBox = async () => {
    if (!boxId) return;
    const ok = await confirm({
      title: t('detail.confirm.deleteBoxTitle'),
      message: t('detail.confirm.deleteBoxMessage', { boxId }),
      danger: true,
      confirmText: t('detail.confirm.delete'),
    });
    if (!ok) return;
    try {
      await deleteBox(boxId);
      props.onChanged();
      props.onClose();
    } catch (err) {
      notify({ intent: 'error', ...errorText(err) });
    }
  };

  const otherBoxes = props.boxes.filter((b) => b.id !== boxId);

  const labelRequest: InventoryLabelRequest | null =
    labelKind && boxId ? (labelKind === 'box' ? { type: 'box', box_id: boxId } : { type: 'content', box_id: boxId }) : null;

  return (
    <>
      {/* Nie zwei modale Dialoge gleichzeitig: solange der Label-Dialog offen ist, ist der Box-Dialog zu und
          kommt danach mit unveränderter Box wieder. */}
      <Dialog open={open && labelKind === null} onOpenChange={(_e, data) => !data.open && props.onClose()}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('detail.title', { boxId })}</DialogTitle>
            <DialogContent className={styles.content}>
              <div className={styles.row}>
                <Field label={t('detail.location')}>
                  <Input value={location} onChange={(_e, d) => setLocation(d.value)} />
                </Field>
                <Field label={t('detail.note')}>
                  <Textarea value={note} onChange={(_e, d) => setNote(d.value)} resize="vertical" />
                </Field>
                <Button onClick={() => void saveHeader()}>{t('detail.save')}</Button>
              </div>

              <div>
                <h3>{t('detail.items')}</h3>
                {(detail?.item_list ?? []).map((item) => (
                  <div key={item.id} className={styles.itemRow}>
                    <span className={styles.itemName}>
                      {item.name}
                      {item.qty !== 1 ? ` ×${item.qty}` : ''}
                    </span>
                    <Dropdown
                      size="small"
                      placeholder={t('detail.moveTo')}
                      selectedOptions={moveTarget[item.id] ? [moveTarget[item.id] as string] : []}
                      onOptionSelect={(_e, d) => setMoveTarget((m) => ({ ...m, [item.id]: d.optionValue ?? '' }))}
                    >
                      {otherBoxes.map((b) => (
                        <Option key={b.id} value={b.id}>
                          {b.id}
                        </Option>
                      ))}
                    </Dropdown>
                    <Button size="small" onClick={() => void onMoveItem(item)} disabled={!moveTarget[item.id]}>
                      {t('detail.move')}
                    </Button>
                    <Button
                      size="small"
                      icon={<Delete16Regular />}
                      onClick={() => void onDeleteItem(item)}
                      aria-label={t('detail.deleteItem', { name: item.name })}
                    />
                  </div>
                ))}
                <div className={styles.row}>
                  <Field label={t('detail.name')}>
                    <Input value={newItemName} onChange={(_e, d) => setNewItemName(d.value)} placeholder={t('detail.namePlaceholder')} />
                  </Field>
                  <Field label={t('detail.qty')}>
                    <Input value={newItemQty} onChange={(_e, d) => setNewItemQty(d.value)} style={{ width: '64px' }} />
                  </Field>
                  <Button onClick={() => void onAddItem()} disabled={!newItemName.trim()}>
                    {t('detail.add')}
                  </Button>
                </div>
              </div>
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setLabelKind('box')}>{t('detail.boxLabel')}</Button>
              <Button onClick={() => setLabelKind('content')}>{t('detail.contentLabel')}</Button>
              <Button appearance="secondary" onClick={() => void onDeleteBox()}>
                {t('detail.deleteBox')}
              </Button>
              <Button appearance="secondary" onClick={props.onClose}>
                {t('detail.close')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <LabelDialog
        open={labelKind !== null}
        title={labelKind === 'box' ? t('detail.boxLabel') : t('detail.contentLabel')}
        request={labelRequest}
        onClose={() => setLabelKind(null)}
      />
    </>
  );
}
