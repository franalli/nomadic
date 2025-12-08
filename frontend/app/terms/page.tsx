import Link from 'next/link';

import { LegalPage } from '@/components/nomadic/legal-page';

export const metadata = {
  title: 'Terms of Service | Nomadic',
  description: 'Nomadic service terms, including how we use Expedia Group Rapid API booking data.',
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      description="The rules for using Nomadic, including how direct booking information from the Expedia Group Rapid API is provided and what you can expect from us."
      updated="February 2025"
      sections={[
        {
          title: 'Using Nomadic',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>Use the product only for lawful, personal travel planning and booking.</li>
              <li>
                You must be able to form a binding contract and use accurate information when
                creating itineraries or booking.
              </li>
              <li>
                You are responsible for safeguarding your account credentials and for all activity
                under your account.
              </li>
            </ul>
          ),
        },
        {
          title: 'Travel content and the Expedia Group Rapid API',
          body: (
            <>
              <p>
                Live rates, availability, and fulfillment details are supplied through the Expedia
                Group Rapid API. Those details come directly from Expedia Group and participating
                suppliers and can change at any time. We display them to help you evaluate options,
                but the final booking is governed by the supplier or Expedia Group.
              </p>
              <p>
                We do not scrape any websites. All travel content we display is obtained through
                authorized APIs—principally the Expedia Group Rapid API—in accordance with supplier
                terms and platform policies.
              </p>
              <p>
                By requesting or completing a booking, you agree to the applicable Expedia Group
                terms, fare rules, and policies for the itinerary you select.
              </p>
            </>
          ),
        },
        {
          title: 'Bookings, payments, and confirmations',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                Payments and confirmations are processed by Expedia Group or the supplier identified
                during checkout. Nomadic facilitates the request and passes your selections securely
                to Expedia via their Rapid API.
              </li>
              <li>
                Pricing, taxes, fees, and cancellation or change rules are provided by Expedia Group
                and may change until the booking is confirmed.
              </li>
              <li>
                If you need to modify or cancel a booking, follow the instructions in the
                confirmation from Expedia Group or contact us with the Expedia itinerary ID so we can
                coordinate support.
              </li>
            </ul>
          ),
        },
        {
          title: 'Privacy, cookies, and data',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                We store an essential <code>session_id</code> in your browser to keep your trip and
                chat context. No analytics or marketing cookies are active today. Manage choices via
                the consent banner or the “Manage cookies” link in the footer.
              </li>
              <li>
                Our data practices, including what is shared with Expedia Group when you request
                booking details, are described in the{' '}
                <Link href="/privacy" className="text-primary underline">
                  Privacy Policy
                </Link>{' '}
                and{' '}
                <Link href="/cookies" className="text-primary underline">
                  Cookie Policy
                </Link>
                .
              </li>
              <li>
                You can request access, correction, or deletion of your data through the contact
                methods in the Privacy Policy.
              </li>
            </ul>
          ),
        },
        {
          title: 'Acceptable use',
          body: (
            <ul className="list-disc space-y-2 pl-5">
              <li>No scraping, bulk harvesting, or automated querying beyond normal product use.</li>
              <li>No attempts to bypass rate limits, security controls, or misrepresent your identity.</li>
              <li>No misuse that violates applicable laws, third-party rights, or supplier policies.</li>
            </ul>
          ),
        },
        {
          title: 'Disclaimers and limitation of liability',
          body: (
            <>
              <p>
                Travel availability and pricing come from third parties. We do not guarantee that
                offers shown will remain available, and we are not responsible for acts or omissions
                of airlines, hotels, activity providers, or Expedia Group.
              </p>
              <p>
                To the fullest extent permitted by law, Nomadic is not liable for indirect,
                incidental, or consequential damages arising from your use of the service. Some
                jurisdictions do not allow these exclusions; where prohibited, they do not apply.
              </p>
            </>
          ),
        },
      ]}
      cta={
        <div className="space-y-2">
          <h3 className="text-lg font-semibold">Need help or have questions?</h3>
          <p className="text-text-soft">
            Visit our contact page for support. For booking assistance, include your Expedia
            itinerary or confirmation number so we can resolve issues quickly with their Rapid API
            team.
          </p>
          <Link href="/contact" className="text-primary underline">
            Go to /contact
          </Link>
        </div>
      }
    />
  );
}
