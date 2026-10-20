import { useMemo } from 'react';
import { FaviconImage, getCleanDomain } from '~/components/Web/SourceHovercard';
import { useLocalize } from '~/hooks';
import cn from '~/utils/cn';

interface ParsedSource {
  url: string;
  title: string;
}

interface SearchResultEntry {
  url?: unknown;
  title?: unknown;
}

/** Pulls every URL the `web_search` tool actually retrieved out of its raw
 *  JSON output, across all three action shapes it can return (`search`,
 *  `read`, `search_and_read`). Returns [] for anything that isn't this
 *  tool's output — safe to call unconditionally. */
function parseSources(output: string | null | undefined): ParsedSource[] {
  if (!output) {
    return [];
  }

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(output) as Record<string, unknown>;
  } catch {
    return [];
  }

  const entries: SearchResultEntry[] = [];

  if (parsed.type === 'webpage' && typeof parsed.url === 'string') {
    entries.push({ url: parsed.url, title: parsed.url });
  }

  if (Array.isArray(parsed.results)) {
    entries.push(...(parsed.results as SearchResultEntry[]));
  }

  if (parsed.selected != null && typeof parsed.selected === 'object') {
    entries.push(parsed.selected as SearchResultEntry);
  }

  const seen = new Set<string>();
  const sources: ParsedSource[] = [];
  for (const entry of entries) {
    if (typeof entry.url !== 'string' || !entry.url || seen.has(entry.url)) {
      continue;
    }
    seen.add(entry.url);
    sources.push({
      url: entry.url,
      title:
        typeof entry.title === 'string' && entry.title ? entry.title : getCleanDomain(entry.url),
    });
  }

  return sources;
}

export default function WebSearchSources({ output }: { output?: string | null }) {
  const localize = useLocalize();
  const sources = useMemo(() => parseSources(output), [output]);

  if (sources.length === 0) {
    return null;
  }

  return (
    <div className={cn('mt-2 flex flex-wrap items-center gap-1.5')}>
      <span className="text-xs text-text-secondary">{localize('com_ui_sources')}</span>
      {sources.map((source) => (
        <a
          key={source.url}
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          title={source.url}
          className={cn(
            'flex max-w-[220px] items-center gap-1.5 rounded-full border border-border-medium',
            'bg-surface-secondary px-2.5 py-1 text-xs text-text-primary no-underline',
            'transition-colors hover:bg-surface-tertiary',
          )}
        >
          <FaviconImage
            domain={getCleanDomain(source.url)}
            className="size-3 shrink-0 rounded-full"
          />
          <span className="truncate">{source.title}</span>
        </a>
      ))}
    </div>
  );
}
