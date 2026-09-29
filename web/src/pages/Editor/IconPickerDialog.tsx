/** Icon-Auswahl (Vorbild `gui/panels/icon_picker.py`): Suche, Kategorien, Raster, eigenes Icon hochladen. */
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Input,
  Option,
  Spinner,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import { ArrowUpload20Regular, Search20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { ApiError, authUrl } from '../../api/client';
import { readFileAsB64 } from '../../platform';
import { iconCategories, listIcons, uploadUserIcon } from './editorApi';

const useStyles = makeStyles({
  surface: { maxWidth: '720px', width: 'calc(100vw - 32px)' },
  filters: { display: 'flex', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalS, flexWrap: 'wrap', marginBottom: tokens.spacingVerticalM },
  search: { flexGrow: 1, minWidth: '180px' },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(76px, 1fr))',
    gap: tokens.spacingHorizontalS,
    maxHeight: '48vh',
    overflowY: 'auto',
    padding: tokens.spacingHorizontalXXS,
  },
  tile: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    rowGap: tokens.spacingVerticalXXS,
    height: 'auto',
    padding: tokens.spacingVerticalS,
    minWidth: 0,
  },
  chosen: { outline: `${tokens.strokeWidthThick} solid ${tokens.colorBrandStroke1}` },
  // wie auf dem Band: schwarzes Symbol auf weißem Grund, auch im Dunkelmodus
  img: { width: '40px', height: '40px', backgroundColor: tokens.colorNeutralForegroundStaticInverted, borderRadius: tokens.borderRadiusSmall },
  name: { maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: tokens.fontSizeBase100 },
  error: { color: tokens.colorPaletteRedForeground1 },
  hidden: { position: 'absolute', width: '1px', height: '1px', opacity: 0, overflow: 'hidden' },
});

export function IconPickerDialog(props: { open: boolean; onClose: () => void; onPick: (ref: string) => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [chosen, setChosen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const categories = useQuery({ queryKey: ['icons', 'categories'], queryFn: ({ signal }) => iconCategories(signal), enabled: props.open, staleTime: 5 * 60_000 });
  const icons = useQuery({
    queryKey: ['icons', query, category],
    queryFn: ({ signal }) => listIcons(query, category, 120, signal),
    enabled: props.open,
    staleTime: 60_000,
  });

  const upload = async (file: File) => {
    setError(null);
    try {
      const data = await readFileAsB64(file);
      const res = await uploadUserIcon(file.name.replace(/\.[^.]+$/, ''), data);
      void queryClient.invalidateQueries({ queryKey: ['icons'] });
      props.onPick(res.ref);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('icons.uploadFailed'));
    }
  };

  return (
    <Dialog open={props.open} onOpenChange={(_e, d) => (d.open ? undefined : props.onClose())}>
      <DialogSurface className={styles.surface}>
        <DialogBody>
          <DialogTitle>{t('icons.title')}</DialogTitle>
          <DialogContent>
            <div className={styles.filters}>
              <Input
                className={styles.search}
                contentBefore={<Search20Regular />}
                placeholder={t('icons.placeholder')}
                aria-label={t('icons.search')}
                value={query}
                onChange={(_e, d) => setQuery(d.value)}
              />
              <Dropdown
                aria-label={t('icons.category')}
                value={category ? (categories.data?.labels?.[category] ?? category) : t('icons.all')}
                selectedOptions={[category]}
                onOptionSelect={(_e, d) => setCategory(d.optionValue ?? '')}
              >
                <Option value="">{t('icons.all')}</Option>
                {(categories.data?.categories ?? []).map((c) => (
                  <Option key={c} value={c} text={categories.data?.labels?.[c] ?? c}>
                    {categories.data?.labels?.[c] ?? c}
                  </Option>
                ))}
              </Dropdown>
              <Button icon={<ArrowUpload20Regular />} onClick={() => fileRef.current?.click()}>
                {t('icons.upload')}
              </Button>
              <input
                ref={fileRef}
                className={styles.hidden}
                type="file"
                accept="image/png,image/svg+xml,image/jpeg,image/bmp"
                aria-label={t('icons.file')}
                tabIndex={-1}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = '';
                  if (file) void upload(file);
                }}
              />
            </div>
            {error ? <Caption1 className={styles.error}>{error}</Caption1> : null}
            {icons.isLoading ? <Spinner size="small" label={t('icons.loading')} /> : null}
            <div className={styles.grid} role="listbox" aria-label={t('icons.list')}>
              {(icons.data?.icons ?? []).map((icon) => (
                <Button
                  key={icon.ref}
                  role="option"
                  aria-selected={chosen === icon.ref}
                  appearance="subtle"
                  className={mergeClasses(styles.tile, chosen === icon.ref && styles.chosen)}
                  title={`${icon.name} (${icon.category_label ?? icon.category})`}
                  onClick={() => setChosen(icon.ref)}
                  onDoubleClick={() => props.onPick(icon.ref)}
                >
                  <img className={styles.img} src={authUrl('/api/v1/icons/png', { ref: icon.ref, size: 48 })} alt="" loading="lazy" />
                  <span className={styles.name}>{icon.name}</span>
                </Button>
              ))}
            </div>
            {icons.data && icons.data.icons.length === 0 ? <Caption1>{t('icons.none')}</Caption1> : null}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!chosen} onClick={() => chosen && props.onPick(chosen)}>
              {t('icons.apply')}
            </Button>
            <Button onClick={props.onClose}>{t('icons.cancel')}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
