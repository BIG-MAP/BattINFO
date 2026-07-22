import type { MetadataRoute } from "next";
import { primaryNav, site } from "@/lib/site";

// Static routes: the home page plus every primary-nav destination. Update
// primaryNav (lib/site.ts) and new routes flow through automatically.
export default function sitemap(): MetadataRoute.Sitemap {
  // /federation is off the primary nav (folded into About) but still a real,
  // indexable page, keep it in the sitemap explicitly.
  const paths = ["/", ...primaryNav.map((n) => n.href), "/federation"];
  return paths.map((path) => ({
    url: new URL(path, site.url).toString(),
    changeFrequency: "weekly",
    priority: path === "/" ? 1 : 0.7,
  }));
}
