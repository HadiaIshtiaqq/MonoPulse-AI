/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  webpack: (config) => {
    // Konva (the design editor's canvas) mentions the Node "canvas" package for server-side
    // drawing; the editor only ever draws in the browser, so it's left out of the bundle.
    config.resolve.alias = { ...(config.resolve.alias || {}), canvas: false };
    return config;
  },
};

export default nextConfig;
