/// <reference types="vite/client" />

interface PywebviewApi {
  pick_folder?: (title?: string) => Promise<string | null>;
  open_path?: (path: string) => Promise<boolean>;
  close_window?: () => Promise<void>;
  set_title?: (title: string) => Promise<void>;
  retry?: (route?: string) => Promise<void>;
}

interface Window {
  pywebview?: { api?: PywebviewApi };
}
