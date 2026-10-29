/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Each build's own id, baked into its pages: an open tab compares it with the running server's
  // (/build-id) and offers a reload when MonoPlus has been updated underneath it.
  env: { NEXT_PUBLIC_BUILD_ID: String(Date.now()) },
  // The web app passes /api and /media on to the backend, so everything is one address: a link to the
  // web app (a tunnel or a host) works from any device. The backend still sees where a request came from.
  async rewrites() {
    const api = (process.env.MONOPLUS_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/media/:path*", destination: `${api}/media/:path*` },
      { source: "/mcp", destination: `${api}/mcp` },
    ];
  },
  // Long calls (a script from Nemotron, a large video upload) pass through without being cut off.
  experimental: { proxyTimeout: 300_000 },
  webpack: (config) => {
    // Konva (the design editor's canvas) mentions the Node "canvas" package for server-side
    // drawing; the editor only ever draws in the browser, so it's left out of the bundle.
    config.resolve.alias = { ...(config.resolve.alias || {}), canvas: false };
    return config;
  },
};

export default nextConfig;
