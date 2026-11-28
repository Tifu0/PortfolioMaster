/**
 * SSR-safe, fault-tolerant localStorage adapter.
 * Guards against undefined window (SSR/Node), disabled storage (SecurityError),
 * storage quota exhaustion (QuotaExceededError), and corrupt JSON payloads.
 */

function getBrowserStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

export function getStoredString(key: string): string | null {
  const storage = getBrowserStorage();
  if (!storage) return null;
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

export function setStoredString(key: string, value: string): boolean {
  const storage = getBrowserStorage();
  if (!storage) return false;
  try {
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function getStoredJson<T>(
  key: string,
  fallback: T,
  validate?: (value: unknown) => value is T
): T {
  const raw = getStoredString(key);
  if (raw === null) return fallback;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (validate && !validate(parsed)) {
      return fallback;
    }
    return parsed as T;
  } catch {
    return fallback;
  }
}

export function setStoredJson<T>(key: string, value: T): boolean {
  try {
    return setStoredString(key, JSON.stringify(value));
  } catch {
    return false;
  }
}

export function removeStoredItem(key: string): boolean {
  const storage = getBrowserStorage();
  if (!storage) return false;
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}
