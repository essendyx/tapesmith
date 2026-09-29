/** Befehlsregister der Kommandopalette. */

export interface CommandDef {
  id: string;
  title: string;
  group: string;
  keywords?: string[];
  shortcut?: string;
  run: () => void | Promise<void>;
  enabled?: () => boolean;
}

type Listener = () => void;

/**
 * Hält alle registrierten Befehle. Mehrere Registrierungen mit derselben ID sind erlaubt
 * (z. B. `druck.aktuell` beim Seitenwechsel): die jüngste gilt, beim Abmelden kommt die vorige zurück.
 */
export class CommandRegistry {
  private entries: { token: number; command: CommandDef }[] = [];
  private nextToken = 1;
  private listeners = new Set<Listener>();
  /** Steigt bei jeder An- oder Abmeldung (für useSyncExternalStore). */
  version = 0;

  register(commands: CommandDef[]): () => void {
    const tokens = commands.map((command) => {
      const token = this.nextToken;
      this.nextToken += 1;
      this.entries.push({ token, command });
      return token;
    });
    this.emit();
    return () => {
      const set = new Set(tokens);
      this.entries = this.entries.filter((e) => !set.has(e.token));
      this.emit();
    };
  }

  get(id: string): CommandDef | undefined {
    for (let i = this.entries.length - 1; i >= 0; i -= 1) {
      const entry = this.entries[i];
      if (entry && entry.command.id === id) return entry.command;
    }
    return undefined;
  }

  all(): CommandDef[] {
    const seen = new Map<string, CommandDef>();
    for (const { command } of this.entries) seen.set(command.id, command);
    return [...seen.values()];
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private emit(): void {
    this.version += 1;
    for (const fn of [...this.listeners]) fn();
  }
}

export function isEnabled(cmd: CommandDef): boolean {
  try {
    return cmd.enabled ? cmd.enabled() : true;
  } catch {
    return false;
  }
}
