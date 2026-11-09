/**
 * The contract has no post title. Public story pages derive one from the first sentence of the
 * author's own text (never invented), trimmed for titles and metadata.
 */
export function storyTitle(body: string, max = 72): string {
  const firstLine = body.trim().split(/\n/)[0] ?? '';
  const sentence = /^(.+?[.!?。！？])(\s|$)/u.exec(firstLine)?.[1] ?? firstLine;
  if (sentence.length <= max) return sentence.replace(/[.。]$/u, '');
  const cut = sentence.slice(0, max);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

export function excerpt(body: string, max = 160): string {
  const flat = body.replace(/\s+/g, ' ').trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
