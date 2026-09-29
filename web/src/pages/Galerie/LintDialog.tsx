/** Lint-Dialog (Galerie): zeigt alle Vorlagenprobleme aus GET /templates/lint. */
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Button,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ErrorCircle16Filled, Warning16Filled } from '@fluentui/react-icons';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { fetchLint } from './api';
import { EmptyState } from '../../components/EmptyState';

const useStyles = makeStyles({
  surface: { maxWidth: '560px' },
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS, maxHeight: '420px', overflowY: 'auto' },
  row: { display: 'flex', alignItems: 'flex-start', columnGap: tokens.spacingHorizontalS },
  error: { color: tokens.colorPaletteRedForeground1, flexShrink: 0, marginTop: '2px' },
  warning: { color: tokens.colorPaletteDarkOrangeForeground1, flexShrink: 0, marginTop: '2px' },
  text: { margin: 0 },
  template: { fontWeight: tokens.fontWeightSemibold },
});

export function LintDialog(props: { open: boolean; onOpenChange: (open: boolean) => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('galerie');
  const query = useQuery({
    queryKey: ['gallery-lint'],
    queryFn: ({ signal }) => fetchLint(signal),
    enabled: props.open,
  });
  const issues = query.data?.issues ?? [];

  return (
    <Dialog open={props.open} onOpenChange={(_e, data) => props.onOpenChange(data.open)}>
      <DialogSurface className={styles.surface}>
        <DialogBody>
          <DialogTitle>{t('lint.title')}</DialogTitle>
          <DialogContent>
            {query.isLoading ? (
              <Spinner label={t('lint.loading')} />
            ) : issues.length === 0 ? (
              <EmptyState title={t('lint.emptyTitle')} body={t('lint.emptyBody')} />
            ) : (
              <ul className={styles.list} data-testid="lint-issues">
                {issues.map((issue, i) => (
                  <li key={`${issue.template}-${i}`} className={styles.row}>
                    {issue.level === 'error' ? (
                      <ErrorCircle16Filled className={styles.error} aria-label={t('lint.error')} />
                    ) : (
                      <Warning16Filled className={styles.warning} aria-label={t('lint.warning')} />
                    )}
                    <p className={styles.text}>
                      <span className={styles.template}>{issue.template}: </span>
                      {issue.message}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" onClick={() => props.onOpenChange(false)}>
              {t('lint.close')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
