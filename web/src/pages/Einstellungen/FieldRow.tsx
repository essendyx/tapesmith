/**
 * Zeilenbaustein der Einstellungsseite im Stil der Windows-11-Einstellungen (Fluent 2): links
 * Beschriftung (normales Gewicht) mit Hilfetext darunter, rechts eine Steuerspalte fester Breite
 * (`form.controlWidth`). Eingabefelder, Zahlenfelder, Auswahllisten und Knöpfe füllen diese Spalte
 * exakt aus, Schalter und Plaketten stehen rechtsbündig darin. Listen-Editoren nutzen
 * `layout="stacked"` (Inhalt in voller Breite unter der Beschriftung). Unter `form.narrow` stehen
 * Beschriftung und Steuerelement untereinander.
 */
import type { ReactNode } from 'react';
import { Badge, Body1, Button, Caption1, Switch, Tooltip, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { form } from '../../theme/layout';

/** Steuerelemente, die die Steuerspalte ausfüllen (mehrere teilen sie sich zu gleichen Teilen). */
const FILL = '& > .fui-Input, & > .fui-SpinButton, & > .fui-Select, & > .fui-Combobox, & > .fui-Dropdown, & > .fui-Button, & > .fui-Textarea';

const useStyles = makeStyles({
  root: {
    display: 'grid',
    gridTemplateColumns: `minmax(0, 1fr) ${form.controlWidth}`,
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalXXL,
    rowGap: tokens.spacingVerticalS,
    minHeight: form.rowMinHeight,
    boxSizing: 'border-box',
    paddingTop: tokens.spacingVerticalM,
    paddingBottom: tokens.spacingVerticalM,
    [form.narrow]: { gridTemplateColumns: 'minmax(0, 1fr)' },
  },
  /** Nur ein kleines Element rechts (Schalter, Plakette): bleibt auch schmal neben der Beschriftung. */
  rootEnd: {
    [form.narrow]: { gridTemplateColumns: 'minmax(0, 1fr) auto' },
  },
  stacked: {
    gridTemplateColumns: 'minmax(0, 1fr)',
  },
  text: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, minWidth: 0 },
  labelLine: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap', rowGap: tokens.spacingVerticalXXS },
  label: { color: tokens.colorNeutralForeground1 },
  heading: {
    margin: 0,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  help: { color: tokens.colorNeutralForeground3, overflowWrap: 'anywhere' },
  control: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    columnGap: tokens.spacingHorizontalS,
    minWidth: 0,
    width: '100%',
    [FILL]: { flex: '1 1 0', minWidth: 0 },
    // Der Schalter hat links und rechts eingebauten Rand: rechts bündig mit den Feldkanten setzen.
    // Oben und unten knapp so viel, dass Schalterzeilen genauso hoch sind wie Zeilen mit Eingabefeld.
    '& > .fui-Switch': {
      marginRight: `calc(-1 * ${tokens.spacingHorizontalS})`,
      marginTop: `calc(-1 * ${tokens.spacingVerticalXXS})`,
      marginBottom: `calc(-1 * ${tokens.spacingVerticalXXS})`,
    },
  },
  content: { minWidth: 0 },
  details: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS, paddingTop: tokens.spacingVerticalXS, minWidth: 0 },
});

/**
 * Hinweis „wirkt nach Neustart“ genau einmal: als eigene Hilfezeile, außer der Hilfetext sagt es schon.
 */
function restartHelp(help: ReactNode, restartText: string): ReactNode[] {
  const lines: ReactNode[] = [];
  if (help) lines.push(help);
  const alreadySaid = typeof help === 'string' && help.trim().toLowerCase() === restartText.trim().toLowerCase();
  if (!alreadySaid) lines.push(restartText);
  return lines;
}

export function FieldRow(props: {
  htmlFor?: string;
  /** ID der Beschriftung, z. B. für `aria-labelledby` einer Gruppe ohne eigenes Eingabefeld. */
  labelId?: string;
  label: ReactNode;
  /** Beschriftung als Überschrift (Semibold), wenn die Zeile einen eigenen Unterabschnitt einleitet. */
  labelAs?: 'h3';
  help?: ReactNode;
  experimental?: boolean;
  restart?: boolean;
  /** Zusätzliche Plaketten hinter der Beschriftung (z. B. ein Status). */
  badges?: ReactNode;
  /** Weitere Angaben unter dem Hilfetext in der Beschriftungsspalte (z. B. ein Fortschrittsbalken). */
  details?: ReactNode;
  control?: ReactNode;
  /** `end`: nur ein kleines Element rechts (Schalter), bleibt auch in schmalen Fenstern daneben. */
  align?: 'fill' | 'end';
  /** `stacked`: `children` in voller Breite unter der Beschriftung (Listen-Editoren, Tabellen). */
  layout?: 'inline' | 'stacked';
  children?: ReactNode;
  className?: string;
}): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const stacked = props.layout === 'stacked';
  // Ohne Steuerelement nutzt der Text die ganze Breite (z. B. ein langer Pfad als Hilfetext).
  const single = stacked || props.control === undefined;
  const helpLines = props.restart ? restartHelp(props.help, t('field.restart')) : props.help ? [props.help] : [];
  const labelText = <Body1 className={styles.label}>{props.label}</Body1>;
  return (
    <div
      className={mergeClasses(
        'p12-field-row',
        styles.root,
        props.align === 'end' && styles.rootEnd,
        single && styles.stacked,
        props.className,
      )}
    >
      <div className={styles.text}>
        <span className={styles.labelLine}>
          {props.labelAs ? (
            <h3 className={styles.heading} id={props.labelId}>
              {props.label}
            </h3>
          ) : props.htmlFor ? (
            <label htmlFor={props.htmlFor} id={props.labelId}>
              {labelText}
            </label>
          ) : (
            <span id={props.labelId}>{labelText}</span>
          )}
          {props.experimental ? (
            <Badge appearance="tint" color="warning" size="small">
              {t('field.experimental')}
            </Badge>
          ) : null}
          {props.badges}
        </span>
        {helpLines.map((line, i) => (
          <Caption1 key={i} className={styles.help}>
            {line}
          </Caption1>
        ))}
        {props.details ? <div className={styles.details}>{props.details}</div> : null}
      </div>
      {props.control !== undefined ? <div className={styles.control}>{props.control}</div> : null}
      {stacked && props.children !== undefined ? <div className={styles.content}>{props.children}</div> : null}
    </div>
  );
}

const useRowsStyles = makeStyles({
  rows: {
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    '& > * + *': { borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}` },
    // Innenabstand der letzten Zeile nicht zusätzlich zum Kartenrand stehen lassen.
    ':last-child': { marginBottom: `calc(-1 * ${tokens.spacingVerticalM})` },
  },
});

/** Liste von `FieldRow`s mit dezenten Trennlinien dazwischen. */
export function FieldRows(props: { children: ReactNode; className?: string }): JSX.Element {
  const styles = useRowsStyles();
  return <div className={mergeClasses(styles.rows, props.className)}>{props.children}</div>;
}

const useControlStyles = makeStyles({
  state: { color: tokens.colorNeutralForeground2 },
  inlineButton: { minWidth: 'auto' },
  value: { color: tokens.colorNeutralForeground2, textAlign: 'right', overflowWrap: 'anywhere', minWidth: 0 },
});

/**
 * Schalter mit „Ein“/„Aus“ davor wie in den Windows-Einstellungen. Der Text ist aria-hidden, weil der
 * Schalter seinen Zustand selbst meldet; der Name kommt aus der `FieldRow`-Beschriftung (`htmlFor`).
 */
export function ToggleControl(props: { id: string; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useControlStyles();
  return (
    <>
      <Body1 className={styles.state} aria-hidden="true">
        {props.checked ? t('field.on') : t('field.off')}
      </Body1>
      <Switch id={props.id} checked={props.checked} disabled={props.disabled} onChange={(_e, d) => props.onChange(d.checked)} />
    </>
  );
}

/** Kleiner Symbolknopf in einem Eingabefeld (Ordner wählen, Zurücksetzen), damit alle Felder gleich breit bleiben. */
export function InlineAction(props: { label: string; icon: JSX.Element; onClick: () => void }): JSX.Element {
  const styles = useControlStyles();
  return (
    <Tooltip content={props.label} relationship="label" withArrow>
      <Button className={styles.inlineButton} size="small" appearance="transparent" icon={props.icon} onClick={props.onClick} />
    </Tooltip>
  );
}

/** Reiner Anzeigewert in der Steuerspalte (rechtsbündig, bricht lange Werte um). */
export function ValueText(props: { children: ReactNode }): JSX.Element {
  const styles = useControlStyles();
  return <Body1 className={styles.value}>{props.children}</Body1>;
}
