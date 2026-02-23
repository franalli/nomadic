import { describe, expect, it, vi } from 'vitest';

import {
  buildGooglePlacesPhotoProxyUrl,
  getSignedGooglePlacesPhotoProxyUrl,
  isGooglePlacesPhotoProxyUrl,
  normalizeGooglePlacesPhotoName,
} from '@/lib/googlePlacesPhoto';

describe('google places photo proxy helpers', () => {
  it('builds a backend proxy URL for valid photo names', () => {
    const url = buildGooglePlacesPhotoProxyUrl('places/ChIJx/photos/AbCd_123', {
      maxWidth: 320,
      maxHeight: 240,
    });

    expect(url).toContain('/api/media/google-places-photo?');
    expect(url).toContain('name=places%2FChIJx%2Fphotos%2FAbCd_123');
    expect(url).toContain('max_width=320');
    expect(url).toContain('max_height=240');
  });

  it('rejects invalid photo names', () => {
    expect(normalizeGooglePlacesPhotoName('https://places.googleapis.com/v1/foo')).toBeUndefined();
    expect(buildGooglePlacesPhotoProxyUrl('places/not-valid')).toBeUndefined();
  });

  it('detects proxy URLs (absolute and relative)', () => {
    expect(isGooglePlacesPhotoProxyUrl('/api/media/google-places-photo?name=places%2Fa%2Fphotos%2Fb')).toBe(true);
    expect(isGooglePlacesPhotoProxyUrl('http://test.local/api/media/google-places-photo?name=places%2Fa%2Fphotos%2Fb')).toBe(true);
    expect(isGooglePlacesPhotoProxyUrl('https://images.unsplash.com/photo-abc')).toBe(false);
  });

  it('fetches and caches signed proxy URLs from backend', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            url: '/api/media/google-places-photo?name=places%2FChIJx%2Fphotos%2FAbCd_123&max_width=320&max_height=240&exp=123&sig=testsig',
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }
        )
      );

    const first = await getSignedGooglePlacesPhotoProxyUrl('places/ChIJx/photos/AbCd_123', {
      maxWidth: 320,
      maxHeight: 240,
    });
    const second = await getSignedGooglePlacesPhotoProxyUrl('places/ChIJx/photos/AbCd_123', {
      maxWidth: 320,
      maxHeight: 240,
    });

    expect(first).toContain('/api/media/google-places-photo?');
    expect(second).toBe(first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/media/google-places-photo-url?'),
      expect.objectContaining({ credentials: 'include', cache: 'no-store' })
    );
  });
});
