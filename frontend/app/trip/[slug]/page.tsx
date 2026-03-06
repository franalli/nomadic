import type { Metadata } from 'next';
import { cache } from 'react';

import { type SharedTripData, SharedTripView } from '@/components/shared/SharedTripView';
import { BACKEND_URL } from '@/lib/config';

interface SharedTripFetchResult {
  status: number;
  data: SharedTripData | null;
}

const fetchSharedTrip = cache(async (slug: string): Promise<SharedTripFetchResult> => {
  const res = await fetch(`${BACKEND_URL}/api/shared/${slug}`, {
    cache: 'no-store',
  });
  if (!res.ok) {
    return { status: res.status, data: null };
  }

  const data = (await res.json()) as SharedTripData;
  return { status: 200, data };
});

function getErrorMessage(status: number): string {
  if (status === 404) return 'Trip not found';
  if (status === 410) return 'This shared trip has expired';
  return 'Failed to load trip';
}

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
      initialError={result.data ? null : getErrorMessage(result.status)}
    />
  );
}
