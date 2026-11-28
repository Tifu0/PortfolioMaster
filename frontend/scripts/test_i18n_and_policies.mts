import assert from 'node:assert/strict';
import { translations } from '../lib/translations';
import { ApiError } from '../lib/api';
import {
  isExpectedUnauthError,
  shouldFetchBackupsOnTabOpen,
  shouldLoadInstrumentsOnModalOpen,
} from '../lib/modal-policies';

function extractPlaceholders(text: string): string[] {
  return Array.from(text.matchAll(/\{[a-zA-Z0-9_]+\}/g), (m) => m[0]).sort();
}

function runI18nSymmetryTests() {
  const enKeys = Object.keys(translations.en).sort();
  const esKeys = Object.keys(translations.es).sort();
  assert.deepEqual(enKeys, esKeys, 'EN and ES translation keys must match symmetrically');

  assert.equal(
    'fastApiStatus' in translations.en,
    false,
    'Retired fastApiStatus dead key must be removed from translations.ts'
  );

  for (const key of enKeys) {
    const enVal = translations.en[key as keyof typeof translations.en];
    const esVal = translations.es[key as keyof typeof translations.es];
    assert.equal(typeof enVal, 'string');
    assert.equal(typeof esVal, 'string');
    assert.ok(enVal.trim().length > 0, `Empty EN translation for ${key}`);
    assert.ok(esVal.trim().length > 0, `Empty ES translation for ${key}`);
    assert.deepEqual(
      extractPlaceholders(enVal),
      extractPlaceholders(esVal),
      `Mismatched interpolation placeholders for key "${key}"`
    );
    assert.equal(
      /sqlite/i.test(enVal),
      false,
      `Outdated SQLite reference found in EN translation "${key}": ${enVal}`
    );
    assert.equal(
      /sqlite/i.test(esVal),
      false,
      `Outdated SQLite reference found in ES translation "${key}": ${esVal}`
    );
  }
}

function runModalAndUnauthPolicyTests() {
  // Never fetch instruments in Add mode
  assert.equal(
    shouldLoadInstrumentsOnModalOpen({
      isEditMode: false,
      isAuthConfigured: true,
      isAuthenticated: true,
      hasInitialTicker: false,
    }),
    false
  );

  // Never fetch instruments when unauthenticated under configured Supabase Auth
  assert.equal(
    shouldLoadInstrumentsOnModalOpen({
      isEditMode: true,
      isAuthConfigured: true,
      isAuthenticated: false,
      hasInitialTicker: false,
    }),
    false
  );

  // Fetch when editing without an explicit ticker and authenticated (or local unconfigured auth)
  assert.equal(
    shouldLoadInstrumentsOnModalOpen({
      isEditMode: true,
      isAuthConfigured: true,
      isAuthenticated: true,
      hasInitialTicker: false,
    }),
    true
  );
  assert.equal(
    shouldLoadInstrumentsOnModalOpen({
      isEditMode: true,
      isAuthConfigured: false,
      isAuthenticated: false,
      hasInitialTicker: false,
    }),
    true
  );

  // When an explicit tickerToEdit is provided, load that instrument directly instead of listing all
  assert.equal(
    shouldLoadInstrumentsOnModalOpen({
      isEditMode: true,
      isAuthConfigured: true,
      isAuthenticated: true,
      hasInitialTicker: true,
    }),
    false
  );

  // Backup tab auto-fetch policy
  assert.equal(shouldFetchBackupsOnTabOpen({ activeTab: 'export', isAuthConfigured: true, isAuthenticated: true }), false);
  assert.equal(shouldFetchBackupsOnTabOpen({ activeTab: 'backup', isAuthConfigured: true, isAuthenticated: false }), false);
  assert.equal(shouldFetchBackupsOnTabOpen({ activeTab: 'backup', isAuthConfigured: true, isAuthenticated: true }), true);
  assert.equal(shouldFetchBackupsOnTabOpen({ activeTab: 'backup', isAuthConfigured: false, isAuthenticated: false }), true);

  // Expected 401 silence policy
  assert.equal(isExpectedUnauthError(new ApiError('Unauthorized', 401)), true);
  assert.equal(isExpectedUnauthError(new ApiError('Server Error', 500)), false);
  assert.equal(isExpectedUnauthError(new Error('Network error')), false);
}

runI18nSymmetryTests();
runModalAndUnauthPolicyTests();
console.log('✓ Behavioral i18n and modal policy tests passed');
