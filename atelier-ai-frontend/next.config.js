const path = require('path');

/** @type {import('next').NextConfig} */
const backendBase = (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');

const nextConfig = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${backendBase}/api/:path*` }];
  },
  turbopack: { root: path.resolve(__dirname) },
};

module.exports = nextConfig;
