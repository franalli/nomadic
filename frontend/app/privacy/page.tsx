import Link from 'next/link';

import { LegalPage } from '@/components/nomadic/legal-page';

export const metadata = {
  title: 'Privacy Policy | Nomadic',
  description:
    'How Nomadic handles your data when planning travel and showing Expedia Rapid API booking details.',
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      description="How we collect, use, and share your information when you plan trips with Nomadic and view direct booking details powered by the Expedia Group Rapid API."
      updated="February 2025"
      sections={[
        {
          title: 'Who we are and how to contact us',
          body: (
            <>
              <p>Nomadic is the controller for personal data processed through this site.</p>
              <p>
                Contact: <a href="mailto:privacy@nomadic.travel" className="text-primary underline">privacy@nomadic.travel</a>. You
                can also use the{' '}
                <Link href="/contact" className="text-primary underline">
                  contact page
                </Link>{' '}
                for data requests.
              </p>
            </>
          ),
        },
        {
          title: 'Information we collect',
          body: (
            <>
              <p>We collect only what is needed to deliver the service:</p>
              <ul className="list-disc space-y-2 pl-5">
                <li>Trip planning inputs you provide (origins, destinations, dates, traveler counts, preferences).</li>
                <li>
                  An essential <code>session_id</code> stored in a secure HttpOnly cookie plus the
                  same identifier in our backend to keep your trip context and chat history tied to
                  this session. The cookie is encrypted and cannot be accessed by JavaScript.
                </li>
                <li>
                  Booking context from the Expedia Group Rapid API when you request live rates or
                  booking details (itinerary IDs, rate keys, property/room identifiers).
                </li>
                <li>
                  Communications you send us (support, privacy, or booking questions) and any
                  identifiers you share (e.g., Expedia itinerary ID).
                </li>
                <li>
                  Device/diagnostic data needed for reliability and security (IP address, browser
                  type, basic logs). We do not record raw payment data; Expedia processes payments.
                </li>
              </ul>
            </>
          ),
        },
        {
          title: 'How we source travel content (no scraping)',
          body: (
            <>
              <p>
                <strong>Nomadic does not scrape websites or use unauthorized data collection methods.</strong>{' '}
                All travel content displayed on our platform is retrieved exclusively through authorized APIs:
              </p>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  The Expedia Group Rapid API provides hotel, flight, and activity listings under an
                  authorized affiliate agreement.
                </li>
                <li>
                  The Booking.com Demand API provides additional accommodation options under authorized
                  partnership terms.
                </li>
                <li>
                  Destination images are sourced from Unsplash under their API license.
                </li>
              </ul>
              <p>
                This ensures all information is accurate, compliant with partner terms, and lawfully obtained.
              </p>
            </>
          ),
        },
        {
          title: 'How we use your information and legal bases (GDPR/UK GDPR)',
          body: (
            <>
              <ul className="list-disc space-y-2 pl-5">
                <li>Delivering trip planning and showing live booking options you request (contract).</li>
                <li>Keeping the platform secure, preventing fraud/abuse, and ensuring reliability (legitimate interests).</li>
                <li>Responding to support or privacy requests (contract/legal obligation).</li>
                <li>Respecting or storing consent choices for non-essential cookies/tech if you opt in (consent). None are active by default today.</li>
              </ul>
            </>
          ),
        },
        {
          title: 'Sharing and transfers',
          body: (
            <>
              <p>We share only what is necessary to provide the service:</p>
              <ul className="list-disc space-y-2 pl-5">
                <li>
                  Expedia Group Rapid API to retrieve live rates and booking details you ask for. Expedia
                  processes payments and confirmations under its own terms.
                </li>
                <li>
                  Booking.com Demand API to retrieve additional accommodation options and booking details.
                  Booking.com processes payments under its own terms.
                </li>
                <li>Infrastructure providers (hosting, databases, monitoring) under confidentiality and data processing terms.</li>
                <li>Service providers for support or compliance (only as needed and under contract).</li>
              </ul>
              <p className="text-sm text-muted-foreground">
                Where data is transferred outside your region, we rely on appropriate safeguards (e.g., DPAs and standard contractual clauses).
              </p>
            </>
          ),
        },
        {
          title: 'Retention',
          body: (
            <>
              <ul className="list-disc space-y-2 pl-5">
                <li>session_id persists until you clear cookies or start a new session in the app. Sessions automatically expire after 90 days or 14 days of inactivity.</li>
                <li>Trip contexts, chat history, and tile clicks are retained for active planning and reliability, then deleted when you request removal or after a limited operational window.</li>
                <li>Expedia itinerary identifiers are kept only as long as needed for booking status or support.</li>
                <li>Support communications are retained as required for compliance and recordkeeping.</li>
              </ul>
            </>
          ),
        },
        {
          title: 'Your rights (GDPR/UK GDPR)',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                Access, correction, deletion, or portability of your personal data.
              </li>
              <li>Objection or restriction where permitted by law (especially for legitimate interests).</li>
              <li>Withdraw consent for any optional processing without affecting past processing.</li>
              <li>
                Lodge a complaint with your supervisory authority; we encourage you to contact us
                first so we can help quickly.
              </li>
            </ul>
          ),
        },
        {
          title: 'Cookies and similar technologies',
          body: (
            <p>
              We store an essential <code>session_id</code> in a secure HttpOnly cookie to keep your trip context
              and chat history. This cookie cannot be accessed by JavaScript, providing enhanced security.
              Functional, analytics, and marketing categories are disabled by
              default and none are active today. Manage choices anytime via the banner or the
              "Manage cookies" link in the footer. See the{' '}
              <Link href="/cookies" className="text-primary underline">
                Cookie Policy
              </Link>{' '}
              for details.
            </p>
          ),
        },
        {
          title: 'Security',
          body: (
            <p>
              We use encryption in transit, access controls, and role-based limits for staff access.
              Please protect your device and avoid reusing credentials across services.
            </p>
          ),
        },
        {
          title: 'Children',
          body: (
            <p>Nomadic is not directed to children under 16, and we do not knowingly collect their data.</p>
          ),
        },
      ]}
      cta={
        <div className="space-y-2">
          <h3 className="text-lg font-semibold">Questions or data requests?</h3>
          <p className="text-text-soft">
            Email us or submit a request on the contact page. For booking-specific questions, please
            include the Expedia itinerary or confirmation ID so we can coordinate with their Rapid
            API support channels.
          </p>
          <Link href="/contact" className="text-primary underline">
            Go to /contact
          </Link>
        </div>
      }
    />
  );
}
