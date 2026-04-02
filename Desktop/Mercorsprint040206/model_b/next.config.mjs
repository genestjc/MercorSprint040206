/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  webpack: (config) => {
    // Silence optional pino-pretty resolution warning pulled in via WalletConnect.
    config.externals.push("pino-pretty");
    return config;
  },
};
export default nextConfig;
