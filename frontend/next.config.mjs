/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  // Allow cross-origin requests to local backend in dev
  async rewrites() {
    return [
      {
        source: '/api/backend/:path*',
        destination: `${(process.env.NEXT_PUBLIC_API_URL || '').trim() || 'http://localhost:8000'}/:path*`,
      },
    ];
  },
};

export default nextConfig;
