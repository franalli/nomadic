'use client';

import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

type ConsentPreferences = {
  essential: true;
  functional: boolean;
  analytics: boolean;
  marketing: boolean;
  updatedAt?: string;
};

const CONSENT_STORAGE_KEY = 'nomadic_consent';
const OPEN_EVENT = 'nomadic-open-consent';

const defaultPreferences: ConsentPreferences = {
  essential: true,
  functional: false,
  analytics: false,
  marketing: false,
};

const safeParsePreferences = (): ConsentPreferences | null => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(CONSENT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ConsentPreferences;
    if (!parsed || typeof parsed !== 'object' || parsed.essential !== true) return null;
    return {
      ...defaultPreferences,
      ...parsed,
      essential: true,
      updatedAt: parsed.updatedAt || new Date().toISOString(),
    };
  } catch (error) {
    if (process.env.NODE_ENV !== 'production') {
      console.warn('Failed to parse consent preferences', error);
    }
    return null;
  }
};

const persistPreferences = (prefs: ConsentPreferences) => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(
    CONSENT_STORAGE_KEY,
    JSON.stringify({ ...prefs, updatedAt: prefs.updatedAt || new Date().toISOString() })
  );
};

export const requestOpenConsentPreferences = () => {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));
};

export function ConsentManager() {
  const [preferences, setPreferences] = useState<ConsentPreferences | null>(null);
  const [showBanner, setShowBanner] = useState(false);
  const [showPanel, setShowPanel] = useState(false);

  useEffect(() => {
    const existing = safeParsePreferences();
    if (existing) {
      setPreferences(existing);
      setShowBanner(false);
    } else {
      setShowBanner(true);
    }
  }, []);

  useEffect(() => {
    const handler = () => setShowPanel(true);
    window.addEventListener(OPEN_EVENT, handler as EventListener);
    return () => window.removeEventListener(OPEN_EVENT, handler as EventListener);
  }, []);

  const draft = useMemo(
    () => preferences || { ...defaultPreferences, updatedAt: new Date().toISOString() },
    [preferences]
  );

  const handleSave = (next: ConsentPreferences) => {
    setPreferences(next);
    persistPreferences(next);
    setShowBanner(false);
    setShowPanel(false);
  };

  const handleAcceptAll = () => {
    handleSave({
      essential: true,
      functional: true,
      analytics: true,
      marketing: true,
      updatedAt: new Date().toISOString(),
    });
  };

  const handleRejectNonEssential = () => {
    handleSave({
      ...defaultPreferences,
      updatedAt: new Date().toISOString(),
    });
  };

  const togglePreference = (key: keyof Omit<ConsentPreferences, 'essential'>) => {
    setPreferences((prev) => {
      const base = prev || draft;
      return { ...base, [key]: !base[key] };
    });
  };

  const renderPanel = () => (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-bg-strong/40 p-4 backdrop-blur-sm">
      <Card className="max-w-lg space-y-4 p-6">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold text-foreground">Cookie & consent settings</h2>
          <p className="text-sm text-muted-foreground">
            We use essential cookies to keep your planning session secure. You can choose whether to
            allow additional categories if we add them later.
          </p>
        </div>

        <div className="space-y-3">
          <label className="flex items-start gap-3 rounded-lg border border-border bg-muted p-3">
            <input type="checkbox" checked readOnly className="mt-1 cursor-not-allowed" />
            <div>
              <div className="text-sm font-semibold text-foreground">Essential (required)</div>
              <p className="text-sm text-muted-foreground">
                Secure session cookie to keep your trip, chat, and booking context tied to this
                browser. Cannot be turned off—use "Start new session" to clear it.
              </p>
            </div>
          </label>

          <label className="flex items-start gap-3 rounded-lg border border-border p-3">
            <input
              type="checkbox"
              checked={draft.functional}
              onChange={() => togglePreference('functional')}
              className="mt-1"
            />
            <div>
              <div className="text-sm font-semibold text-foreground">Functional (optional)</div>
              <p className="text-sm text-muted-foreground">
                Remembering UI preferences if we add them (none set today). Stored only if enabled.
              </p>
            </div>
          </label>

          <label className="flex items-start gap-3 rounded-lg border border-border p-3">
            <input
              type="checkbox"
              checked={draft.analytics}
              onChange={() => togglePreference('analytics')}
              className="mt-1"
            />
            <div>
              <div className="text-sm font-semibold text-foreground">Analytics (optional)</div>
              <p className="text-sm text-muted-foreground">
                Measuring product usage without selling data. Disabled by default; no analytics are
                loaded unless you opt in.
              </p>
            </div>
          </label>

          <label className="flex items-start gap-3 rounded-lg border border-border p-3">
            <input
              type="checkbox"
              checked={draft.marketing}
              onChange={() => togglePreference('marketing')}
              className="mt-1"
            />
            <div>
              <div className="text-sm font-semibold text-foreground">Marketing (optional)</div>
              <p className="text-sm text-muted-foreground">
                Campaign measurement or remarketing if introduced later. Disabled by default; none
                are active today.
              </p>
            </div>
          </label>
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setShowPanel(false)}>
            Cancel
          </Button>
          <Button variant="outline" onClick={handleRejectNonEssential}>
            Reject non-essential
          </Button>
          <Button onClick={() => handleSave({ ...draft, essential: true, updatedAt: new Date().toISOString() })}>
            Save choices
          </Button>
          <Button onClick={handleAcceptAll}>
            Accept all
          </Button>
        </div>
      </Card>
    </div>
  );

  const renderBanner = () => (
    <div className="fixed inset-x-0 bottom-0 z-30 bg-card/95 shadow-lg ring-1 ring-border">
      <div className="container mx-auto flex flex-col gap-3 px-4 py-4 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <p className="text-sm font-semibold text-foreground">Your privacy choices</p>
          <p className="text-sm text-muted-foreground">
            We use essential cookies to keep your trip and booking context. Analytics and marketing
            are off unless you enable them.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => setShowPanel(true)}>
            Manage choices
          </Button>
          <Button variant="ghost" onClick={handleRejectNonEssential}>
            Reject non-essential
          </Button>
          <Button onClick={handleAcceptAll}>Accept all</Button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {showBanner ? renderBanner() : null}
      {showPanel ? renderPanel() : null}
    </>
  );
}
