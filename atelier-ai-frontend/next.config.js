/** @type {import('next').NextConfig} */
const backendBase = (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');

const nextConfig = {
  outputFileTracingRoot: __dirname,
  turbopack: {
    root: __dirname,
  },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${backendBase}/api/:path*` }];
  },
};

module.exports = nextConfig;
