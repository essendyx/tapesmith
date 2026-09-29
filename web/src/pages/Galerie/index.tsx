/** Galerie: Kacheln nach Kategorie mit echter Bandvorschau, Favoriten, zuletzt verwendet,
 * Suche auch in Feldnamen, Import/Export als Paket, Vorlagen-Lint. */
import { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Input,
  Tab,
  TabList,
  makeStyles,
  tokens,
  type SelectTabData,
  type SelectTabEvent,
} from '@fluentui/react-components';
import {
  ArrowImport20Regular,
  DocumentSearch20Regular,
  FolderOpen20Regular,
  Search20Regular,
} from '@fluentui/react-icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { useAppInfo } from '../../api/core';
import type { TemplateSummary } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { Section } from '../../components/Section';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import { isAppWindow, openPath, readFileAsB64 } from '../../platform';
import { deleteTemplate, exportPackage, fetchGallery, importPackage, setFavorite } from './api';
import { GalleryTile } from './GalleryTile';
import { LintDialog } from './LintDialog';
import { useDebounced } from './useDebounced';

const ALL_CATEGORY = '__alle__';

const useStyles = makeStyles({
  toolbar: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: tokens.spacingHorizontalM, rowGap: tokens.spacingVerticalS, marginBottom: tokens.spacingVerticalL },
  search: { minWidth: '240px', flexGrow: 1, maxWidth: '360px' },
  tabsWrap: { overflowX: 'auto', maxWidth: '100%' },
  sections: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXL },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: tokens.spacingHorizontalM },
});

export default function GaleriePage(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('galerie');
  const navigate = useNavigate();
  const notify = useNotify();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const app = useAppInfo();

  const [searchInput, setSearchInput] = useState('');
  const debouncedQuery = useDebounced(searchInput, 200);
  const [category, setCategory] = useState<string>(ALL_CATEGORY);
  const [lintOpen, setLintOpen] = useState(false);
  const [optimisticFavorites, setOptimisticFavorites] = useState<Record<string, boolean>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);

  const queryKey = useMemo(() => ['gallery', debouncedQuery, category === ALL_CATEGORY ? null : category] as const, [debouncedQuery, category]);
  const gallery = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchGallery(debouncedQuery, category === ALL_CATEGORY ? null : category, signal),
  });

  const data = gallery.data;
  const tape = app.data?.tape.id;

  const favoriteNames = useMemo(() => new Set(data?.favorites ?? []), [data]);
  const recentNames = useMemo(() => data?.recent ?? [], [data]);
  const byName = useMemo(() => {
    const map = new Map<string, TemplateSummary>();
    for (const cat of data?.categories ?? []) {
      for (const t of cat.templates) map.set(t.name, t);
    }
    return map;
  }, [data]);

  const isFavorite = (name: string): boolean => optimisticFavorites[name] ?? favoriteNames.has(name);

  const toggleFavorite = (name: string) => {
    const next = !isFavorite(name);
    setOptimisticFavorites((prev) => ({ ...prev, [name]: next }));
    setFavorite(name, next).then(
      () => {
        void queryClient.invalidateQueries({ queryKey: ['gallery'] });
      },
      (err: unknown) => {
        setOptimisticFavorites((prev) => ({ ...prev, [name]: !next }));
        notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.favoriteFailed') });
      },
    );
  };

  const goToTemplate = (name: string) => navigate(`/vorlagen?vorlage=${encodeURIComponent(name)}`);
  const editTemplate = (name: string) => navigate(`/editor?vorlage=${encodeURIComponent(name)}`);
  const batchTemplate = (name: string) => navigate(`/vorlagen?vorlage=${encodeURIComponent(name)}&serie=1`);

  const exportTemplate = async (name: string) => {
    try {
      await exportPackage([name]);
      notify({ intent: 'success', title: t('notify.exported', { name }) });
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.exportFailed') });
    }
  };

  const removeTemplate = async (name: string) => {
    const ok = await confirm({
      title: t('deleteDialog.title'),
      message: t('deleteDialog.message', { name }),
      confirmText: t('deleteDialog.confirm'),
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteTemplate(name);
      notify({ intent: 'success', title: t('notify.deleted', { name }) });
      void queryClient.invalidateQueries({ queryKey: ['gallery'] });
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.deleteFailed') });
    }
  };

  const onImportFile = async (file: File) => {
    const overwrite = await confirm({
      title: t('importDialog.title'),
      message: t('importDialog.message'),
      confirmText: t('importDialog.confirm'),
      cancelText: t('importDialog.cancel'),
    });
    try {
      const b64 = await readFileAsB64(file);
      const res = await importPackage(b64, overwrite);
      notify({
        intent: 'success',
        title: res.imported.length ? t('notify.imported', { names: res.imported.join(', ') }) : t('notify.importedNothing'),
      });
      void queryClient.invalidateQueries({ queryKey: ['gallery'] });
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.importFailed') });
    }
  };

  const renderTile = (t: TemplateSummary) => (
    <GalleryTile
      key={t.name}
      template={t}
      tape={tape}
      favorite={isFavorite(t.name)}
      onToggleFavorite={() => toggleFavorite(t.name)}
      onUse={() => goToTemplate(t.name)}
      onEdit={() => editTemplate(t.name)}
      onBatch={() => batchTemplate(t.name)}
      onExport={() => void exportTemplate(t.name)}
      onDelete={() => void removeTemplate(t.name)}
    />
  );

  const favTemplates = useMemo(() => (data?.favorites ?? []).map((n) => byName.get(n)).filter((t): t is TemplateSummary => Boolean(t)), [data, byName]);
  const recentTemplates = useMemo(() => recentNames.map((n) => byName.get(n)).filter((t): t is TemplateSummary => Boolean(t)), [recentNames, byName]);

  const totalCount = (data?.categories ?? []).reduce((sum, c) => sum + c.templates.length, 0);
  const nothingFound = !gallery.isLoading && totalCount === 0 && favTemplates.length === 0 && recentTemplates.length === 0;
  const filterActive = Boolean(debouncedQuery) || category !== ALL_CATEGORY;
  const resetSearch = () => {
    setSearchInput('');
    setCategory(ALL_CATEGORY);
  };

  return (
    <>
      <PageHeader
        title={t('title')}
        subtitle={t('subtitle')}
        actions={
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (file) void onImportFile(file);
              }}
            />
            <Button icon={<ArrowImport20Regular />} onClick={() => fileInputRef.current?.click()}>
              {t('actions.import')}
            </Button>
            <Button icon={<DocumentSearch20Regular />} onClick={() => setLintOpen(true)}>
              {t('actions.lintAll')}
            </Button>
            {isAppWindow() && data ? (
              <Button icon={<FolderOpen20Regular />} onClick={() => void openPath(data.templates_dir)}>
                {t('actions.openFolder')}
              </Button>
            ) : null}
          </>
        }
      />

      <div className={styles.toolbar}>
        <Input
          className={styles.search}
          contentBefore={<Search20Regular />}
          placeholder={t('search.placeholder')}
          value={searchInput}
          onChange={(_e, d) => setSearchInput(d.value)}
          aria-label={t('search.label')}
        />
        <div className={styles.tabsWrap}>
          <TabList
            selectedValue={category}
            onTabSelect={(_e: SelectTabEvent, d: SelectTabData) => setCategory(String(d.value))}
            size="small"
          >
            <Tab value={ALL_CATEGORY}>{t('tabs.all')}</Tab>
            {(data?.categories ?? []).map((c) => (
              <Tab key={c.name} value={c.name}>
                {c.name}
              </Tab>
            ))}
          </TabList>
        </div>
      </div>

      {gallery.isLoading ? (
        <LoadingState variant="section" label={t('loading')} />
      ) : nothingFound ? (
        <EmptyState
          title={t('empty.title')}
          body={t('empty.body')}
          action={filterActive ? <Button onClick={resetSearch}>{t('empty.reset')}</Button> : undefined}
        />
      ) : (
        <div className={styles.sections}>
          {favTemplates.length > 0 ? (
            <Section title={t('sections.favorites')}>
              <div className={styles.grid}>{favTemplates.map(renderTile)}</div>
            </Section>
          ) : null}
          {recentTemplates.length > 0 ? (
            <Section title={t('sections.recent')}>
              <div className={styles.grid}>{recentTemplates.map(renderTile)}</div>
            </Section>
          ) : null}
          {(data?.categories ?? [])
            .filter((c) => c.templates.length > 0)
            .map((c) => (
              <Section title={c.name} key={c.name}>
                <div className={styles.grid}>{c.templates.map(renderTile)}</div>
              </Section>
            ))}
        </div>
      )}

      <LintDialog open={lintOpen} onOpenChange={setLintOpen} />
    </>
  );
}
