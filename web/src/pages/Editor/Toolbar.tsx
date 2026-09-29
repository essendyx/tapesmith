/** Werkzeugleiste des Editors: Datei, Verlauf, Zoom, Raster/Einrasten, Drucken, Export. */
import type { ReactNode } from 'react';
import {
  Button,
  Dropdown,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Option,
  Popover,
  PopoverSurface,
  PopoverTrigger,
  ToggleButton,
  Toolbar as FluentToolbar,
  ToolbarDivider,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowDownload20Regular,
  ArrowExport20Regular,
  ArrowRedo20Regular,
  ArrowUndo20Regular,
  BookAdd20Regular,
  DocumentAdd20Regular,
  FolderOpen20Regular,
  Grid20Regular,
  Pin20Regular,
  Options20Regular,
  Print20Regular,
  Save20Regular,
  SaveCopy20Regular,
} from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import type { Zoom } from './geometry';

const ZOOMS: { value: Zoom; key: string }[] = [
  { value: 'fit', key: 'toolbar.zoomFit' },
  { value: 1, key: 'toolbar.zoom100' },
  { value: 2, key: 'toolbar.zoom200' },
  { value: 4, key: 'toolbar.zoom400' },
];

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    rowGap: tokens.spacingVerticalXS,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusXLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
  },
  zoom: { minWidth: '150px' },
  spacer: { flexGrow: 1 },
  printSurface: { padding: tokens.spacingHorizontalL, maxWidth: '520px' },
});

function Tool(props: { label: string; shortcut?: string; icon: JSX.Element; onClick: () => void; disabled?: boolean }): JSX.Element {
  const { t } = useTranslation('editor');
  return (
    <Tooltip content={props.shortcut ? t('toolbar.withKey', { label: props.label, key: props.shortcut }) : props.label} relationship="description">
      <Button appearance="subtle" aria-label={props.label} icon={props.icon} onClick={props.onClick} disabled={props.disabled} />
    </Tooltip>
  );
}

export interface ToolbarProps {
  onNew(): void;
  onOpen(): void;
  onSave(): void;
  onSaveAs(): void;
  onSaveTemplate(): void;
  onUndo(): void;
  onRedo(): void;
  canUndo: boolean;
  canRedo: boolean;
  zoom: Zoom;
  onZoom(z: Zoom): void;
  grid: boolean;
  onGrid(v: boolean): void;
  snap: boolean;
  onSnap(v: boolean): void;
  onPrint(): void;
  printDisabledReason: string | null;
  printBusy: boolean;
  printOptions: ReactNode;
  onExport(format: 'png' | 'pdf' | 'pbm'): void;
  onDownloadDoc(): void;
  compact: boolean;
}

export function EditorToolbar(p: ToolbarProps): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const zoomKey = ZOOMS.find((z) => z.value === p.zoom)?.key;
  const zoomLabel = zoomKey ? t(zoomKey) : '';
  const printButton = (
    <Button appearance="primary" icon={<Print20Regular />} onClick={p.onPrint} disabled={p.printDisabledReason !== null || p.printBusy}>
      {t('toolbar.print')}
    </Button>
  );
  const printOptions = (
    <Popover positioning="below-end" withArrow trapFocus>
      <PopoverTrigger disableButtonEnhancement>
        <Tooltip content={t('toolbar.printOptions')} relationship="label">
          <Button appearance="subtle" aria-label={t('toolbar.printOptions')} icon={<Options20Regular />} />
        </Tooltip>
      </PopoverTrigger>
      <PopoverSurface className={styles.printSurface} aria-label={t('toolbar.printOptions')}>
        {p.printOptions}
      </PopoverSurface>
    </Popover>
  );
  return (
    <FluentToolbar className={styles.root} aria-label={t('toolbar.label')} size="small">
      <Tool label={t('toolbar.new')} icon={<DocumentAdd20Regular />} onClick={p.onNew} />
      <Tool label={t('toolbar.open')} icon={<FolderOpen20Regular />} onClick={p.onOpen} />
      <Tool label={t('toolbar.save')} shortcut={t('keys.save')} icon={<Save20Regular />} onClick={p.onSave} />
      <Tool label={t('toolbar.saveAs')} icon={<SaveCopy20Regular />} onClick={p.onSaveAs} />
      <Tool label={t('toolbar.saveTemplate')} icon={<BookAdd20Regular />} onClick={p.onSaveTemplate} />
      <ToolbarDivider />
      <Tool label={t('toolbar.undo')} shortcut={t('keys.undo')} icon={<ArrowUndo20Regular />} onClick={p.onUndo} disabled={!p.canUndo} />
      <Tool label={t('toolbar.redo')} shortcut={t('keys.redo')} icon={<ArrowRedo20Regular />} onClick={p.onRedo} disabled={!p.canRedo} />
      <ToolbarDivider />
      <Dropdown
        className={styles.zoom}
        size="small"
        aria-label={t('toolbar.zoom')}
        value={zoomLabel}
        selectedOptions={[String(p.zoom)]}
        onOptionSelect={(_e, d) => {
          const z = ZOOMS.find((x) => String(x.value) === d.optionValue);
          if (z) p.onZoom(z.value);
        }}
      >
        {ZOOMS.map((z) => (
          <Option key={String(z.value)} value={String(z.value)}>
            {t(z.key)}
          </Option>
        ))}
      </Dropdown>
      <Tooltip content={t('toolbar.gridTip')} relationship="description">
        <ToggleButton appearance="subtle" aria-label={t('toolbar.grid')} icon={<Grid20Regular />} checked={p.grid} onClick={() => p.onGrid(!p.grid)} />
      </Tooltip>
      <Tooltip content={t('toolbar.snapTip')} relationship="description">
        <ToggleButton appearance="subtle" aria-label={t('toolbar.snap')} icon={<Pin20Regular />} checked={p.snap} onClick={() => p.onSnap(!p.snap)} />
      </Tooltip>
      <div className={styles.spacer} />
      <Menu>
        <MenuTrigger disableButtonEnhancement>
          <Button appearance="subtle" icon={<ArrowExport20Regular />} aria-label={p.compact ? t('toolbar.export') : undefined}>
            {p.compact ? null : t('toolbar.export')}
          </Button>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            <MenuItem disabled={p.printDisabledReason !== null} onClick={() => p.onExport('png')}>
              {t('toolbar.exportPng')}
            </MenuItem>
            <MenuItem disabled={p.printDisabledReason !== null} onClick={() => p.onExport('pdf')}>
              {t('toolbar.exportPdf')}
            </MenuItem>
            <MenuItem disabled={p.printDisabledReason !== null} onClick={() => p.onExport('pbm')}>
              {t('toolbar.exportPbm')}
            </MenuItem>
            <MenuItem icon={<ArrowDownload20Regular />} onClick={p.onDownloadDoc}>
              {t('toolbar.downloadDoc')}
            </MenuItem>
          </MenuList>
        </MenuPopover>
      </Menu>
      {printOptions}
      {p.printDisabledReason ? (
        <Tooltip content={p.printDisabledReason} relationship="description">
          <span>{printButton}</span>
        </Tooltip>
      ) : (
        printButton
      )}
    </FluentToolbar>
  );
}
