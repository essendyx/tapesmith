/**
 * Bewegungs-Bausteine. Animationen nur hierüber; die globale Regel im ThemeProvider
 * schaltet sie bei `prefers-reduced-motion` ab.
 */
import { tokens, type GriffelStyle } from '@fluentui/react-components';

const durations = { fast: tokens.durationFast, normal: tokens.durationNormal } as const;

export const motion: {
  fadeIn: GriffelStyle;
  slideUp: GriffelStyle;
  scaleIn: GriffelStyle;
  durations: { fast: string; normal: string };
} = {
  fadeIn: {
    animationName: { from: { opacity: 0 }, to: { opacity: 1 } },
    animationDuration: '150ms',
    animationTimingFunction: tokens.curveDecelerateMid,
    animationFillMode: 'both',
  },
  slideUp: {
    animationName: {
      from: { opacity: 0, transform: 'translateY(6px)' },
      to: { opacity: 1, transform: 'translateY(0)' },
    },
    animationDuration: durations.normal,
    animationTimingFunction: tokens.curveDecelerateMid,
    animationFillMode: 'both',
  },
  scaleIn: {
    animationName: {
      from: { opacity: 0, transform: 'scale(0.98)' },
      to: { opacity: 1, transform: 'scale(1)' },
    },
    animationDuration: durations.normal,
    animationTimingFunction: tokens.curveDecelerateMid,
    animationFillMode: 'both',
  },
  durations,
};
