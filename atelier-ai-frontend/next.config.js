/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: 'http://localhost:8787/:path*' }];
  },
  turbopack: { root: '..' },
};
module.exports = nextConfig;
