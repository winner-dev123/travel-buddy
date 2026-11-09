import { Fragment, type ReactNode } from 'react';

/**
 * Deliberately tiny Markdown subset for editorial guide content: paragraphs, `- ` bullet lists,
 * **bold**, *italic* and [links](https://…). Produces React elements only — no HTML strings — so
 * content can never inject markup. Unsafe link schemes render as plain text.
 */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(\[([^\]]+)\]\(([^)\s]+)\))/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const key = `${keyPrefix}-${i++}`;
    if (match[2] !== undefined) out.push(<strong key={key}>{match[2]}</strong>);
    else if (match[4] !== undefined) out.push(<em key={key}>{match[4]}</em>);
    else if (match[6] !== undefined && match[7] !== undefined) {
      const href = match[7];
      if (/^https?:\/\//i.test(href) || href.startsWith('/')) {
        const external = !href.startsWith('/');
        out.push(
          <a key={key} href={href} className="text-primary underline underline-offset-2" {...(external ? { rel: 'noopener noreferrer nofollow', target: '_blank' } : {})}>
            {match[6]}
          </a>,
        );
      } else {
        out.push(match[6]);
      }
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source, className }: { source: string; className?: string }) {
  const blocks = source.replace(/\r\n/g, '\n').split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  return (
    <div className={className}>
      {blocks.map((block, bi) => {
        const lines = block.split('\n');
        if (lines.every((l) => /^[-*]\s+/.test(l))) {
          return (
            <ul key={bi} className="my-3 list-disc space-y-1.5 ps-5 marker:text-secondary">
              {lines.map((l, li) => (
                <li key={li}>{inline(l.replace(/^[-*]\s+/, ''), `${bi}-${li}`)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={bi}>
            {lines.map((l, li) => (
              <Fragment key={li}>
                {li > 0 ? <br /> : null}
                {inline(l, `${bi}-${li}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
