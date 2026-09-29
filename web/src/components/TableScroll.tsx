/**
 * Waagrecht scrollbarer Rahmen für breite Tabellen (bis 200 % Zoom und auf dem
 * Handy kein Abschneiden). Die Seite selbst scrollt nie waagrecht (`main` hat `overflow-x: hidden`),
 * darum scrollt nur die Tabelle in ihrem Rahmen. Der Rahmen ist per Tab erreichbar und benannt,
 * damit er auch ohne Maus scrollbar ist (axe `scrollable-region-focusable`).
 */
import type { ReactNode } from 'react';
import { makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    overflowX: 'auto',
    // Breite 0 plus Mindestbreite 100 %: der Rahmen füllt die Zeile, trägt aber nichts zur
    // Mindestbreite der umgebenden Grid- und Flex-Elemente bei (sonst wüchse die Karte mit).
    width: 0,
    minWidth: '100%',
    borderRadius: tokens.borderRadiusMedium,
    ':focus-visible': { outline: `${tokens.strokeWidthThick} solid ${tokens.colorStrokeFocus2}`, outlineOffset: '2px' },
  },
});

export function TableScroll(props: { label: string; children: ReactNode; className?: string }): JSX.Element {
  const styles = useStyles();
  return (
    <div
      className={props.className ? `${styles.root} ${props.className}` : styles.root}
      role="region"
      aria-label={props.label}
      tabIndex={0}
    >
      {props.children}
    </div>
  );
}
