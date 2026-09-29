/** Eine Kachel der Galerie: Miniatur, Name, Beschreibung, Stichworte, Favorit, Kontextmenü. */
import { useState, type MouseEvent } from 'react';
import {
  Badge,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  Delete20Regular,
  DocumentArrowRight20Regular,
  Edit20Regular,
  MoreHorizontal20Regular,
  Play20Regular,
  Star20Filled,
  Star20Regular,
  TableSimple20Regular,
} from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { authUrl } from '../../api/client';
import type { TemplateSummary } from '../../api/types';

const useStyles = makeStyles({
  root: {
    position: 'relative',
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXS,
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
    transitionProperty: 'transform, box-shadow',
    transitionDuration: tokens.durationFast,
    transitionTimingFunction: tokens.curveEasyEase,
    ':hover': { transform: 'translateY(-2px)', boxShadow: tokens.shadow8 },
  },
  /**
   * Deckt die ganze Karte transparent ab (öffnet die Vorlage) und ist im DOM das einzige
   * interaktive Element ohne eigene Geschwister-Interaktive innerhalb: Stern und Menü liegen als
   * Geschwister mit höherem `zIndex` darüber (kein verschachteltes Interaktives Element, axe
   * `nested-interactive`).
   */
  openButton: {
    position: 'absolute',
    inset: 0,
    zIndex: 0,
    width: '100%',
    height: '100%',
    padding: 0,
    margin: 0,
    background: 'none',
    border: 'none',
    borderRadius: tokens.borderRadiusXLarge,
    cursor: 'pointer',
    ':focus-visible': { outline: `2px solid ${tokens.colorStrokeFocus2}`, outlineOffset: '2px' },
  },
  body: { position: 'relative', zIndex: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS, pointerEvents: 'none' },
  stage: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '72px',
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground3,
    overflow: 'hidden',
  },
  img: { maxWidth: '100%', height: 'auto', display: 'block' },
  head: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', columnGap: tokens.spacingHorizontalXS },
  name: { margin: 0, fontWeight: tokens.fontWeightSemibold, fontSize: tokens.fontSizeBase300, color: tokens.colorNeutralForeground1 },
  description: {
    margin: 0,
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  },
  tags: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalXXS, rowGap: tokens.spacingVerticalXXS },
  star: {
    position: 'relative',
    zIndex: 1,
    pointerEvents: 'auto',
    background: 'none',
    border: 'none',
    padding: tokens.spacingHorizontalXXS,
    cursor: 'pointer',
    color: tokens.colorPaletteMarigoldForeground1,
    display: 'flex',
    borderRadius: tokens.borderRadiusCircular,
  },
  more: {
    position: 'absolute',
    zIndex: 1,
    pointerEvents: 'auto',
    top: tokens.spacingHorizontalXS,
    right: tokens.spacingHorizontalXS,
    background: 'none',
    border: 'none',
    padding: tokens.spacingHorizontalXXS,
    cursor: 'pointer',
    color: tokens.colorNeutralForeground3,
    display: 'flex',
    borderRadius: tokens.borderRadiusCircular,
  },
});

export function GalleryTile(props: {
  template: TemplateSummary;
  tape: string | undefined;
  favorite: boolean;
  onToggleFavorite: () => void;
  onUse: () => void;
  onEdit: () => void;
  onBatch: () => void;
  onExport: () => void;
  onDelete: () => void;
}): JSX.Element {
  const styles = useStyles();
  const { t: tr } = useTranslation('galerie');
  const { template: t } = props;
  const title = t.title ?? t.name;
  const [thumbError, setThumbError] = useState(false);
  const src = authUrl(`/api/v1/gallery/thumb/${encodeURIComponent(t.name)}.png`, { tape: props.tape ?? '' });

  const onContextMenu = (e: MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
  };

  return (
    <div className={styles.root} onContextMenu={onContextMenu} data-testid={`tile-${t.name}`}>
      <button
        type="button"
        className={styles.openButton}
        aria-label={tr('tile.label', { name: title })}
        onClick={props.onUse}
      />
      <div className={styles.body}>
        <div className={styles.stage}>
          {!thumbError ? (
            <img
              className={styles.img}
              loading="lazy"
              src={src}
              alt={tr('tile.thumbAlt', { name: title })}
              onError={() => setThumbError(true)}
            />
          ) : (
            <span aria-hidden="true">🏷️</span>
          )}
        </div>
        <div className={styles.head}>
          <h3 className={styles.name}>{title}</h3>
          <button
            type="button"
            className={styles.star}
            aria-pressed={props.favorite}
            aria-label={props.favorite ? tr('tile.favoriteRemove') : tr('tile.favoriteAdd')}
            onClick={props.onToggleFavorite}
          >
            {props.favorite ? <Star20Filled /> : <Star20Regular />}
          </button>
        </div>
        {t.description ? <p className={styles.description}>{t.description}</p> : null}
        {t.tags.length > 0 ? (
          <div className={styles.tags}>
            {t.tags.map((tag) => (
              <Badge key={tag} appearance="tint" size="small">
                {tag}
              </Badge>
            ))}
          </div>
        ) : null}
      </div>
      <Menu>
        <MenuTrigger disableButtonEnhancement>
          <Tooltip content={tr('tile.moreActions')} relationship="label">
            <button type="button" className={styles.more} aria-label={tr('tile.moreActionsFor', { name: title })}>
              <MoreHorizontal20Regular />
            </button>
          </Tooltip>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            <MenuItem icon={<Play20Regular />} onClick={props.onUse}>
              {tr('tile.use')}
            </MenuItem>
            <MenuItem icon={<Edit20Regular />} onClick={props.onEdit} disabled={t.kind !== 'document' && t.kind !== 'layout'}>
              {tr('tile.editInEditor')}
            </MenuItem>
            <MenuItem icon={<TableSimple20Regular />} onClick={props.onBatch}>
              {tr('tile.batchImport')}
            </MenuItem>
            <MenuItem icon={<DocumentArrowRight20Regular />} onClick={props.onExport}>
              {tr('common:actions.export')}
            </MenuItem>
            {!t.builtin ? (
              <MenuItem icon={<Delete20Regular />} onClick={props.onDelete}>
                {tr('tile.delete')}
              </MenuItem>
            ) : null}
          </MenuList>
        </MenuPopover>
      </Menu>
    </div>
  );
}
