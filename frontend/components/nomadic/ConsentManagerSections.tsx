import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

import type { ConsentPreferenceKey, ConsentPreferences } from './consent-manager-storage';

const OPTIONAL_CONSENT_OPTIONS: Array<{
  key: ConsentPreferenceKey;
  title: string;
  description: string;
}> = [
  {
    key: 'functional',
    title: 'Functional (optional)',
    description: 'Remembering UI preferences if we add them (none set today). Stored only if enabled.',
  },
  {
    key: 'analytics',
    title: 'Analytics (optional)',
    description: 'Measuring product usage without selling data. Disabled by default; no analytics are loaded unless you opt in.',
  },
  {
    key: 'marketing',
    title: 'Marketing (optional)',
    description: 'Campaign measurement or remarketing if introduced later. Disabled by default; none are active today.',
  },
] as const;

interface ConsentPanelProps {
  draft: ConsentPreferences;
  onTogglePreference: (key: ConsentPreferenceKey) => void;
  onClose: () => void;
  onRejectNonEssential: () => void;
  onSave: () => void;
  onAcceptAll: () => void;
}

export function ConsentPanel({
  draft,
  onTogglePreference,
  onClose,
  onRejectNonEssential,
  onSave,
  onAcceptAll,
}: ConsentPanelProps) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-bg-strong/40 p-4 backdrop-blur-sm">
      <Card className="max-w-lg space-y-4 p-6">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold text-foreground">Cookie & consent settings</h2>
          <p className="text-sm text-muted-foreground">
            We use essential cookies to keep your planning session secure. You can choose whether to
            allow additional categories if we add them later.
          </p>
        </div>

        <div className="space-y-4">
          <label className="flex items-start gap-3 rounded-lg border border-border bg-muted p-3">
            <input
              type="checkbox"
              checked
              readOnly
              className="mt-1 cursor-not-allowed"
              aria-label="Essential cookies (required)"
            />
            <div>
              <div className="text-sm font-semibold text-foreground">Essential (required)</div>
              <p className="text-sm text-muted-foreground">
                Secure session cookie to keep your trip, chat, and booking context tied to this
                browser. Cannot be turned off, use &quot;Start new session&quot; to clear it.
              </p>
            </div>
          </label>

          {OPTIONAL_CONSENT_OPTIONS.map((option) => (
            <label key={option.key} className="flex items-start gap-3 rounded-lg border border-border p-3">
              <input
                type="checkbox"
                checked={draft[option.key]}
                onChange={() => onTogglePreference(option.key)}
                className="mt-1"
                aria-label={option.title}
              />
              <div>
                <div className="text-sm font-semibold text-foreground">{option.title}</div>
                <p className="text-sm text-muted-foreground">{option.description}</p>
              </div>
            </label>
          ))}
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="outline" onClick={onRejectNonEssential}>
            Reject non-essential
          </Button>
          <Button onClick={onSave}>Save choices</Button>
          <Button onClick={onAcceptAll}>Accept all</Button>
        </div>
      </Card>
    </div>
  );
}

export function ConsentBanner({
  onManage,
  onRejectNonEssential,
  onAcceptAll,
}: {
  onManage: () => void;
  onRejectNonEssential: () => void;
  onAcceptAll: () => void;
}) {
  return (
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
          <Button variant="outline" onClick={onManage}>
            Manage choices
          </Button>
          <Button variant="ghost" onClick={onRejectNonEssential}>
            Reject non-essential
          </Button>
          <Button onClick={onAcceptAll}>Accept all</Button>
        </div>
      </div>
    </div>
  );
}
