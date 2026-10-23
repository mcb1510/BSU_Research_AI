import { z } from 'zod';
import { tool } from '@librechat/agents/langchain/tools';
import type { DynamicStructuredTool } from '@librechat/agents/langchain/tools';

const desktopWriteToolSchema: z.ZodObject<
  {
    filename: z.ZodString;
    content: z.ZodString;
  },
  'strip'
> = z.object({
  filename: z
    .string()
    .trim()
    .min(1)
    .describe('A plain file name (no path), e.g. "notes.txt". It will be written to the Desktop.'),
  content: z.string().describe('The complete text content to write to the file.'),
});

type DesktopWriteInput = z.infer<typeof desktopWriteToolSchema>;

export const DESKTOP_WRITE_TOOL_DESCRIPTION: string =
  "Writes a text file to the researcher's own Desktop, in the BSU Research AI desktop app. " +
  'This tool does NOT write the file itself — it only packages the filename and content; the ' +
  "desktop app on the researcher's own computer performs the actual write. Only usable when " +
  'running inside the desktop app, not in a web browser.';

export interface DesktopWriteToolDefinitionShape {
  name: string;
  description: string;
  schema: {
    type: 'object';
    properties: {
      filename: { type: 'string'; description: string };
      content: { type: 'string'; description: string };
    };
    required: string[];
  };
}

export const DesktopWriteToolDefinition: DesktopWriteToolDefinitionShape = {
  name: 'write_to_desktop',
  description: DESKTOP_WRITE_TOOL_DESCRIPTION,
  schema: {
    type: 'object',
    properties: {
      filename: {
        type: 'string',
        description: 'A plain file name (no path), e.g. "notes.txt".',
      },
      content: {
        type: 'string',
        description: 'The complete text content to write to the file.',
      },
    },
    required: ['filename', 'content'],
  },
};

/** This tool is a pure pass-through: the backend has no access to the
 *  researcher's own computer, so it can't write anything itself. It just
 *  returns {filename, content} as its output — the chat frontend (running
 *  inside the desktop app) watches for this tool's result and performs the
 *  actual write via Electron's `window.desktopBridge`, which is the only
 *  thing with real filesystem access here. */
export function createDesktopWriteTool(): DynamicStructuredTool<typeof desktopWriteToolSchema> {
  return tool(
    async (input: DesktopWriteInput) => {
      return JSON.stringify({
        type: 'desktop_write_request',
        filename: input.filename,
        content: input.content,
      });
    },
    {
      name: DesktopWriteToolDefinition.name,
      description: DESKTOP_WRITE_TOOL_DESCRIPTION,
      schema: desktopWriteToolSchema,
    },
  );
}
