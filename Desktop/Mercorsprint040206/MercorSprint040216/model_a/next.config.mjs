/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    remotePatterns: [{ protocol: "https", hostname: "image.mux.com" }],
  },
  webpack: (config) => {
    // WalletConnect's logger optionally requires pino-pretty (dev pretty-printer);
    // it isn't needed and the missing-module warning is noise.
    config.resolve.fallback = { ...config.resolve.fallback, "pino-pretty": false };
    return config;
  },
};
export default nextConfig;
