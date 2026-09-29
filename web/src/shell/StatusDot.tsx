/** Farbpunkt einer Status-Rolle; immer zusammen mit Text verwenden. */
import { makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import type { Role } from '../api/types';

const useStyles = makeStyles({
  dot: {
    display: 'inline-block',
    width: '10px',
    height: '10px',
    flexShrink: 0,
    borderRadius: tokens.borderRadiusCircular,
    boxShadow: `0 0 0 3px ${tokens.colorNeutralBackground1}`,
  },
  success: { backgroundColor: tokens.colorPaletteGreenBackground3 },
  secondary: { backgroundColor: tokens.colorNeutralForeground3 },
  warning: { backgroundColor: tokens.colorPaletteDarkOrangeBackground3 },
  error: { backgroundColor: tokens.colorPaletteRedBackground3 },
});

export function StatusDot(props: { role: Role }): JSX.Element {
  const styles = useStyles();
  return <span className={mergeClasses(styles.dot, styles[props.role])} aria-hidden="true" data-role={props.role} />;
}
