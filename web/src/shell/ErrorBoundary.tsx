/** Fängt Renderfehler ab und zeigt eine freundliche Karte mit „Neu laden“. */
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowClockwise20Regular, ErrorCircle48Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { CenteredCard } from './NoTokenScreen';

interface State {
  error: Error | null;
}

const useStyles = makeStyles({
  body: { margin: 0, color: tokens.colorNeutralForeground2 },
  detail: {
    margin: 0,
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    overflowWrap: 'anywhere',
  },
});

function CrashCard(props: { message: string }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  return (
    <CenteredCard
      icon={<ErrorCircle48Regular />}
      title={t('errorBoundary.title')}
      action={
        <Button appearance="primary" icon={<ArrowClockwise20Regular />} onClick={() => window.location.reload()}>
          {t('errorBoundary.reload')}
        </Button>
      }
    >
      <p className={styles.body}>{t('errorBoundary.body')}</p>
      <p className={styles.detail}>{props.message}</p>
    </CenteredCard>
  );
}

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: unknown }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('UI crashed', error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: unknown }): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return <CrashCard message={this.state.error.message} />;
  }
}
