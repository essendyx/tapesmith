/** Eigenschaften (Vorbild `gui/panels/properties.py`): Formular je Objektart, Ausrichten und Verteilen. */
import { useState, type ReactNode } from 'react';
import {
  Badge,
  Button,
  Caption1,
  Divider,
  Radio,
  RadioGroup,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  AlignBottom20Regular,
  AlignCenterHorizontal20Regular,
  AlignCenterVertical20Regular,
  AlignLeft20Regular,
  AlignRight20Regular,
  AlignSpaceEvenlyHorizontal20Regular,
  AlignSpaceEvenlyVertical20Regular,
  AlignTop20Regular,
  ArrowRotateClockwise20Regular,
  ArrowRotateCounterclockwise20Regular,
  Copy20Regular,
  Delete20Regular,
  FlipHorizontal20Regular,
  Image20Regular,
  Star20Regular,
  type FluentIcon,
} from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { authUrl } from '../../api/client';
import type { EditorOverlay, FontInfo, LabelDocumentJson, LabelObjectJson } from '../../api/types';
import { ChoiceField, NumberField, SwitchField, TextField } from './fields';
import { formatMm } from '../../i18n/format';
import { objectTitle, useKindName } from './presets';

export type AlignMode = 'left' | 'hcenter' | 'right' | 'top' | 'vcenter' | 'bottom';

export interface PropertiesActions {
  update(ids: string[], changes: Record<string, unknown>, field: string): void;
  setBox(id: string, box: { x: number; y: number; w: number; h: number }, field: string): void;
  align(mode: AlignMode, reference: 'selection' | 'label'): void;
  distribute(axis: 'h' | 'v'): void;
  rotate(degrees: 90 | -90): void;
  flip(): void;
  duplicate(): void;
  remove(): void;
  pickIcon(id: string): void;
  replaceImage(id: string): void;
}

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  heading: {
    margin: 0,
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
    fontWeight: tokens.fontWeightSemibold,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  grid2: { display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: tokens.spacingHorizontalM, rowGap: tokens.spacingVerticalS },
  row: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalXS, rowGap: tokens.spacingVerticalXS, alignItems: 'center' },
  group: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  groupTitle: {
    margin: 0,
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground2,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
  iconPreview: {
    width: '40px',
    height: '40px',
    borderRadius: tokens.borderRadiusMedium,
    // wie auf dem Band: schwarzes Symbol auf weißem Grund, auch im Dunkelmodus
    backgroundColor: tokens.colorNeutralForegroundStaticInverted,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    objectFit: 'contain',
  },
  muted: { color: tokens.colorNeutralForeground3 },
});

const ROTATIONS = [0, 90, 180, 270].map((v) => ({ value: v, label: `${v}°` }));
const ALIGN_TEXT = ['left', 'center', 'right'] as const;
const VALIGN_TEXT = ['top', 'middle', 'bottom'] as const;
const QR_ERRORS = ['l', 'm', 'q', 'h'].map((v) => ({ value: v, label: v.toUpperCase() }));
const DIRECTIONS = ['h', 'v', 'down', 'up'] as const;
const FILLS = ['none', 'solid', 'stripes'] as const;
const DITHERS = ['none', 'floyd', 'bayer'] as const;

const ALIGN_BUTTONS: { mode: AlignMode; key: string; icon: FluentIcon }[] = [
  { mode: 'left', key: 'props.alignLeft', icon: AlignLeft20Regular },
  { mode: 'hcenter', key: 'props.alignHcenter', icon: AlignCenterHorizontal20Regular },
  { mode: 'right', key: 'props.alignRight', icon: AlignRight20Regular },
  { mode: 'top', key: 'props.alignTop', icon: AlignTop20Regular },
  { mode: 'vcenter', key: 'props.alignVcenter', icon: AlignCenterVertical20Regular },
  { mode: 'bottom', key: 'props.alignBottom', icon: AlignBottom20Regular },
];

function str(o: LabelObjectJson, key: string, fallback = ''): string {
  const v = o[key];
  return typeof v === 'string' ? v : fallback;
}
function num(o: LabelObjectJson, key: string, fallback: number | null): number | null {
  const v = o[key];
  return typeof v === 'number' ? v : fallback;
}
function bool(o: LabelObjectJson, key: string, fallback: boolean): boolean {
  const v = o[key];
  return typeof v === 'boolean' ? v : fallback;
}

function shared<T>(objects: LabelObjectJson[], get: (o: LabelObjectJson) => T): T | null {
  const first = objects[0];
  if (!first) return null;
  const v = get(first);
  return objects.every((o) => get(o) === v) ? v : null;
}

function IconButton(props: { label: string; icon: FluentIcon; onClick: () => void; disabled?: boolean }): JSX.Element {
  const Icon = props.icon;
  return (
    <Tooltip content={props.label} relationship="label">
      <Button appearance="subtle" aria-label={props.label} icon={<Icon />} onClick={props.onClick} disabled={props.disabled} />
    </Tooltip>
  );
}

function Group(props: { title: string; children: ReactNode }): JSX.Element {
  const styles = useStyles();
  return (
    <div className={styles.group} role="group" aria-label={props.title}>
      <h3 className={styles.groupTitle}>{props.title}</h3>
      {props.children}
    </div>
  );
}

export function PropertiesPanel(props: {
  doc: LabelDocumentJson;
  selection: string[];
  overlay: EditorOverlay | null;
  fonts: FontInfo[];
  dotsPerMm: number;
  actions: PropertiesActions;
  empty: ReactNode;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const kindName = useKindName();
  const { actions } = props;
  const opts = (group: string, values: readonly string[]) => values.map((v) => ({ value: v, label: t(`props.${group}.${v}`) }));
  const objects = props.selection
    .map((id) => props.doc.objects.find((o) => o.id === id))
    .filter((o): o is LabelObjectJson => o !== undefined);
  const [reference, setReference] = useState<'selection' | 'label' | null>(null);

  if (objects.length === 0) return <>{props.empty}</>;

  const ids = objects.map((o) => o.id);
  const multi = objects.length > 1;
  const ref = reference ?? (multi ? 'selection' : 'label');
  const mm = (v: number) => formatMm(v / props.dotsPerMm, 1);

  const quick = (
    <div className={styles.row} role="toolbar" aria-label={t('props.quick')}>
      <IconButton label={t('props.rotateLeft')} icon={ArrowRotateCounterclockwise20Regular} onClick={() => actions.rotate(-90)} />
      <IconButton label={t('props.rotateRight')} icon={ArrowRotateClockwise20Regular} onClick={() => actions.rotate(90)} />
      <IconButton label={t('props.flip')} icon={FlipHorizontal20Regular} onClick={actions.flip} />
      <IconButton label={t('props.duplicate')} icon={Copy20Regular} onClick={actions.duplicate} />
      <IconButton label={t('props.delete')} icon={Delete20Regular} onClick={actions.remove} />
    </div>
  );

  const alignGroup = (
    <Group title={t('props.align')}>
      <div className={styles.row}>
        {ALIGN_BUTTONS.map((b) => (
          <IconButton key={b.mode} label={t(b.key)} icon={b.icon} onClick={() => actions.align(b.mode, ref)} />
        ))}
      </div>
      <RadioGroup layout="horizontal" value={ref} aria-label={t('props.reference')} onChange={(_e, d) => setReference(d.value as 'selection' | 'label')}>
        <Radio value="selection" label={t('props.refSelection')} disabled={!multi} />
        <Radio value="label" label={t('props.refLabel')} />
      </RadioGroup>
      {multi ? (
        <div className={styles.row}>
          <IconButton
            label={t('props.distH')}
            icon={AlignSpaceEvenlyHorizontal20Regular}
            disabled={objects.length < 3}
            onClick={() => actions.distribute('h')}
          />
          <IconButton
            label={t('props.distV')}
            icon={AlignSpaceEvenlyVertical20Regular}
            disabled={objects.length < 3}
            onClick={() => actions.distribute('v')}
          />
          {objects.length < 3 ? <Caption1 className={styles.muted}>{t('props.distHint')}</Caption1> : null}
        </div>
      ) : null}
    </Group>
  );

  const common = (
    <Group title={t('props.look')}>
      <ChoiceField
        label={t('props.rotation')}
        value={shared(objects, (o) => o.rotation ?? 0)}
        options={ROTATIONS}
        onChange={(v) => actions.update(ids, { rotation: v }, 'rotation')}
      />
      <SwitchField label={t('props.mirror')} checked={shared(objects, (o) => o.mirror ?? false)} onChange={(v) => actions.update(ids, { mirror: v }, 'mirror')} />
      <SwitchField label={t('props.locked')} checked={shared(objects, (o) => o.locked ?? false)} onChange={(v) => actions.update(ids, { locked: v }, 'locked')} />
      <SwitchField label={t('props.visible')} checked={shared(objects, (o) => o.visible ?? true)} onChange={(v) => actions.update(ids, { visible: v }, 'visible')} />
    </Group>
  );

  if (multi) {
    return (
      <div className={styles.root}>
        <h2 className={styles.heading}>{t('props.selected', { n: objects.length })}</h2>
        {quick}
        <Divider />
        {alignGroup}
        <Divider />
        {common}
      </div>
    );
  }

  const o = objects[0]!;
  const key = o.id;
  const set = (field: string) => (v: unknown) => actions.update([o.id], { [field]: v }, field);
  const box = { x: o.x, y: o.y, w: o.w, h: o.h };
  const setBox = (field: 'x' | 'y' | 'w' | 'h') => (v: number | null) => {
    if (v === null) return;
    actions.setBox(o.id, { ...box, [field]: Math.round(v) }, field);
  };
  const code = props.overlay?.codes[o.id];
  const autoSize = props.overlay?.font_sizes[o.id];

  let specific: ReactNode = null;
  switch (o.kind) {
    case 'text':
      specific = (
        <Group title={t('props.text.group')}>
          <TextField key={`${key}-text`} label={t('props.text.text')} value={str(o, 'text')} onCommit={set('text')} multiline maxLines={3} hint={t('props.text.hint')} />
          <ChoiceField
            label={t('props.text.font')}
            value={str(o, 'font', 'sans')}
            options={(props.fonts.length ? props.fonts : [{ id: 'sans', name: 'sans' }]).map((f) => ({ value: f.id, label: f.name }))}
            onChange={set('font')}
          />
          <NumberField
            key={`${key}-size`}
            label={t('props.text.size')}
            value={num(o, 'size', null)}
            min={6}
            max={400}
            auto={{ label: autoSize ? t('props.autoValue', { value: autoSize }) : t('props.auto'), fallback: autoSize ?? 24 }}
            onCommit={set('size')}
          />
          <ChoiceField label={t('props.text.align')} value={str(o, 'align', 'left')} options={opts('text', ALIGN_TEXT)} onChange={set('align')} />
          <ChoiceField label={t('props.text.valign')} value={str(o, 'valign', 'middle')} options={opts('text', VALIGN_TEXT)} onChange={set('valign')} />
          <SwitchField label={t('props.text.invert')} checked={bool(o, 'invert', false)} onChange={set('invert')} />
          <SwitchField label={t('props.text.vertical')} checked={bool(o, 'vertical', false)} onChange={set('vertical')} />
        </Group>
      );
      break;
    case 'qr':
      specific = (
        <Group title={t('props.qr.group')}>
          <TextField key={`${key}-data`} label={t('props.content')} value={str(o, 'data')} onCommit={set('data')} />
          <ChoiceField label={t('props.qr.error')} value={str(o, 'error', 'm')} options={QR_ERRORS} onChange={set('error')} />
          <NumberField key={`${key}-module`} label={t('props.module')} value={num(o, 'module', null)} min={1} max={20} auto={{ label: t('props.auto'), fallback: 3 }} onCommit={set('module')} />
        </Group>
      );
      break;
    case 'code128':
      specific = (
        <Group title={t('props.code128.group')}>
          <TextField key={`${key}-data`} label={t('props.content')} value={str(o, 'data')} onCommit={set('data')} />
          <NumberField key={`${key}-module`} label={t('props.code128.bar')} value={num(o, 'module', 2)} min={2} max={8} onCommit={set('module')} />
          <SwitchField label={t('props.code128.showText')} checked={bool(o, 'show_text', true)} onChange={set('show_text')} />
          <NumberField key={`${key}-ts`} label={t('props.code128.textSize')} value={num(o, 'text_size', null)} min={6} max={40} auto={{ label: t('props.auto'), fallback: 12 }} onCommit={set('text_size')} />
        </Group>
      );
      break;
    case 'datamatrix':
      specific = (
        <Group title={t('props.datamatrix.group')}>
          <TextField key={`${key}-data`} label={t('props.content')} value={str(o, 'data')} onCommit={set('data')} />
          <NumberField key={`${key}-module`} label={t('props.module')} value={num(o, 'module', null)} min={2} max={20} auto={{ label: t('props.auto'), fallback: 3 }} onCommit={set('module')} />
        </Group>
      );
      break;
    case 'icon': {
      const icon = str(o, 'icon', 'tabler:star');
      specific = (
        <Group title={t('props.icon.group')}>
          <div className={styles.row}>
            {icon.includes('{') ? null : <img className={styles.iconPreview} src={authUrl('/api/v1/icons/png', { ref: icon, size: 48 })} alt="" />}
            <Caption1>{icon}</Caption1>
          </div>
          <Button icon={<Star20Regular />} onClick={() => actions.pickIcon(o.id)}>
            {t('props.icon.pick')}
          </Button>
        </Group>
      );
      break;
    }
    case 'line':
      specific = (
        <Group title={t('props.line.group')}>
          <ChoiceField label={t('props.line.direction')} value={str(o, 'direction', 'h')} options={opts('line', DIRECTIONS)} onChange={set('direction')} />
          <NumberField key={`${key}-th`} label={t('props.thickness')} value={num(o, 'thickness', 2)} min={1} max={20} onCommit={set('thickness')} />
          <NumberField key={`${key}-dash`} label={t('props.line.dash')} value={num(o, 'dash', 0)} min={0} max={50} onCommit={set('dash')} />
          <SwitchField label={t('props.line.arrowStart')} checked={bool(o, 'arrow_start', false)} onChange={set('arrow_start')} />
          <SwitchField label={t('props.line.arrowEnd')} checked={bool(o, 'arrow_end', false)} onChange={set('arrow_end')} />
        </Group>
      );
      break;
    case 'rect':
      specific = (
        <Group title={t('props.rect.group')}>
          <NumberField key={`${key}-th`} label={t('props.thickness')} value={num(o, 'thickness', 2)} min={0} max={20} onCommit={set('thickness')} />
          <NumberField key={`${key}-r`} label={t('props.rect.radius')} value={num(o, 'radius', 0)} min={0} max={40} onCommit={set('radius')} />
          <ChoiceField label={t('props.rect.fill')} value={str(o, 'fill', 'none')} options={opts('rect', FILLS)} onChange={set('fill')} />
          <NumberField key={`${key}-st`} label={t('props.rect.stripe')} value={num(o, 'stripe', 6)} min={2} max={40} onCommit={set('stripe')} />
        </Group>
      );
      break;
    case 'image':
      specific = (
        <Group title={t('props.image.group')}>
          <NumberField key={`${key}-thr`} label={t('props.image.threshold')} value={num(o, 'threshold', 128)} min={0} max={255} onCommit={set('threshold')} />
          <ChoiceField label={t('props.image.dither')} value={str(o, 'dither', 'none')} options={opts('image', DITHERS)} onChange={set('dither')} />
          <SwitchField label={t('props.image.invert')} checked={bool(o, 'invert', false)} onChange={set('invert')} />
          <SwitchField label={t('props.image.keepAspect')} checked={bool(o, 'keep_aspect', true)} onChange={set('keep_aspect')} />
          <Button icon={<Image20Regular />} onClick={() => actions.replaceImage(o.id)}>
            {t('props.image.replace')}
          </Button>
        </Group>
      );
      break;
    default:
      specific = null;
  }

  return (
    <div className={styles.root}>
      <h2 className={styles.heading}>{objectTitle(o, kindName)}</h2>
      {code ? (
        <div className={styles.row}>
          <Badge
            appearance="tint"
            color={!code.checked ? 'informative' : code.decodes ? 'success' : 'danger'}
            title={!code.checked ? t('props.selftestNotCheckedReason') : undefined}
          >
            {!code.checked ? t('props.selftestNotChecked') : code.decodes ? t('props.selftestOk') : t('props.selftestFail')}
          </Badge>
          <Caption1 className={styles.muted}>
            {[
              t('props.codeModule', { dots: code.module_dots }),
              code.version ? t('props.codeVersion', { version: code.version }) : null,
              code.inverted ? t('props.codeInverted') : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </Caption1>
        </div>
      ) : null}
      {quick}
      <Divider />
      {specific}
      <Divider />
      <Group title={t('props.position')}>
        <div className={styles.grid2}>
          <NumberField key={`${key}-x`} label={t('props.x')} value={o.x} min={-9999} max={9999} onCommit={setBox('x')} unitHint={mm} disabled={o.locked} />
          <NumberField key={`${key}-y`} label={t('props.y')} value={o.y} min={-9999} max={9999} onCommit={setBox('y')} unitHint={mm} disabled={o.locked} />
          <NumberField key={`${key}-w`} label={t('props.w')} value={o.w} min={1} max={9999} onCommit={setBox('w')} unitHint={mm} disabled={o.locked} />
          <NumberField key={`${key}-h`} label={t('props.h')} value={o.h} min={1} max={9999} onCommit={setBox('h')} unitHint={mm} disabled={o.locked} />
        </div>
      </Group>
      {common}
      <TextField key={`${key}-name`} label={t('props.name')} value={o.name ?? ''} onCommit={set('name')} placeholder={t('props.optional')} />
      <Divider />
      {alignGroup}
    </div>
  );
}
