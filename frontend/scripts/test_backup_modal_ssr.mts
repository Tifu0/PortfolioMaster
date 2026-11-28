import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AppRouterContext } from 'next/dist/shared/lib/app-router-context.shared-runtime';
import { BackupExportModal } from '../components/BackupExportModal';
import { LanguageProvider } from '../context/LanguageContext';
import { ToastProvider } from '../components/ui/Toast';

const router = {
  bfcacheId: 'backup-verification',
  back() {},
  forward() {},
  refresh() {},
  hmrRefresh() {},
  push() {},
  replace() {},
  prefetch() {},
};

const modalCallbacks = { onClose() {}, onSuccess() {}, onError() {}, onDataRestored() {} };

const renderModal = (isOpen: boolean) =>
  renderToStaticMarkup(
    createElement(
      AppRouterContext.Provider,
      { value: router },
      createElement(
        LanguageProvider,
        null,
        createElement(
          ToastProvider,
          null,
          createElement(BackupExportModal, { isOpen, ...modalCallbacks })
        )
      )
    )
  );

const closedMarkup = renderModal(false);
assert.equal(closedMarkup.includes('role="dialog"'), false, 'Closed modal must not render dialog');
assert.ok(closedMarkup.includes('aria-live="polite"'), 'Persistent toast aria-live region must remain mounted');
const dialog = renderModal(true);
assert.ok(/role="dialog"[^>]*aria-label="Backup &amp; Export Center"/.test(dialog), 'The dialog needs an accessible name');
assert.match(dialog, /Download CSV/);
assert.match(dialog, /Restore &amp; Backups/);

console.log('✓ Backup modal SSR dialog and accessibility tests passed');
