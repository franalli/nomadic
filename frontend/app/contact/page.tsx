import Link from 'next/link';

import { LegalPage } from '@/components/nomadic/legal-page';

export const metadata = {
  title: 'Contact Nomadic | Support & Compliance',
  description:
    'Reach Nomadic for support, booking assistance, or data/privacy requests tied to Expedia Group Rapid API bookings.',
};

export default function ContactPage() {
  return (
    <LegalPage
      title="Contact Nomadic"
      description="We are here to help with trip planning, booking questions, and data or privacy requests—especially when your itinerary involves Expedia Group Rapid API bookings."
      updated="May 2024"
      sections={[
        {
          title: 'Customer support',
          body: (
            <>
              <p>
                For general questions or help using Nomadic, email us at{' '}
                <a href="mailto:support@nomadic-planner.com" className="text-primary underline">
                  support@nomadic-planner.com
                </a>
                . Please include a brief description of the issue and any relevant screenshots.
              </p>
              <p>
                Booking questions move faster if you share the Expedia itinerary or confirmation ID
                you received during checkout.
              </p>
            </>
          ),
        },
        {
          title: 'Privacy and data requests',
          body: (
            <p>
              To request access, correction, or deletion of your data, email{' '}
              <a href="mailto:support@nomadic-planner.com" className="text-primary underline">
                support@nomadic-planner.com
              </a>{' '}
              with the email associated with your account. We will confirm your identity before
              completing the request. See our{' '}
              <Link href="/privacy" className="text-primary underline">
                Privacy Policy
              </Link>{' '}
              for details.
            </p>
          ),
        },
        {
          title: 'Expedia Group Rapid API bookings',
          body: (
            <>
              <p>
                If your question involves direct booking information powered by the Expedia Group
                Rapid API, include:
              </p>
              <ul className="list-disc space-y-2 pl-5">
                <li>The Expedia itinerary or confirmation ID.</li>
                <li>The property, flight, or activity name you selected.</li>
                <li>Your travel dates and the email used during checkout.</li>
              </ul>
              <p>
                This lets us coordinate with Expedia Group and resolve pricing, availability, or
                fulfillment questions quickly.
              </p>
            </>
          ),
        },
        {
          title: 'Response times and hours',
          body: (
            <p>
              We typically respond within one business day. Time-sensitive booking issues (e.g.,
              same-day check-in or imminent departures) are prioritized. If you contact us outside of
              business hours, we will respond as soon as possible the next day.
            </p>
          ),
        },
      ]}
      cta={
        <div className="space-y-2">
          <h3 className="text-lg font-semibold">Need to report an urgent issue?</h3>
          <p className="text-text-soft">
            Flag the message subject with "Urgent" and include your Expedia itinerary ID so we can
            escalate with their Rapid API support channels immediately.
          </p>
        </div>
      }
    />
  );
}
