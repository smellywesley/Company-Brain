import type { MetadataRoute } from "next";

/**
 * Web app manifest (served at /manifest.webmanifest). Next auto-injects the
 * <link rel="manifest"> from this file. Makes Company Brain installable as a
 * standalone PWA on Android/Chrome and iOS ("Add to Home Screen").
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Company Brain",
    short_name: "Company Brain",
    description:
      "Search your company's knowledge and get warned when it contradicts itself.",
    start_url: "/",
    display: "standalone",
    background_color: "#060708",
    theme_color: "#060708",
    icons: [
      { src: "/icon-512.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
