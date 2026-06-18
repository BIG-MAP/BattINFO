/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The site is a pure presentation layer scoped to web/. It must not reach
  // outside this directory at build or runtime — keep it self-contained so the
  // monorepo stays split-able.
};

export default nextConfig;
