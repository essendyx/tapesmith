/** Textarea „eine Zeile je Eintrag“: Anzeige als Text, beim Verlassen zur Liste normalisiert (leere Zeilen raus). */
import { useEffect, useState } from 'react';
import { Textarea } from '@fluentui/react-components';

export function ListTextarea(props: {
  id?: string;
  value: string[];
  onChange: (lines: string[]) => void;
  rows?: number;
}): JSX.Element {
  const [text, setText] = useState(() => props.value.join('\n'));
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) setText(props.value.join('\n'));
  }, [props.value, focused]);

  return (
    <Textarea
      id={props.id}
      rows={props.rows ?? 3}
      value={text}
      onFocus={() => setFocused(true)}
      onChange={(_e, d) => setText(d.value)}
      onBlur={() => {
        setFocused(false);
        props.onChange(
          text
            .split('\n')
            .map((l) => l.trim())
            .filter((l) => l !== ''),
        );
      }}
    />
  );
}
