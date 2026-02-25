import path from 'node:path';

/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      'use-sync-external-store/shim/with-selector.js': path.resolve(
        process.cwd(),
        'lib/use-sync-external-store-shim.js'
      ),
    };

    return config;
  },
  turbopack: {
    resolveAlias: {
      'use-sync-external-store/shim/with-selector.js': './lib/use-sync-external-store-shim.js',
    },
  },
  reactStrictMode: true,
  images: {
    // Enable remote patterns for external images (Unsplash placeholders, partner images)
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'images.unsplash.com',
      },
      {
        protocol: 'https',
        hostname: 'plus.unsplash.com',
      },
      {
        protocol: 'https',
        hostname: '*.unsplash.com',
      },
      {
        protocol: 'https',
        hostname: 'pics.avs.io',  // Airline logos
      },
      {
        protocol: 'https',
        hostname: 'places.googleapis.com',  // Google Places photos
      },
    ],
    // Cache optimized images for 1 year (browser + CDN)
    minimumCacheTTL: 31536000,
  },
  async headers() {
    const isDev = process.env.NODE_ENV === 'development';
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const apiOrigin = (() => {
      try {
        return new URL(apiUrl).origin;
      } catch {
        return 'http://localhost:8000';
      }
    })();
    const csp = [
      "default-src 'self'",
      `script-src 'self' ${isDev ? "'unsafe-eval'" : ""} 'unsafe-inline'`,
      "style-src 'self' 'unsafe-inline'",
      `img-src 'self' ${apiOrigin} https://*.unsplash.com https://images.unsplash.com https://plus.unsplash.com https://pics.avs.io https://places.googleapis.com https://api.mapbox.com https://*.mapbox.com data: blob:`,
      "font-src 'self'",
      `connect-src 'self' https://*.mapbox.com ${apiOrigin}`,
      "worker-src 'self' blob:",
      "frame-src 'none'",
    ].join('; ');

    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          { key: 'Content-Security-Policy', value: csp },
        ],
      },
    ];
  },
};

export default nextConfig;
