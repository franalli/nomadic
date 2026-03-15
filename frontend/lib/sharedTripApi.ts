import type { SharedTripData } from '@/components/shared/SharedTripView';
import { API_BASE, BACKEND_URL } from '@/lib/config';

export interface SharedTripFetchResult {
  status: number;
  data: SharedTripData | null;
}

function getSharedTripUrl(baseUrl: string, slug: string): string {
  return `${baseUrl}/api/shared/${slug}`;
}

async function parseSharedTripResponse(res: Response): Promise<SharedTripFetchResult> {
  if (!res.ok) {
    return { status: res.status, data: null };
  }

  const data = (await res.json()) as SharedTripData;
  return { status: 200, data };
}

export function getSharedTripErrorMessage(status: number): string {
  if (status === 404) return 'Trip not found';
  if (status === 410) return 'This shared trip has expired';
  return 'Failed to load trip';
}

export async function fetchSharedTripClient(
  slug: string,
  signal?: AbortSignal,
): Promise<SharedTripData> {
  const result = await parseSharedTripResponse(
    await fetch(getSharedTripUrl(API_BASE, slug), {
      credentials: 'omit',
      signal,
    })
  );
  if (!result.data) throw new Error(getSharedTripErrorMessage(result.status));
  return result.data;
}

export async function fetchSharedTripServer(slug: string): Promise<SharedTripFetchResult> {
  return parseSharedTripResponse(
    await fetch(getSharedTripUrl(BACKEND_URL, slug), {
      cache: 'no-store',
    })
  );
}
