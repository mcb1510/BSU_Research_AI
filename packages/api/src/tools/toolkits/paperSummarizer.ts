import { z } from 'zod';
import * as fs from 'fs';
import { v4 } from 'uuid';
import * as path from 'path';
import { Types } from 'mongoose';
import { tool } from '@librechat/agents/langchain/tools';
import { FileSources, extractEnvVariable } from 'librechat-data-provider';
import type { DynamicStructuredTool } from '@librechat/agents/langchain/tools';
import type { IMongoFile } from '@librechat/data-schemas';
import type { AppConfig } from '@librechat/data-schemas';
import { getCustomEndpointConfig } from '~/app/config';

const paperSummarizerToolSchema: z.ZodObject<
  {
    paragraphs: z.ZodArray<z.ZodString>;
    filename: z.ZodOptional<z.ZodString>;
  },
  'strip'
> = z.object({
  paragraphs: z
    .array(z.string().trim().min(1))
    .min(1)
    .describe(
      'Every paragraph of the attached paper, in order, copied verbatim from the text you ' +
        'can already see in this conversation. One array entry per paragraph — do not merge ' +
        'multiple paragraphs into one entry or split a single paragraph across several.',
    ),
  filename: z
    .string()
    .trim()
    .min(1)
    .optional()
    .describe("The attached paper's filename, used to name the summary file. Omit if unknown."),
});

type PaperSummarizerInput = z.infer<typeof paperSummarizerToolSchema>;

interface PaperSummarizerDeps {
  appConfig: AppConfig;
  userId: string;
  /** Custom endpoint name whose credentials run the per-paragraph summary calls
   *  (the same model the researcher is already chatting with). */
  endpoint: string;
  model: string;
  createFile: (data: Partial<IMongoFile>, disableTTL?: boolean) => Promise<IMongoFile | null>;
}

async function summarizeParagraph(
  paragraph: string,
  credentials: { apiKey: string; baseURL: string; model: string },
): Promise<string> {
  const response = await fetch(`${credentials.baseURL.replace(/\/$/, '')}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${credentials.apiKey}`,
    },
    body: JSON.stringify({
      model: credentials.model,
      messages: [
        {
          role: 'system',
          content:
            'Summarize the following paragraph from a research paper in 1-3 concise ' +
            'sentences. Respond with only the summary, no preamble.',
        },
        { role: 'user', content: paragraph },
      ],
    }),
  });

  if (!response.ok) {
    throw new Error(
      `Summary request failed (${response.status}): ${await response.text().catch(() => '')}`,
    );
  }

  const data = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const content = data.choices?.[0]?.message?.content;
  if (!content) {
    throw new Error('Summary request returned no content.');
  }
  return content.trim();
}

async function summarizeParagraphs(
  paragraphs: string[],
  credentials: { apiKey: string; baseURL: string; model: string },
): Promise<string[]> {
  const summaries: string[] = [];
  /** Sequential, not concurrent: these share the same vLLM instance as every
   *  researcher's live chat traffic (bounded `max_num_seqs`), so fanning out
   *  one request per paragraph would compete with ordinary conversations. */
  for (const paragraph of paragraphs) {
    summaries.push(await summarizeParagraph(paragraph, credentials));
  }
  return summaries;
}

function buildMarkdown(sourceFilename: string, paragraphs: string[], summaries: string[]): string {
  const sections = paragraphs.map(
    (_paragraph, index) => `## Paragraph ${index + 1}\n\n${summaries[index]}`,
  );
  return `# Summary of ${sourceFilename}\n\n${sections.join('\n\n')}\n`;
}

/** Saves the generated markdown under the researcher's own uploads directory, matching
 *  the on-disk convention `saveLocalBuffer` uses (`/uploads/<userId>/<fileName>`), then
 *  records it as a real downloadable `File` document. */
async function saveSummaryFile(
  deps: PaperSummarizerDeps,
  markdown: string,
  sourceFilename: string,
): Promise<IMongoFile> {
  const { appConfig, userId, createFile } = deps;
  const uploadsDir = appConfig.paths?.uploads;
  if (!uploadsDir) {
    throw new Error('Uploads directory is not configured.');
  }

  const directory = path.resolve(uploadsDir, userId);
  await fs.promises.mkdir(directory, { recursive: true });

  const baseName = sourceFilename.replace(/\.[^.]+$/, '') || 'paper';
  const fileName = `${baseName}-summary-${v4()}.md`;
  const absolutePath = path.resolve(directory, fileName);
  const buffer = Buffer.from(markdown, 'utf8');
  await fs.promises.writeFile(absolutePath, buffer);

  const filepath = path.posix.join('/', 'uploads', userId, fileName);
  const file = await createFile(
    {
      user: new Types.ObjectId(userId),
      file_id: v4(),
      bytes: buffer.byteLength,
      filepath,
      filename: fileName,
      source: FileSources.local,
      type: 'text/markdown',
    },
    true,
  );
  if (!file) {
    throw new Error('Failed to create the summary file record.');
  }
  return file;
}

export const PAPER_SUMMARIZER_TOOL_DESCRIPTION: string =
  'Summarizes a research paper paragraph by paragraph and returns one downloadable Markdown ' +
  'file with every paragraph summary. Pass every paragraph of the paper, copied verbatim from ' +
  'the text already visible in this conversation — do not read or summarize the paper ' +
  'yourself, this tool does that.';

/** JSON-schema twin of {@link paperSummarizerToolSchema} for the schema-only tool registry
 *  (`agentToolDefinitions` in `tools/registry/definitions.ts`), same shape the DDGS web-search
 *  tool uses for the same reason — the registry needs a plain JSON schema, not a zod object. */
export interface PaperSummarizerToolDefinitionShape {
  name: string;
  description: string;
  schema: {
    type: 'object';
    properties: {
      paragraphs: { type: 'array'; items: { type: 'string' }; description: string };
      filename: { type: 'string'; description: string };
    };
    required: string[];
  };
}

export const PaperSummarizerToolDefinition: PaperSummarizerToolDefinitionShape = {
  name: 'paper_summarizer',
  description: PAPER_SUMMARIZER_TOOL_DESCRIPTION,
  schema: {
    type: 'object',
    properties: {
      paragraphs: {
        type: 'array',
        items: { type: 'string' },
        description:
          'Every paragraph of the attached paper, in order, copied verbatim from the text ' +
          'already visible in this conversation.',
      },
      filename: {
        type: 'string',
        description: "The attached paper's filename, used to name the summary file.",
      },
    },
    required: ['paragraphs'],
  },
};

export function createPaperSummarizerTool(
  deps: PaperSummarizerDeps,
): DynamicStructuredTool<typeof paperSummarizerToolSchema> {
  return tool(
    async (input: PaperSummarizerInput) => {
      const paragraphs = input.paragraphs;
      const sourceFilename = input.filename ?? 'paper.pdf';

      const endpointConfig = getCustomEndpointConfig({
        endpoint: deps.endpoint,
        appConfig: deps.appConfig,
      });
      // getCustomEndpointConfig() returns the config as stored — `${VAR}`
      // placeholders (e.g. baseURL: '${SSH_TUNNEL_BASE_URL}') are not resolved
      // automatically; extractEnvVariable() is the caller's responsibility.
      const apiKey = extractEnvVariable(endpointConfig?.apiKey ?? '');
      const baseURL = extractEnvVariable(endpointConfig?.baseURL ?? '');
      if (!apiKey || !baseURL) {
        throw new Error(`No credentials configured for endpoint "${deps.endpoint}".`);
      }

      const summaries = await summarizeParagraphs(paragraphs, {
        apiKey,
        baseURL,
        model: deps.model,
      });
      const markdown = buildMarkdown(sourceFilename, paragraphs, summaries);
      const summaryFile = await saveSummaryFile(deps, markdown, sourceFilename);

      return [
        `Summarized ${paragraphs.length} paragraphs from "${sourceFilename}" into ` +
          `"${summaryFile.filename}".`,
        { files: [summaryFile] },
      ] as [string, { files: IMongoFile[] }];
    },
    {
      name: PaperSummarizerToolDefinition.name,
      description: PAPER_SUMMARIZER_TOOL_DESCRIPTION,
      schema: paperSummarizerToolSchema,
      responseFormat: 'content_and_artifact',
    },
  );
}
