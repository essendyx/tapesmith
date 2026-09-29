/** Reiter „Suche": entprellte Volltextsuche (250 ms) über Gegenstände und ihre Boxen. */
import { useEffect, useRef, useState } from 'react';
import { Input, Text, makeStyles, tokens } from '@fluentui/react-components';
import { Search16Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { errorText } from './errors';
import { EmptyState } from '../../components/EmptyState';
import { useNotify } from '../../components/NotifyProvider';
import type { SearchHitJson } from '../../api/types';
import { searchInventory } from './api';

const DEBOUNCE_MS = 250;

const useStyles = makeStyles({
  field: { maxWidth: '420px', marginBottom: tokens.spacingVerticalL },
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  hit: {
    textAlign: 'left',
    padding: tokens.spacingVerticalS,
    borderRadius: tokens.borderRadiusMedium,
    border: 'none',
    backgroundColor: tokens.colorNeutralBackground1,
    cursor: 'pointer',
    ':hover': { backgroundColor: tokens.colorNeutralBackground1Hover },
  },
});

export function SearchView(props: { onOpenBox: (boxId: string) => void }): JSX.Element {
  const { t } = useTranslation('inventar');
  const styles = useStyles();
  const notify = useNotify();
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchHitJson[]>([]);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    clearTimeout(timer.current);
    if (!query.trim()) {
      setHits([]);
      setSearched(false);
      setSearchError(null);
      return undefined;
    }
    timer.current = setTimeout(() => {
      searchInventory(query)
        .then((r) => {
          setHits(r.hits);
          setSearched(true);
          setSearchError(null);
        })
        .catch((err: unknown) => {
          const text = errorText(err);
          setSearchError(text.title);
          notify({ intent: 'error', ...text });
        });
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer.current);
  }, [query, notify]);

  return (
    <div>
      <Input
        className={styles.field}
        contentBefore={<Search16Regular />}
        placeholder={t('search.placeholder')}
        aria-label={t('search.a11y')}
        value={query}
        onChange={(_e, d) => setQuery(d.value)}
      />
      {searchError ? (
        <EmptyState title={t('search.failed')} body={searchError} />
      ) : searched && hits.length === 0 ? (
        <EmptyState title={t('search.empty.title')} body={t('search.empty.body', { query })} />
      ) : (
        <div className={styles.list}>
          {hits.map((hit, i) => (
            <button
              key={`${hit.item.id}-${i}`}
              type="button"
              className={styles.hit}
              onClick={() => hit.box && props.onOpenBox(hit.box.id)}
              disabled={!hit.box}
            >
              <Text>{hit.text}</Text>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
