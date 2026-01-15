import { LegalPage } from '@/components/nomadic/legal-page';

export const metadata = {
  title: 'Image Credits | Nomadic',
  description: 'Attribution for images used on Nomadic.',
};

export default function CreditsPage() {
  return (
    <LegalPage
      title="Image Credits"
      description="Attribution for photography and imagery used throughout Nomadic."
      sections={[
        {
          title: 'Photography',
          body: (
            <>
              <p>
                Many of the beautiful travel photographs displayed on Nomadic are sourced from{' '}
                <a
                  href="https://unsplash.com?utm_source=nomadic&utm_medium=referral"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary underline"
                >
                  Unsplash
                </a>
                , a platform offering freely usable images under the{' '}
                <a
                  href="https://unsplash.com/license"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary underline"
                >
                  Unsplash License
                </a>
                .
              </p>
              <p className="mt-4">
                We extend our gratitude to the talented photographers who share their work
                and make platforms like Nomadic more visually engaging.
              </p>
            </>
          ),
        },
        {
          title: 'Icons',
          body: (
            <p>
              Icons used throughout Nomadic are provided by{' '}
              <a
                href="https://lucide.dev"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline"
              >
                Lucide
              </a>
              , an open-source icon library.
            </p>
          ),
        },
        {
          title: 'Travel Content',
          body: (
            <p>
              Property images, descriptions, and booking details displayed in search results
              are provided by our travel partners including Expedia Group and Booking.com
              through their respective APIs.
            </p>
          ),
        },
      ]}
    />
  );
}
