export type ConsentPreferences = {
  essential: true;
  functional: boolean;
  analytics: boolean;
  marketing: boolean;
  updatedAt?: string;
};

export type ConsentPreferenceKey = keyof Omit<ConsentPreferences, 'essential' | 'updatedAt'>;

const CONSENT_STORAGE_KEY = 'nomadic_consent';

export const defaultConsentPreferences: ConsentPreferences = {
  essential: true,
  functional: false,
  analytics: false,
  marketing: false,
};

export function stampConsentPreferences(preferences: ConsentPreferences): ConsentPreferences {
  return {
    ...preferences,
    essential: true,
    updatedAt: preferences.updatedAt || new Date().toISOString(),
  };
}

export function safeParseConsentPreferences(): ConsentPreferences | null {
  if (typeof window === 'undefined') return null;

  try {
    const raw = window.localStorage.getItem(CONSENT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ConsentPreferences;
    if (!parsed || typeof parsed !== 'object' || parsed.essential !== true) return null;
    return stampConsentPreferences({
      ...defaultConsentPreferences,
      ...parsed,
      essential: true,
    });
  } catch (error) {
    if (process.env.NODE_ENV !== 'production') {
      console.error('Failed to parse consent preferences', error);
    }
    return null;
  }
}

export function persistConsentPreferences(preferences: ConsentPreferences) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(
    CONSENT_STORAGE_KEY,
    JSON.stringify(stampConsentPreferences(preferences))
  );
}
