import { z } from 'zod';
import * as fs from 'fs';
import { v4 } from 'uuid';
import * as path from 'path';
import { Types } from 'mongoose';
import { FileSources } from 'librechat-data-provider';
import { tool } from '@librechat/agents/langchain/tools';
import type { DynamicStructuredTool } from '@librechat/agents/langchain/tools';
import type { IMongoFile } from '@librechat/data-schemas';
import type { AppConfig } from '@librechat/data-schemas';
import { getCustomEndpointConfig } from '~/app/config';

const paperSummarizerToolSchema: z.ZodObject<{ fileId: z.ZodOptional<z.ZodString> }, 'strip'> =
  z.object({
    fileId: z
      .string()
      .trim()
      .min(1)
      .optional()
      .describe(
        'ID of the uploaded paper to summarize. Omit to use the single attached file when ' +
          'exactly one was uploaded this turn.',
      ),
  });

type PaperSummarizerInput = z.infer<typeof paperSummarizerToolSchema>;

/** Minimal shape this tool needs from an attached file, regardless of caller's file type. */
interface AttachedFile {
  file_id: string;
  filepath: string;
  filename: string;
  type: string;
  user: string;
}

interface PaperSummarizerDeps {
  appConfig: AppConfig;
  userId: string;
  files: AttachedFile[];
  /** Custom endpoint name whose credentials run the per-paragraph summary calls
   *  (the same model the researcher is already chatting with). */
  endpoint: string;
  model: string;
  createFile: (data: Partial<IMongoFile>, disableTTL?: boolean) => Promise<IMongoFile | null>;
}

const MIN_PARAGRAPH_LENGTH = 40;

function selectTargetFile(files: AttachedFile[], fileId?: string): AttachedFile {
  if (fileId) {
    const match = files.find((file) => file.file_id === fileId);
    if (!match) {
      throw new Error(`No attached file found with id "${fileId}".`);
    }
    return match;
  }
  if (files.length === 1) {
    return files[0];
  }
  if (files.length === 0) {
    throw new Error('No file is attached to this turn. Upload a paper first.');
  }
  throw new Error(
    `Multiple files are attached (${files
      .map((file) => `"${file.filename}" (${file.file_id})`)
      .join(', ')}); specify "fileId" to pick one.`,
  );
}

/** Resolves a stored `/uploads/<userId>/<name>` filepath to its absolute path on disk,
 *  rejecting traversal outside the configured uploads directory. */
function resolveUploadPath(appConfig: AppConfig, filepath: string): string {
  const marker = '/uploads/';
  const index = filepath.indexOf(marker);
  if (index === -1) {
    throw new Error(`Unsupported file location for local summarization: "${filepath}".`);
  }
  const relative = filepath.slice(index + marker.length);
  const uploadsDir = appConfig.paths?.uploads;
  if (!uploadsDir) {
    throw new Error('Uploads directory is not configured.');
  }
  const resolved = path.resolve(uploadsDir, relative);
  const rel = path.relative(path.resolve(uploadsDir), resolved);
  if (rel.startsWith('..') || path.isAbsolute(rel)) {
    throw new Error(`Invalid file path: "${filepath}".`);
  }
  return resolved;
}

/** Extracts page text from a local PDF, mirroring the extraction used for document uploads
 *  (`files/documents/crud.ts`), inlined here since that helper expects a Multer file. */
async function extractPdfText(absolutePath: string): Promise<string> {
  const { getDocument } = await import('pdfjs-dist/legacy/build/pdf.mjs');
  const data = new Uint8Array(await fs.promises.readFile(absolutePath));
  const pdf = await getDocument({ data }).promise;

  let fullText = '';
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const textContent = await page.getTextContent();
    const pageText = textContent.items
      .map((item) => ('str' in item ? item.str : ''))
      .join(' ');
    fullText += `${pageText}\n`;
  }
  return fullText;
}

/** Splits extracted text into paragraphs on blank lines, dropping fragments too short
 *  to be a real paragraph (running headers, page numbers, stray line breaks). */
function splitIntoParagraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.replace(/\s+/g, ' ').trim())
    .filter((paragraph) => paragraph.length >= MIN_PARAGRAPH_LENGTH);
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
  'Reads an uploaded PDF research paper, summarizes it paragraph by paragraph, and returns ' +
  'one downloadable Markdown file with every paragraph summary.';

/** JSON-schema twin of {@link paperSummarizerToolSchema} for the schema-only tool registry
 *  (`agentToolDefinitions` in `tools/registry/definitions.ts`), same shape the DDGS web-search
 *  tool uses for the same reason — the registry needs a plain JSON schema, not a zod object. */
export interface PaperSummarizerToolDefinitionShape {
  name: string;
  description: string;
  schema: {
    type: 'object';
    properties: {
      fileId: { type: 'string'; description: string };
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
      fileId: {
        type: 'string',
        description:
          'ID of the uploaded paper to summarize. Omit to use the single attached file ' +
          'when exactly one was uploaded this turn.',
      },
    },
    required: [],
  },
};

export function createPaperSummarizerTool(
  deps: PaperSummarizerDeps,
): DynamicStructuredTool<typeof paperSummarizerToolSchema> {
  return tool(
    async (input: PaperSummarizerInput) => {
      const sourceFile = selectTargetFile(deps.files, input.fileId);
      if (sourceFile.type !== 'application/pdf') {
        throw new Error(
          `"${sourceFile.filename}" is a ${sourceFile.type}; only PDF papers are supported.`,
        );
      }

      const absolutePath = resolveUploadPath(deps.appConfig, sourceFile.filepath);
      const text = await extractPdfText(absolutePath);
      const paragraphs = splitIntoParagraphs(text);
      if (paragraphs.length === 0) {
        throw new Error(`No readable paragraphs were found in "${sourceFile.filename}".`);
      }

      const endpointConfig = getCustomEndpointConfig({
        endpoint: deps.endpoint,
        appConfig: deps.appConfig,
      });
      if (!endpointConfig?.apiKey || !endpointConfig.baseURL) {
        throw new Error(`No credentials configured for endpoint "${deps.endpoint}".`);
      }

      const summaries = await summarizeParagraphs(paragraphs, {
        apiKey: endpointConfig.apiKey,
        baseURL: endpointConfig.baseURL,
        model: deps.model,
      });
      const markdown = buildMarkdown(sourceFile.filename, paragraphs, summaries);
      const summaryFile = await saveSummaryFile(deps, markdown, sourceFile.filename);

      return [
        `Summarized ${paragraphs.length} paragraphs from "${sourceFile.filename}" into ` +
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
