import { site } from "@/lib/site";

/**
 * Trust markers under the hero: live badges (CI, PyPI, they update themselves,
 * so they can never go stale) plus the claims that need no counter: license,
 * pinned ontology versions, and the projects funding the work. A DOI badge
 * appears automatically once `site.doi` is set at the 0.8 archive step.
 */
export function ProofStrip() {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 text-xs text-ink-faint">
      <a href={site.ciRuns} target="_blank" rel="noreferrer" className="inline-flex">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={site.ciBadge} alt="CI status" className="h-5" />
      </a>
      {site.pypiLive ? (
        <a href={site.pypi} target="_blank" rel="noreferrer" className="inline-flex">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={site.pypiBadge} alt="Latest release on PyPI" className="h-5" />
        </a>
      ) : null}
      {site.doi ? (
        <a href={`https://doi.org/${site.doi}`} target="_blank" rel="noreferrer" className="inline-flex">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`https://img.shields.io/badge/DOI-${encodeURIComponent(site.doi)}-1682D4`}
            alt={`DOI ${site.doi}`}
            className="h-5"
          />
        </a>
      ) : null}
      <span className="font-medium">{site.license}</span>
      <span>EMMO domain-battery {site.versions.domainBattery}</span>
      <span>Developed in the EU projects BIG-MAP &amp; DigiBatt</span>
    </div>
  );
}
