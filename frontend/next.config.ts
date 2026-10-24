import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    optimizePackageImports: ['lucide-react', '@tanstack/react-table'],
  },
  async rewrites() {
    const rawBackend = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || process.env.BACKEND_URL;
    const isVercel = process.env.VERCEL === "1";
    const isProduction = process.env.NODE_ENV === "production" || isVercel;

    if (!rawBackend && isVercel) {
      throw new Error(
        "[Deployment Configuration Error] API_BASE_URL or NEXT_PUBLIC_API_URL must be configured in Vercel environment variables. " +
        "Without this setting, /api/* rewrites cannot route to the deployed backend on Render."
      );
    }

    if (!rawBackend && isProduction) {
      console.warn("[Rewrites] Warning: API_BASE_URL / NEXT_PUBLIC_API_URL is not set in production.");
    }
    const backendUrl = (rawBackend || (isProduction ? "" : "http://localhost:8000")).replace(/\/$/, "");
    if (!backendUrl) {
      return [];
    }
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        ],
      },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
