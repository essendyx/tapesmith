/** Hinweisschirm der Familienseite: kein Token, ungültiges Token, keine Berechtigung, Sperre. */
import { useState } from 'react';
import { Body1, Button, Card, Input, Title2, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';

export type GateVariant = 'invite' | 'invalid' | 'forbidden' | 'ratelimited';

const useStyles = makeStyles({
  root: {
    minHeight: '100%',
    display: 'grid',
    placeItems: 'center',
    padding: tokens.spacingHorizontalXL,
    boxSizing: 'border-box',
  },
  card: {
    width: '100%',
    maxWidth: '360px',
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalM,
    padding: tokens.spacingVerticalXL,
    boxSizing: 'border-box',
  },
  input: { fontSize: '16px' },
  save: { minHeight: '48px', fontSize: tokens.fontSizeBase400 },
});

export function TokenGate(props: { variant: GateVariant; onSubmit?: (token: string) => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('familie');
  const [value, setValue] = useState('');
  const title = t(`gate.${props.variant}.title`);
  const body = t(`gate.${props.variant}.body`);
  const showInput = props.variant === 'invite' || props.variant === 'invalid';

  return (
    <div className={styles.root}>
      <Card className={styles.card}>
        <Title2 as="h1">{title}</Title2>
        <Body1>{body}</Body1>
        {showInput ? (
          <>
            <Input
              className={styles.input}
              type="password"
              placeholder={t('gate.token')}
              aria-label={t('gate.token')}
              value={value}
              onChange={(_e, data) => setValue(data.value)}
            />
            <Button
              className={styles.save}
              appearance="primary"
              size="large"
              disabled={!value.trim()}
              onClick={() => props.onSubmit?.(value.trim())}
            >
              {t('gate.save')}
            </Button>
          </>
        ) : null}
      </Card>
    </div>
  );
}
