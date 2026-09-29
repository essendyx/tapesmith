/** JSON-Editor für `ssh.hosts`: Tabelle Name, Host, Benutzer, Port, Schlüssel-Pfad. */
import { Body1, Button, Input, makeStyles, tokens } from '@fluentui/react-components';
import { Add20Regular, Delete20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import type { SshHostJson } from '../../../api/types';
import { TableScroll } from '../../../components/TableScroll';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', alignItems: 'flex-start', rowGap: tokens.spacingVerticalS, width: '100%' },
  table: { width: '100%', minWidth: '600px', borderCollapse: 'collapse', tableLayout: 'fixed' },
  th: {
    textAlign: 'left',
    fontWeight: tokens.fontWeightRegular,
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    paddingBottom: tokens.spacingVerticalXS,
    paddingRight: tokens.spacingHorizontalS,
  },
  td: { paddingRight: tokens.spacingHorizontalS, paddingBottom: tokens.spacingVerticalS, verticalAlign: 'middle' },
  tdLast: { paddingRight: 0, paddingBottom: tokens.spacingVerticalS, verticalAlign: 'middle', textAlign: 'right' },
  input: { width: '100%', minWidth: 0 },
  colName: { width: '18%' },
  colHost: { width: '22%' },
  colUser: { width: '16%' },
  colPort: { width: '88px' },
  colAction: { width: '40px' },
  empty: { color: tokens.colorNeutralForeground3 },
});

function emptyHost(): SshHostJson {
  return { name: '', host: '', user: '', port: 22, key: '' };
}

function isSshHostArray(value: unknown): value is SshHostJson[] {
  return Array.isArray(value);
}

export function SshHostsEditor(props: { fieldId: string; value: unknown; onChange: (rows: SshHostJson[]) => void }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const rows = isSshHostArray(props.value) ? props.value : [];

  const update = (index: number, patch: Partial<SshHostJson>) => {
    const next = rows.map((r, i) => (i === index ? { ...r, ...patch } : r));
    props.onChange(next);
  };
  const remove = (index: number) => {
    props.onChange(rows.filter((_, i) => i !== index));
  };
  const add = () => {
    props.onChange([...rows, emptyHost()]);
  };

  return (
    <div className={styles.root} id={props.fieldId}>
      {rows.length > 0 ? (
        <TableScroll label={t('sshHosts.tableAria')}>
          <table className={styles.table}>
            <colgroup>
              <col className={styles.colName} />
              <col className={styles.colHost} />
              <col className={styles.colUser} />
              <col className={styles.colPort} />
              <col />
              <col className={styles.colAction} />
            </colgroup>
            <thead>
              <tr>
                <th className={styles.th}>{t('sshHosts.name')}</th>
                <th className={styles.th}>{t('sshHosts.host')}</th>
                <th className={styles.th}>{t('sshHosts.user')}</th>
                <th className={styles.th}>{t('sshHosts.port')}</th>
                <th className={styles.th}>{t('sshHosts.key')}</th>
                <th className={styles.th} />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td className={styles.td}>
                    <Input className={styles.input} value={row.name} aria-label={t('sshHosts.name')} onChange={(_e, d) => update(i, { name: d.value })} />
                  </td>
                  <td className={styles.td}>
                    <Input className={styles.input} value={row.host} aria-label={t('sshHosts.host')} onChange={(_e, d) => update(i, { host: d.value })} />
                  </td>
                  <td className={styles.td}>
                    <Input className={styles.input} value={row.user} aria-label={t('sshHosts.user')} onChange={(_e, d) => update(i, { user: d.value })} />
                  </td>
                  <td className={styles.td}>
                    <Input
                      className={styles.input}
                      type="number"
                      value={String(row.port)}
                      aria-label={t('sshHosts.port')}
                      onChange={(_e, d) => update(i, { port: Number(d.value) || 0 })}
                    />
                  </td>
                  <td className={styles.td}>
                    <Input
                      className={styles.input}
                      value={row.key}
                      title={row.key || undefined}
                      aria-label={t('sshHosts.key')}
                      onChange={(_e, d) => update(i, { key: d.value })}
                    />
                  </td>
                  <td className={styles.tdLast}>
                    <Button
                      appearance="subtle"
                      icon={<Delete20Regular />}
                      aria-label={t('field.removeRow', { row: i + 1 })}
                      onClick={() => remove(i)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      ) : (
        <Body1 className={styles.empty}>{t('sshHosts.empty')}</Body1>
      )}
      <Button appearance="secondary" icon={<Add20Regular />} onClick={add}>
        {t('field.addRow')}
      </Button>
    </div>
  );
}
