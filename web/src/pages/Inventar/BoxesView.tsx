/** Reiter „Boxen": Kartenraster mit Suche-Übernahme aus der URL (`box`-Parameter). */
import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  CardHeader,
  Caption1,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Add20Regular, Box24Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/EmptyState';
import { ListToolbar } from '../../components/ListToolbar';
import type { BoxJson } from '../../api/types';
import { fetchBoxes } from './api';
import { errorText } from './errors';
import { BoxDetailDialog } from './BoxDetailDialog';
import { NewBoxDialog } from './NewBoxDialog';

const useStyles = makeStyles({
  count: { color: tokens.colorNeutralForeground3 },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
    gap: tokens.spacingHorizontalM,
  },
  card: { cursor: 'pointer' },
});

export function BoxesView(props: { boxIdFromUrl: string | null; onBoxHandled: () => void }): JSX.Element {
  const { t } = useTranslation('inventar');
  const styles = useStyles();
  const [boxes, setBoxes] = useState<BoxJson[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<{ title: string; hint?: string } | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = () => {
    fetchBoxes()
      .then((r) => {
        setBoxes(r.boxes);
        setLoaded(true);
        setLoadError(null);
      })
      .catch((err: unknown) => setLoadError(errorText(err)));
  };

  useEffect(load, []);

  useEffect(() => {
    if (props.boxIdFromUrl) {
      setSelectedId(props.boxIdFromUrl);
      props.onBoxHandled();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.boxIdFromUrl]);

  return (
    <div>
      <ListToolbar
        actions={
          <Button appearance="primary" icon={<Add20Regular />} onClick={() => setNewOpen(true)}>
            {t('boxes.new')}
          </Button>
        }
      >
        {loaded ? <Caption1 className={styles.count}>{t('boxes.count', { count: boxes.length })}</Caption1> : null}
      </ListToolbar>
      {loadError ? (
        <MessageBar intent="error">
          <MessageBarBody>
            <MessageBarTitle>{loadError.title}</MessageBarTitle>
            {loadError.hint}
          </MessageBarBody>
        </MessageBar>
      ) : null}
      {loaded && boxes.length === 0 ? (
        <EmptyState icon={<Box24Regular />} title={t('boxes.empty.title')} body={t('boxes.empty.body')} />
      ) : (
        <div className={styles.grid}>
          {boxes.map((box) => (
            <Card
              key={box.id}
              className={styles.card}
              role="button"
              aria-label={box.id}
              onClick={() => setSelectedId(box.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setSelectedId(box.id);
                }
              }}
            >
              <CardHeader
                image={<Box24Regular />}
                header={<Text weight="semibold">{box.id}</Text>}
                description={<Caption1>{box.location}</Caption1>}
              />
              <Text>{t('boxes.items', { count: box.items })}</Text>
            </Card>
          ))}
        </div>
      )}
      <NewBoxDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={(box) => {
          setNewOpen(false);
          load();
          setSelectedId(box.id);
        }}
      />
      <BoxDetailDialog boxId={selectedId} boxes={boxes} onClose={() => setSelectedId(null)} onChanged={load} />
    </div>
  );
}
