import Link from 'next/link';

import { LegalPage } from '@/components/nomadic/legal-page';

export const metadata = {
  title: 'Sitemap | Nomadic',
  description: 'Quick links to Nomadic pages, policies, and Expedia Group Rapid API booking support.',
};

export default function SitemapPage() {
  return (
    <LegalPage
      title="Sitemap"
      description="Quick links to every public-facing page so you can find policies, booking support, and information about how Nomadic uses the Expedia Group Rapid API."
      sections={[
        {
          title: 'Explore Nomadic',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <Link href="/" className="text-primary underline">
                  Home / Trip Planner
                </Link>{' '}
                — start planning trips and exploring recommendations.
              </li>
              <li>
                <Link href="/privacy" className="text-primary underline">
                  Privacy Policy
                </Link>{' '}
                — learn how we handle data and work with Expedia Group.
              </li>
              <li>
                <Link href="/terms" className="text-primary underline">
                  Terms of Service
                </Link>{' '}
                — understand the rules for using Nomadic and booking via Expedia.
              </li>
            </ul>
          ),
        },
        {
          title: 'Policies and support',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <Link href="/cookies" className="text-primary underline">
                  Cookie Policy
                </Link>{' '}
                — how we use cookies and Expedia session identifiers.
              </li>
              <li>
                <Link href="/contact" className="text-primary underline">
                  Contact
                </Link>{' '}
                — reach us for support, data requests, or booking help.
              </li>
            </ul>
          ),
        },
        {
          title: 'Direct booking via Expedia Group Rapid API',
          body: (
            <>
              <p>
                Live rates, availability, and booking fulfillment are supplied by Expedia Group. When
                you request direct booking details we securely pass your search parameters and
                session identifiers to Expedia through their Rapid API. Bookings are processed under
                Expedia&apos;s terms and policies.
              </p>
              <p>
                For itinerary questions, share the Expedia confirmation or itinerary ID with our
                support team so we can coordinate quickly.
              </p>
            </>
          ),
        },
      ]}
      cta={
        <div className="space-y-2">
          <h3 className="text-lg font-semibold">Need something that is not listed?</h3>
          <p className="text-text-soft">
            Reach out and we will point you to the right resource or create one if it helps other
            travelers.
          </p>
          <Link href="/contact" className="text-primary underline">
            Go to /contact
          </Link>
        </div>
      }
    />
  );
}
