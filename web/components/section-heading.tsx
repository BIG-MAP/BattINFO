// Reusable section heading with an uppercase kicker, used across pages so the
// typographic rhythm stays consistent (schema.org / Materials Project style).

export function SectionHeading({
  id,
  kicker,
  title,
  className = "",
}: {
  id?: string;
  kicker: string;
  title: string;
  className?: string;
}) {
  return (
    <div id={id} className={`scroll-mt-24 ${className}`}>
      <h2 className="text-sm font-semibold uppercase tracking-wider text-brand-600">
        {kicker}
      </h2>
      <p className="mt-2 max-w-prose text-2xl font-semibold tracking-tight text-ink">
        {title}
      </p>
    </div>
  );
}
