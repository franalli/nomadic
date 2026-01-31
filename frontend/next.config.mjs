/** @type {import('next').NextConfig} */
const nextConfig = {
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
        hostname: 'picsum.photos',  // Placeholder images for tiles
      },
    ],
    // Cache optimized images for 1 year (browser + CDN)
    minimumCacheTTL: 31536000,
  },
};

export default nextConfig;
