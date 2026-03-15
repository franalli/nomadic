'use client';

import { useEffect, useMemo, useState } from 'react';

import {
  type ConsentPreferenceKey,
  type ConsentPreferences,
  defaultConsentPreferences,
  persistConsentPreferences,
  safeParseConsentPreferences,
  stampConsentPreferences,
} from './consent-manager-storage';
import { ConsentBanner, ConsentPanel } from './ConsentManagerSections';

export function ConsentManager() {
  const [preferences, setPreferences] = useState<ConsentPreferences | null>(null);
  const [showBanner, setShowBanner] = useState(false);
  const [showPanel, setShowPanel] = useState(false);

  useEffect(() => {
    const existing = safeParseConsentPreferences();
    if (existing) {
      setPreferences(existing);
      setShowBanner(false);
    } else {
      setShowBanner(true);
    }
  }, []);

  const draft = useMemo(
    () => preferences || stampConsentPreferences({ ...defaultConsentPreferences }),
    [preferences]
  );

  const handleSave = (next: ConsentPreferences) => {
    setPreferences(next);
    persistConsentPreferences(next);
    setShowBanner(false);
    setShowPanel(false);
  };

  const handleAcceptAll = () => {
    handleSave(stampConsentPreferences({
      ...defaultConsentPreferences,
      functional: true,
      analytics: true,
      marketing: true,
    }));
  };

  const handleRejectNonEssential = () => {
    handleSave(stampConsentPreferences({ ...defaultConsentPreferences }));
  };

  const togglePreference = (key: ConsentPreferenceKey) => {
    setPreferences((prev) => {
      const base = prev || draft;
      return { ...base, [key]: !base[key] };
    });
  };

  return (
    <>
      {showBanner ? (
        <ConsentBanner
          onManage={() => setShowPanel(true)}
          onRejectNonEssential={handleRejectNonEssential}
          onAcceptAll={handleAcceptAll}
        />
      ) : null}
      {showPanel ? (
        <ConsentPanel
          draft={draft}
          onTogglePreference={togglePreference}
          onClose={() => setShowPanel(false)}
          onRejectNonEssential={handleRejectNonEssential}
          onSave={() => handleSave(stampConsentPreferences({ ...draft }))}
          onAcceptAll={handleAcceptAll}
        />
      ) : null}
    </>
  );
}
