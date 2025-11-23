import Link from 'next/link';

import { LegalPage } from '@/components/nomadic/legal-page';

export const metadata = {
  title: 'Cookie Policy | Nomadic',
  description:
    'Details on how Nomadic uses cookies and similar technologies, including the essential session_id and Expedia Group Rapid API session data.',
};

export default function CookiesPage() {
  return (
    <LegalPage
      title="Cookie Policy"
      description="How Nomadic uses cookies and similar technologies to run the site, keep sessions secure, and deliver booking details from the Expedia Group Rapid API."
      updated="February 2025"
      sections={[
        {
          title: 'What we store (today)',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <strong>session_id (localStorage)</strong> — essential, created as a random UUID to
                keep your trip planning, chat, and booking context tied to this browser. Sent to our
                backend to look up your session and trip context. Cleared when you choose “Start new
                session” or clear browser storage.
              </li>
              <li>
                <strong>Expedia Rapid API identifiers</strong> — when you request live booking
                details, Expedia may return itinerary IDs, rate keys, or session tokens. They are
                required to fetch prices/availability and are governed by Expedia policies. We do not
                set marketing or analytics cookies from Expedia.
              </li>
              <li>
                <strong>No analytics or marketing cookies are set</strong> at this time. Categories
                for functional, analytics, and marketing remain off by default in the consent banner.
              </li>
            </ul>
          ),
        },
        {
          title: 'Consent and controls',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                Essential storage (session_id) runs without consent because the site cannot function
                without it.
              </li>
              <li>
                Functional, analytics, and marketing categories are off by default. If we ever add
                them, we will block them until you opt in.
              </li>
              <li>
                Use the banner or the “Manage cookies” link in the footer to review or change your
                choices at any time.
              </li>
            </ul>
          ),
        },
        {
          title: 'Optional categories (currently unused)',
          body: (
            <>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  Functional: remembering UI preferences if introduced later. None are set today.
                </li>
                <li>
                  Analytics: privacy-preserving usage measurement. None are loaded unless you opt in.
                </li>
                <li>
                  Marketing: campaign measurement or remarketing. None are active.
                </li>
              </ul>
              <p className="mt-2 text-sm text-slate-600">
                If we enable any of these, we will update this policy, request consent, and keep them
                disabled unless you opt in.
              </p>
            </>
          ),
        },
        {
          title: 'Managing and deleting cookies',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                Open the “Manage cookies” link in the footer at any time to review or change your
                choices.
              </li>
              <li>
                Clear storage via your browser settings if you want to remove the essential
                session_id immediately. Using “Start new session” in the app also clears it and
                deletes the corresponding server-side context when possible.
              </li>
            </ul>
          ),
        },
        {
          title: 'Retention and storage',
          body: (
            <p>
              The session_id persists until you clear it. Expedia itinerary identifiers are retained
              only as long as needed to show booking status or provide support. For more on how we
              handle data, see our{' '}
              <Link href="/privacy" className="text-blue-700 underline">
                Privacy Policy
              </Link>
              .
            </p>
          ),
        },
      ]}
      cta={
        <div className="space-y-2">
          <h3 className="text-lg font-semibold">Questions about cookies?</h3>
          <p className="text-slate-700">
            We are happy to help. Reach out and let us know which device and browser you are using
            plus, if applicable, your Expedia itinerary ID so we can troubleshoot booking flows.
          </p>
          <Link href="/contact" className="text-blue-700 underline">
            Go to /contact
          </Link>
        </div>
      }
    />
  );
}
