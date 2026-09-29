/**
 * Bandvorschau: Design-Bild oder 1-Bit-Druckbild auf ruhiger Bühne. „Einpassen“ passt das Bild
 * in Breite und Höhe der Bühne ein (nie Überlauf), „100 %“ zeigt die echte Größe mit Scrollen.
 * Die Info-Zeile entsteht aus den Zahlen der Vorschau in der Sprache der Oberfläche.
 */
import { useState, type CSSProperties } from 'react';
import {
  Caption1,
  makeStyles,
  mergeClasses,
  Tab,
  TabList,
  ToggleButton,
  Tooltip,
  tokens,
} from '@fluentui/react-components';
import { ZoomFit20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { pngSrc } from '../api/client';
import { useAppInfo } from '../api/core';
import type { PreviewJson, RenderJson } from '../api/types';
import { formatMm } from '../i18n/format';
import { WarningList } from './WarningList';

export type PreviewMode = 'design' | 'raster';
/** 'fit' passt in Breite und Höhe der Bühne (höchstens Faktor 6), '100' ist echte Größe in Millimetern, eine Zahl ist ein Vielfaches davon. */
export type PreviewZoom = 'fit' | '100' | number;

const MAX_FIT_FACTOR = 6;
/** Höhe der Bühne beim Einpassen (normal und kompakt). */
export const FIT_MAX_HEIGHT = 'min(40vh, 320px)';
export const FIT_MAX_HEIGHT_COMPACT = '96px';
const DEFAULT_SCREEN_PX_PER_MM = 96 / 25.4;

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM, minWidth: 0 },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    columnGap: tokens.spacingHorizontalM,
    flexWrap: 'wrap',
  },
  zoom: { display: 'flex', columnGap: tokens.spacingHorizontalXS },
  stage: {
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '140px',
    padding: `${tokens.spacingVerticalXXL} ${tokens.spacingHorizontalXXL}`,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground3,
    backgroundImage: `radial-gradient(${tokens.colorNeutralStroke3} 1px, transparent 1px)`,
    backgroundSize: '16px 16px',
    overflow: 'auto',
    '@media (forced-colors: active)': { border: `${tokens.strokeWidthThin} solid CanvasText`, backgroundImage: 'none' },
  },
  stageFit: { overflow: 'hidden' },
  stageCompact: { minHeight: '88px', padding: tokens.spacingHorizontalL },
  imageWrap: {
    position: 'relative',
    maxWidth: '100%',
    maxHeight: '100%',
    lineHeight: 0,
    display: 'flex',
    justifyContent: 'center',
  },
  imageWrapScroll: { maxWidth: 'none' },
  imageWrapFit: { width: '100%' },
  image: {
    display: 'block',
    height: 'auto',
    borderRadius: tokens.borderRadiusSmall,
    boxShadow: tokens.shadow8,
    transitionProperty: 'opacity, filter',
    transitionDuration: tokens.durationNormal,
    transitionTimingFunction: tokens.curveEasyEase,
  },
  pixelated: { imageRendering: 'pixelated' },
  loading: { opacity: 0.5, filter: 'saturate(0.6)' },
  shimmer: {
    position: 'absolute',
    inset: 0,
    borderRadius: tokens.borderRadiusSmall,
    backgroundImage: `linear-gradient(90deg, transparent 0%, ${tokens.colorNeutralBackground1Hover} 50%, transparent 100%)`,
    backgroundSize: '200% 100%',
    opacity: 0.7,
    animationName: {
      from: { backgroundPosition: '200% 0' },
      to: { backgroundPosition: '-200% 0' },
    },
    animationDuration: '1.4s',
    animationIterationCount: 'infinite',
    animationTimingFunction: 'linear',
    '@media (prefers-reduced-motion: reduce)': { animationName: 'none' },
  },
  placeholder: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase300 },
  info: {
    display: 'flex',
    flexWrap: 'wrap',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXXS,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase300,
  },
  infoCompact: { fontSize: tokens.fontSizeBase200 },
  hint: { color: tokens.colorPaletteDarkOrangeForeground1 },
});

type TFn = (key: string, opts?: Record<string, unknown>) => string;

/** Info-Zeile: „Inhalt 38 mm + Vor-/Nachlauf ca. 10 mm = ca. 48 mm Band“ in der aktuellen Sprache. */
export function previewInfoText(preview: PreviewJson, t: TFn): string {
  const lead = Math.max(0, preview.tape_mm - preview.content_mm);
  return t('preview.info', {
    content: formatMm(preview.content_mm, 0),
    lead: formatMm(lead, 0),
    tape: formatMm(preview.tape_mm, 0),
    context: preview.estimated ? 'estimated' : undefined,
  });
}

/** Bandbilanz bei mehreren Labels („3 Labels: 120 mm Band“), sonst leer. */
export function previewBalanceText(preview: PreviewJson, t: TFn): string {
  if (preview.labels <= 1) return '';
  return t('preview.balance', { count: preview.labels, tape: formatMm(preview.tape_mm, 0) });
}

export function TapePreview(props: {
  render: RenderJson | undefined;
  loading?: boolean;
  mode?: PreviewMode;
  onModeChange?: (m: PreviewMode) => void;
  zoom?: PreviewZoom;
  onZoomChange?: (z: PreviewZoom) => void;
  compact?: boolean;
  title?: string;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('components');
  const tt: TFn = (key, opts) => String(t(key, opts));
  const app = useAppInfo().data;
  const [innerMode, setInnerMode] = useState<PreviewMode>('design');
  const [innerZoom, setInnerZoom] = useState<PreviewZoom>('fit');
  const mode = props.mode ?? innerMode;
  const zoom = props.zoom ?? innerZoom;
  const compact = props.compact ?? false;
  const loading = props.loading ?? false;
  const render = props.render;
  const preview = render?.preview ?? null;

  const setMode = (m: PreviewMode) => {
    setInnerMode(m);
    props.onModeChange?.(m);
  };
  const setZoom = (z: PreviewZoom) => {
    setInnerZoom(z);
    props.onZoomChange?.(z);
  };

  const calibrated = app?.screen_px_per_mm != null;
  const screenPxPerMm = app?.screen_px_per_mm ?? DEFAULT_SCREEN_PX_PER_MM;
  const dotsPerMm = app?.profile.dots_per_mm ?? 8;
  const cssPerDot = screenPxPerMm / dotsPerMm;
  const fit = zoom === 'fit';

  let imgStyle: CSSProperties = {};
  if (preview) {
    if (fit) {
      imgStyle = {
        width: '100%',
        height: 'auto',
        maxWidth: `${preview.width * MAX_FIT_FACTOR}px`,
        maxHeight: compact ? FIT_MAX_HEIGHT_COMPACT : FIT_MAX_HEIGHT,
        objectFit: 'contain',
      };
    } else {
      const factor = zoom === '100' ? 1 : zoom;
      imgStyle = { width: `${preview.width * cssPerDot * factor}px`, maxWidth: 'none', maxHeight: 'none' };
    }
  }

  const titleText = props.title ?? render?.title ?? '';
  const raster = mode === 'raster';
  const altBase = titleText
    ? tt(raster ? 'preview.altTitledRaster' : 'preview.altTitled', { title: titleText })
    : tt(raster ? 'preview.altRaster' : 'preview.alt');
  const info = preview ? previewInfoText(preview, tt) : '';
  const balance = preview ? previewBalanceText(preview, tt) : '';
  const alt = preview ? tt('preview.altInfo', { alt: altBase, info }) : tt('preview.alt');

  const showZoom = !compact && Boolean(props.onZoomChange);
  const tapeName = app?.tape.name;

  return (
    <div className={styles.root}>
      {!compact ? (
        <div className={styles.toolbar}>
          <TabList
            size="small"
            selectedValue={mode}
            onTabSelect={(_e, data) => setMode(data.value as PreviewMode)}
            aria-label={t('preview.view')}
          >
            <Tab value="design">{t('preview.design')}</Tab>
            <Tab value="raster">{t('preview.raster')}</Tab>
          </TabList>
          {showZoom ? (
            <div className={styles.zoom} role="group" aria-label={t('preview.zoom')}>
              <Tooltip content={t('preview.fitTooltip')} relationship="description">
                <ToggleButton size="small" appearance="subtle" icon={<ZoomFit20Regular />} checked={fit} onClick={() => setZoom('fit')}>
                  {t('preview.fit')}
                </ToggleButton>
              </Tooltip>
              <Tooltip content={t('preview.actualTooltip')} relationship="description">
                <ToggleButton size="small" appearance="subtle" checked={zoom === '100'} onClick={() => setZoom('100')}>
                  {t('preview.actual')}
                </ToggleButton>
              </Tooltip>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className={mergeClasses(styles.stage, compact && styles.stageCompact, fit && styles.stageFit)} aria-busy={loading}>
        {preview ? (
          <div className={mergeClasses(styles.imageWrap, fit ? styles.imageWrapFit : styles.imageWrapScroll)}>
            <img
              className={mergeClasses('p12-tape-image', styles.image, raster && styles.pixelated, loading && styles.loading)}
              src={pngSrc(raster ? preview.raster_png : preview.design_png)}
              alt={alt}
              style={imgStyle}
              draggable={false}
            />
            {loading ? <div className={styles.shimmer} aria-hidden="true" /> : null}
          </div>
        ) : (
          <span className={styles.placeholder} role="status">
            {loading ? t('preview.rendering') : t('preview.empty')}
          </span>
        )}
      </div>

      {preview ? (
        <div className={mergeClasses(styles.info, compact && styles.infoCompact)} data-testid="preview-info">
          <span>{info}</span>
          {balance ? <span>{balance}</span> : null}
          {!compact && tapeName ? <span>{t('preview.tape', { name: tapeName })}</span> : null}
          {!fit && !calibrated ? <Caption1 className={styles.hint}>{t('preview.uncalibrated')}</Caption1> : null}
        </div>
      ) : null}

      {render ? (
        <WarningList errors={render.errors} warnings={[...render.warnings, ...(preview?.warnings ?? [])]} notes={compact ? [] : render.notes} />
      ) : null}
    </div>
  );
}
