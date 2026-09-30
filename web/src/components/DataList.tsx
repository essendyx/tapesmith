/**
 * Einheitliche Liste mit Zeilen: ab 900 px Breite eine kompakte Tabelle über die volle
 * Inhaltsbreite, darunter Karten (eine je Zeile). Spaltenarten legen Ausrichtung und Breite fest:
 *
 * - `title`: flexibel, nimmt den restlichen Platz, darf umbrechen (höchstens zwei Zeilen);
 * - `number`: rechtsbündig mit Ziffern gleicher Breite (`tabular-nums`), ohne Umbruch;
 * - `status`: Badge, ohne Umbruch;
 * - `media`: Vorschaubild, feste Breite;
 * - `actions`: rechtsbündig, so schmal wie ihr Inhalt (siehe `RowActions`);
 * - `text` (Standard): ohne Umbruch, außer `wrap`.
 *
 * In der Kartenansicht stehen Vorschau, Titel und Status oben, die übrigen Spalten als
 * „Beschriftung: Wert“ darunter und die Aktionen am Ende. Mit `selection` erhält jede Zeile ein
 * Auswahlkästchen (Kopf: alle auswählen), z. B. für „Als Serie drucken“. Lade-, Fehler- und Leerzustand sind
 * eingebaut (`LoadingState`, `ErrorMessage`, `EmptyState`), damit jede Liste sie gleich zeigt.
 */
import type { ReactNode } from 'react';
import {
  Checkbox,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { EmptyState } from './EmptyState';
import { ErrorMessage } from './ErrorMessage';
import { LoadingState } from './LoadingState';
import { TableScroll } from './TableScroll';
import { useMediaQuery } from './useMediaQuery';

/** Unterhalb dieser Breite zeigen alle Listen Karten statt einer Tabelle. */
export const LIST_NARROW_QUERY = '(max-width: 899px)';

export type ListColumnKind = 'title' | 'text' | 'number' | 'status' | 'media' | 'actions';

export interface ListColumn<T> {
  id: string;
  /** Spaltenkopf; bei `media` und `actions` darf er leer sein (dann nur für Screenreader). */
  header: string;
  cell: (item: T) => ReactNode;
  kind?: ListColumnKind;
  /** Feste oder minimale Breite (CSS), z. B. '120px'. */
  width?: string;
  /** Text darf umbrechen (Standard: nur `title`). */
  wrap?: boolean;
  /** In der Kartenansicht weglassen (z. B. wenn der Wert schon im Titel steht). */
  hideInCard?: boolean;
  /** In der Tabellenansicht weglassen (nur in der Karte zeigen). */
  hideInTable?: boolean;
}

const useStyles = makeStyles({
  table: {
    width: '100%',
    tableLayout: 'auto',
  },
  headCell: {
    whiteSpace: 'nowrap',
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground2,
  },
  cell: {
    paddingTop: tokens.spacingVerticalXS,
    paddingBottom: tokens.spacingVerticalXS,
    verticalAlign: 'middle',
  },
  nowrap: { whiteSpace: 'nowrap' },
  title: {
    width: '100%',
    minWidth: '12rem',
    overflowWrap: 'anywhere',
  },
  number: {
    textAlign: 'right',
    whiteSpace: 'nowrap',
    fontVariantNumeric: 'tabular-nums',
  },
  numberHead: { justifyContent: 'flex-end', textAlign: 'right' },
  actions: { width: '1%', whiteSpace: 'nowrap', textAlign: 'right' },
  select: { width: '44px', paddingLeft: tokens.spacingHorizontalXS, paddingRight: 0 },
  media: { width: '1%', paddingTop: tokens.spacingVerticalXS, paddingBottom: tokens.spacingVerticalXS },
  cellInner: { display: 'flex', alignItems: 'center', minWidth: 0 },
  cellEnd: { justifyContent: 'flex-end' },
  cards: {
    listStyleType: 'none',
    margin: 0,
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalS,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalS,
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
    minWidth: 0,
  },
  cardTop: { display: 'flex', columnGap: tokens.spacingHorizontalM, alignItems: 'flex-start', minWidth: 0 },
  cardHead: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXXS,
    minWidth: 0,
    flexGrow: 1,
  },
  cardTitleRow: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXXS,
    flexWrap: 'wrap',
    minWidth: 0,
  },
  cardTitle: { fontWeight: tokens.fontWeightSemibold, overflowWrap: 'anywhere', minWidth: 0 },
  cardMeta: {
    display: 'grid',
    gridTemplateColumns: 'max-content minmax(0, 1fr)',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXXS,
    margin: 0,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
  },
  cardLabel: { color: tokens.colorNeutralForeground3 },
  cardValue: { margin: 0, overflowWrap: 'anywhere', minWidth: 0, fontVariantNumeric: 'tabular-nums' },
  cardActions: { display: 'flex', justifyContent: 'flex-end' },
});

export interface ListSelection<T> {
  isSelected: (item: T) => boolean;
  onChange: (item: T, selected: boolean) => void;
  onChangeAll: (selected: boolean) => void;
  /** Zugänglicher Name des Kästchens einer Zeile („Auswählen: pmx10“). */
  itemLabel: (item: T) => string;
  /** Zugänglicher Name des Kästchens im Tabellenkopf („Alle auswählen“). */
  allLabel: string;
}

export interface DataListProps<T> {
  items: T[];
  columns: ListColumn<T>[];
  getKey: (item: T) => string | number;
  /** Zugänglicher Name der Tabelle bzw. Kartenliste. */
  label: string;
  /** Erstes Laden (ohne Daten): Platzhalterzeilen. */
  loading?: boolean;
  /** Ladefehler: Fehlermeldung mit „Erneut versuchen“, falls `onRetry` gesetzt. */
  error?: unknown;
  errorTitle?: string;
  onRetry?: () => void;
  /** Leerer Zustand (meist `<EmptyState …/>`); Standard: schlichter Hinweis. */
  empty?: ReactNode;
  emptyTitle?: string;
  /** Kartenansicht erzwingen bzw. eigene Grenze (Standard `LIST_NARROW_QUERY`). */
  narrowQuery?: string;
  /** Zusätzliche Klasse der Tabellenzeile (z. B. hervorgehobene Zeile). */
  rowClassName?: (item: T) => string | undefined;
  className?: string;
  /** Auswahlkästchen je Zeile. */
  selection?: ListSelection<T>;
}

export function DataList<T>(props: DataListProps<T>): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('common');
  const narrow = useMediaQuery(props.narrowQuery ?? LIST_NARROW_QUERY);

  if (props.error && props.items.length === 0) {
    return <ErrorMessage error={props.error} title={props.errorTitle} onRetry={props.onRetry} />;
  }
  if (props.loading && props.items.length === 0) {
    return <LoadingState variant="list" rows={4} />;
  }
  if (props.items.length === 0) {
    return <>{props.empty ?? <EmptyState compact title={props.emptyTitle ?? props.label} />}</>;
  }

  const tableColumns = props.columns.filter((c) => !c.hideInTable);
  const sel = props.selection;
  const selectBox = (item: T): JSX.Element | null =>
    sel ? (
      <Checkbox
        checked={sel.isSelected(item)}
        aria-label={sel.itemLabel(item)}
        onChange={(_e, d) => sel.onChange(item, Boolean(d.checked))}
      />
    ) : null;
  const selectedCount = sel ? props.items.filter((i) => sel.isSelected(i)).length : 0;
  const allState: boolean | 'mixed' =
    selectedCount === 0 ? false : selectedCount === props.items.length ? true : 'mixed';

  if (narrow) {
    const media = props.columns.find((c) => c.kind === 'media' && !c.hideInCard);
    const title = props.columns.find((c) => c.kind === 'title');
    const status = props.columns.filter((c) => c.kind === 'status' && !c.hideInCard);
    const actions = props.columns.find((c) => c.kind === 'actions' && !c.hideInCard);
    const rest = props.columns.filter(
      (c) => !c.hideInCard && c !== media && c !== title && c !== actions && !status.includes(c),
    );
    return (
      <ul className={mergeClasses(styles.cards, props.className)} aria-label={props.label}>
        {props.items.map((item) => (
          <li key={props.getKey(item)} className={styles.card}>
            <div className={styles.cardTop}>
              {selectBox(item)}
              {media ? media.cell(item) : null}
              <div className={styles.cardHead}>
                <div className={styles.cardTitleRow}>
                  <div className={styles.cardTitle}>{title ? title.cell(item) : null}</div>
                  {status.map((c) => (
                    <div key={c.id}>{c.cell(item)}</div>
                  ))}
                </div>
                {rest.length > 0 ? (
                  <dl className={styles.cardMeta}>
                    {rest.map((c) => (
                      <CardField key={c.id} label={c.header} value={c.cell(item)} />
                    ))}
                  </dl>
                ) : null}
              </div>
            </div>
            {actions ? <div className={styles.cardActions}>{actions.cell(item)}</div> : null}
          </li>
        ))}
      </ul>
    );
  }

  const cellClass = (c: ListColumn<T>): string =>
    mergeClasses(
      styles.cell,
      c.kind === 'title' && styles.title,
      c.kind === 'number' && styles.number,
      c.kind === 'actions' && styles.actions,
      c.kind === 'media' && styles.media,
      c.kind !== 'title' && !c.wrap && styles.nowrap,
    );

  return (
    <TableScroll label={t('dataList.region', { label: props.label })} className={props.className}>
      <Table className={styles.table} aria-label={props.label} size="small">
        <TableHeader>
          <TableRow>
            {sel ? (
              <TableHeaderCell className={styles.select}>
                <Checkbox
                  checked={allState}
                  aria-label={sel.allLabel}
                  onChange={(_e, d) => sel.onChangeAll(d.checked === true)}
                />
              </TableHeaderCell>
            ) : null}
            {tableColumns.map((c) => (
              <TableHeaderCell
                key={c.id}
                className={mergeClasses(styles.headCell, c.kind === 'number' && styles.numberHead)}
                style={c.width ? { width: c.width, minWidth: c.width } : undefined}
              >
                {c.header ? (
                  c.kind === 'actions' || c.kind === 'media' ? <span className="p12-visually-hidden">{c.header}</span> : c.header
                ) : null}
              </TableHeaderCell>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {props.items.map((item) => (
            <TableRow key={props.getKey(item)} className={props.rowClassName?.(item)}>
              {sel ? <TableCell className={mergeClasses(styles.cell, styles.select)}>{selectBox(item)}</TableCell> : null}
              {tableColumns.map((c) => (
                <TableCell key={c.id} className={cellClass(c)} style={c.width ? { width: c.width } : undefined}>
                  {c.kind === 'actions' ? (
                    <div className={mergeClasses(styles.cellInner, styles.cellEnd)}>{c.cell(item)}</div>
                  ) : (
                    c.cell(item)
                  )}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableScroll>
  );
}

function CardField(props: { label: string; value: ReactNode }): JSX.Element | null {
  const styles = useStyles();
  if (props.value === null || props.value === undefined || props.value === '') return null;
  return (
    <>
      <dt className={styles.cardLabel}>{props.label}</dt>
      <dd className={styles.cardValue}>{props.value}</dd>
    </>
  );
}
