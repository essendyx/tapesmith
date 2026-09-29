/** Ebenen (Vorbild `gui/panels/layers.py`): oben = vorne, Sichtbar/Gesperrt, Reihenfolge, Umbenennen. */
import { useState, type KeyboardEvent, type MouseEvent } from 'react';
import { Button, Caption1, Input, Tooltip, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import {
  ArrowDown20Regular,
  ArrowMaximize20Regular,
  ArrowUp20Regular,
  Eye20Regular,
  EyeOff20Regular,
  LockClosed20Regular,
  LockOpen20Regular,
  Rename20Regular,
  ArrowBetweenDown20Regular,
  type FluentIcon,
} from '@fluentui/react-icons';
import type { LabelDocumentJson } from '../../api/types';
import { useTranslation } from 'react-i18next';
import { objectTitle, useKindName } from './presets';

export type ReorderOp = 'raise' | 'lower' | 'top' | 'bottom';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  bar: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalXXS },
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, margin: 0, padding: 0, outline: 'none' },
  row: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalXS,
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    cursor: 'pointer',
    userSelect: 'none',
    ':hover': { backgroundColor: tokens.colorNeutralBackground1Hover },
  },
  selected: {
    backgroundColor: tokens.colorBrandBackground2,
    ':hover': { backgroundColor: tokens.colorBrandBackground2Hover },
  },
  hidden: { opacity: 0.55 },
  text: { flexGrow: 1, minWidth: 0, display: 'flex', flexDirection: 'column' },
  name: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  kind: { color: tokens.colorNeutralForeground3 },
  empty: { color: tokens.colorNeutralForeground3 },
});

function BarButton(props: { label: string; icon: FluentIcon; onClick: () => void; disabled: boolean }): JSX.Element {
  const Icon = props.icon;
  return (
    <Tooltip content={props.label} relationship="label">
      <Button appearance="subtle" size="small" icon={<Icon />} disabled={props.disabled} onClick={props.onClick} />
    </Tooltip>
  );
}

export function LayersPanel(props: {
  doc: LabelDocumentJson;
  selection: string[];
  onSelect: (ids: string[]) => void;
  onUpdate: (id: string, changes: Record<string, unknown>, field: string) => void;
  onReorder: (op: ReorderOp) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const kindName = useKindName();
  const [renaming, setRenaming] = useState<{ id: string; value: string } | null>(null);
  const rows = [...props.doc.objects].reverse();
  const none = props.selection.length === 0;

  const click = (id: string, e: MouseEvent) => {
    if (e.ctrlKey || e.shiftKey || e.metaKey) {
      props.onSelect(props.selection.includes(id) ? props.selection.filter((s) => s !== id) : [...props.selection, id]);
    } else {
      props.onSelect([id]);
    }
  };

  const commitRename = () => {
    if (!renaming) return;
    const obj = props.doc.objects.find((o) => o.id === renaming.id);
    if (obj && (obj.name ?? '') !== renaming.value.trim()) props.onUpdate(renaming.id, { name: renaming.value.trim() }, 'name');
    setRenaming(null);
  };

  const single = props.selection.length === 1 ? props.selection[0] : undefined;

  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    e.stopPropagation();
    const idx = rows.findIndex((r) => r.id === props.selection[props.selection.length - 1]);
    const next = rows[Math.min(rows.length - 1, Math.max(0, idx + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (next) props.onSelect([next.id]);
  };

  return (
    <div className={styles.root}>
      <div className={styles.bar} role="toolbar" aria-label={t('layers.order')}>
        <BarButton label={t('layers.top')} icon={ArrowMaximize20Regular} disabled={none} onClick={() => props.onReorder('top')} />
        <BarButton label={t('layers.raise')} icon={ArrowUp20Regular} disabled={none} onClick={() => props.onReorder('raise')} />
        <BarButton label={t('layers.lower')} icon={ArrowDown20Regular} disabled={none} onClick={() => props.onReorder('lower')} />
        <BarButton label={t('layers.bottom')} icon={ArrowBetweenDown20Regular} disabled={none} onClick={() => props.onReorder('bottom')} />
        <BarButton
          label={t('layers.rename')}
          icon={Rename20Regular}
          disabled={!single}
          onClick={() => {
            const obj = props.doc.objects.find((o) => o.id === single);
            if (obj) setRenaming({ id: obj.id, value: obj.name ?? '' });
          }}
        />
      </div>
      {rows.length === 0 ? <Caption1 className={styles.empty}>{t('layers.empty')}</Caption1> : null}
      <ul className={styles.list} role="listbox" aria-label={t('layers.list')} aria-multiselectable="true" tabIndex={rows.length ? 0 : -1} onKeyDown={onListKey}>
        {rows.map((o) => {
          const selected = props.selection.includes(o.id);
          const visible = o.visible !== false;
          const locked = o.locked === true;
          const title = objectTitle(o, kindName);
          return (
            <li
              key={o.id}
              role="option"
              aria-selected={selected}
              aria-label={title}
              className={mergeClasses(styles.row, selected && styles.selected, !visible && styles.hidden)}
              onClick={(e) => click(o.id, e)}
              onDoubleClick={() => setRenaming({ id: o.id, value: o.name ?? '' })}
            >
              <span className={styles.text}>
                {renaming?.id === o.id ? (
                  <Input
                    size="small"
                    aria-label={t('layers.newName')}
                    autoFocus
                    value={renaming.value}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(_e, d) => setRenaming({ id: o.id, value: d.value })}
                    onBlur={commitRename}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitRename();
                      if (e.key === 'Escape') {
                        e.stopPropagation();
                        setRenaming(null);
                      }
                    }}
                  />
                ) : (
                  <>
                    <span className={styles.name}>{o.name || o.id}</span>
                    <Caption1 className={styles.kind}>{kindName(o.kind)}</Caption1>
                  </>
                )}
              </span>
              <Tooltip content={visible ? t('layers.hide', { title }) : t('layers.show', { title })} relationship="label">
                <Button
                  appearance="subtle"
                  size="small"
                  icon={visible ? <Eye20Regular /> : <EyeOff20Regular />}
                  onClick={(e) => {
                    e.stopPropagation();
                    props.onUpdate(o.id, { visible: !visible }, 'visible');
                  }}
                />
              </Tooltip>
              <Tooltip content={locked ? t('layers.unlock', { title }) : t('layers.lock', { title })} relationship="label">
                <Button
                  appearance="subtle"
                  size="small"
                  icon={locked ? <LockClosed20Regular /> : <LockOpen20Regular />}
                  onClick={(e) => {
                    e.stopPropagation();
                    props.onUpdate(o.id, { locked: !locked }, 'locked');
                  }}
                />
              </Tooltip>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
