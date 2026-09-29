/** Reiter „Laufwerke": Wechseldatenträger mit Vorschlag, Drucken oder Übernahme in Schnelldruck. */
import { useEffect, useState } from 'react';
import { Button, Caption1, Card, CardHeader, MessageBar, MessageBarBody, MessageBarTitle, Text, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowSync16Regular, HardDrive24Regular, Print16Regular, TextBulletListSquare16Regular } from '@fluentui/react-icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { errorText } from './errors';
import { EmptyState } from '../../components/EmptyState';
import { usePrint } from '../../components/usePrint';
import type { DriveJson } from '../../api/types';
import { fetchDrives } from './api';

const useStyles = makeStyles({
  toolbar: { display: 'flex', justifyContent: 'flex-end', marginBottom: tokens.spacingVerticalM },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
    gap: tokens.spacingHorizontalM,
  },
  meta: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  suggestion: { display: 'flex', flexDirection: 'column', margin: `${tokens.spacingVerticalS} 0` },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
});

export function DrivesView(): JSX.Element {
  const { t } = useTranslation('datentraeger');
  const styles = useStyles();
  const navigate = useNavigate();
  const print = usePrint();
  const [drives, setDrives] = useState<DriveJson[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<{ title: string; hint?: string } | null>(null);

  const load = () => {
    setLoadError(null);
    fetchDrives()
      .then((r) => {
        setDrives(r.drives);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        setLoaded(true);
        setLoadError(errorText(err));
      });
  };

  useEffect(load, []);

  return (
    <div>
      <div className={styles.toolbar}>
        <Button icon={<ArrowSync16Regular />} onClick={load}>
          {t('drives.refresh')}
        </Button>
      </div>
      {loadError ? (
        <MessageBar intent="error">
          <MessageBarBody>
            <MessageBarTitle>{loadError.title}</MessageBarTitle>
            {loadError.hint || undefined}
          </MessageBarBody>
        </MessageBar>
      ) : loaded && drives.length === 0 ? (
        <EmptyState
          icon={<HardDrive24Regular />}
          title={t('drives.empty.title')}
          body={t('drives.empty.body')}
        />
      ) : (
        <div className={styles.grid}>
          {drives.map((drive) => (
            <Card key={drive.root}>
              <CardHeader
                image={<HardDrive24Regular />}
                header={<Text weight="semibold">{drive.root}</Text>}
                description={<Caption1>{drive.label || t('drives.unlabeled')}</Caption1>}
              />
              <div className={styles.meta}>
                {drive.size_text} · {drive.filesystem || t('drives.unknownFilesystem')} · {drive.bus}
              </div>
              <div className={styles.suggestion}>
                {drive.suggestion.map((line, i) => (
                  <Text key={i}>{line}</Text>
                ))}
              </div>
              <div className={styles.actions}>
                <Button
                  size="small"
                  appearance="primary"
                  icon={<Print16Regular />}
                  onClick={() => void print.run({ kind: 'text', lines: drive.suggestion })}
                  disabled={print.busy}
                >
                  {t('drives.print')}
                </Button>
                <Button
                  size="small"
                  icon={<TextBulletListSquare16Regular />}
                  onClick={() => navigate(`/schnelldruck?text=${encodeURIComponent(drive.suggestion.join('\n'))}`)}
                >
                  {t('drives.adjust')}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
