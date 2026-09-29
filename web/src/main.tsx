import { StrictMode, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { initToken } from './api/client';
import { isFamilyPath, LazyFamilyApp } from './pages/Familie';
import { initI18n, resolveLanguage } from './i18n';

// /familie ist eine eigenständige, handyoptimierte Seite mit eigenem Token-Speicher: kein
// initToken() (das würde das Familien-Token sonst als Admin-Sitzung in p12.token ablegen).
const root = document.getElementById('root');
if (root) {
  const isFamily = isFamilyPath(window.location.pathname);
  // Startsprache aus dem Browser; die Admin-Oberfläche folgt danach `app.language` (LanguageSync in App).
  const language = resolveLanguage('auto', navigator.languages);
  initI18n({ language });
  document.documentElement.lang = language;
  if (!isFamily) initToken();
  createRoot(root).render(
    <StrictMode>
      {isFamily ? (
        <Suspense fallback={null}>
          <LazyFamilyApp />
        </Suspense>
      ) : (
        <App />
      )}
    </StrictMode>,
  );
}
