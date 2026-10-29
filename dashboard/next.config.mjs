/** @type {import('next').NextConfig} */
const securityHeaders = [
  // The dashboard may not be shown inside another site (prevents tricked clicks).
  {key: 'X-Frame-Options', value: 'DENY'},
  {key: 'Content-Security-Policy', value: "frame-ancestors 'none'"},
  {key: 'X-Content-Type-Options', value: 'nosniff'},
  {key: 'Referrer-Policy', value: 'no-referrer'},
];

const nextConfig = {
  async headers() {
    return [{source: '/:path*', headers: securityHeaders}];
  },
};

export default nextConfig;
