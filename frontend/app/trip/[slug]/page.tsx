import type { Metadata } from 'next';
import { cache } from 'react';

import { SharedTripView } from '@/components/shared/SharedTripView';
import {
  fetchSharedTripServer,
  getSharedTripErrorMessage,
  type SharedTripFetchResult,
} from '@/lib/sharedTripApi';

const fetchSharedTrip = cache(fetchSharedTripServer);

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params;

  try {
    const { data } = await fetchSharedTrip(slug);
    if (!data) return { title: 'Shared Trip | Nomadic' };

    const title = data.title || 'Shared Trip';
    const dayCount = data.day_count ?? null;
    const destination = data.destination || 'your next destination';
    const description = dayCount
      ? `${dayCount}-day trip to ${destination}`
      : `Shared trip to ${destination}`;
    const image = data.hero_image_url || undefined;

    return {
      title: `${title} | Nomadic`,
      description,
      openGraph: {
        title,
        description,
        type: 'website',
        images: image ? [{ url: image }] : [],
      },
      twitter: {
        card: image ? 'summary_large_image' : 'summary',
        title,
        description,
        images: image ? [image] : [],
      },
    };
  } catch {
    return { title: 'Shared Trip | Nomadic' };
  }
}

export default async function SharedTripPage(
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  let result: SharedTripFetchResult = { status: 500, data: null };
  try {
    result = await fetchSharedTrip(slug);
  } catch {
    result = { status: 500, data: null };
  }
  return (
    <SharedTripView
      slug={slug}
      initialData={result.data}
      initialError={result.data ? null : getSharedTripErrorMessage(result.status)}
    />
  );
}
