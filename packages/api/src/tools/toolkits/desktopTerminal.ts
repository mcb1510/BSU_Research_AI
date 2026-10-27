import { z } from 'zod';
import { interrupt } from '@langchain/langgraph';
import { tool } from '@librechat/agents/langchain/tools';
import type { DynamicStructuredTool } from '@librechat/agents/langchain/tools';

const desktopTerminalToolSchema: z.ZodObject<
  {
    workspace: z.ZodEnum<['input', 'output']>;
    executable: z.ZodString;
    args: z.ZodOptional<z.ZodArray<z.ZodString>>;
  },
  'strip'
> = z.object({
  workspace: z
    .enum(['input', 'output'])
    .describe('The user-selected input or output workspace to run in.'),
  executable: z
    .string()
    .trim()
    .min(1)
    .describe('Executable to run directly, without a shell. Example: "python".'),
  args: z
    .array(z.string())
    .max(100)
    .optional()
    .describe('Arguments passed directly to the executable. Do not include shell syntax.'),
});

type DesktopTerminalInput = z.infer<typeof desktopTerminalToolSchema>;

/** Command request carried through the existing durable ask-user interrupt. */
export interface DesktopTerminalCommand {
  workspace: 'input' | 'output';
  executable: string;
  args: string[];
}

/** The Electron result becomes this tool's actual output after the run resumes. */
export interface DesktopTerminalResult {
  exitCode: number | null;
  signal: string | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  outputTruncated: boolean;
}

interface DesktopTerminalInterruptPayload {
  type: 'ask_user_question';
  question: {
    question: string;
    description: string;
    desktop_command: DesktopTerminalCommand;
  };
  tool_call_id?: string;
}

export const DESKTOP_TERMINAL_TOOL_DESCRIPTION: string =
  "Runs a command on the researcher's computer inside a user-selected workspace, using the BSU " +
  'Research AI desktop app. The desktop app performs the actual execution; this server never has ' +
  "direct access to the researcher's computer. Use an executable and arguments, never shell syntax. " +
  'The agent pauses until the desktop app returns the command result, then uses that result in its ' +
  'next step. On macOS, use "python3" for Python commands.';

export interface DesktopTerminalToolDefinitionShape {
  name: string;
  description: string;
  schema: {
    type: 'object';
    properties: {
      workspace: { type: 'string'; enum: string[]; description: string };
      executable: { type: 'string'; description: string };
      args: { type: 'array'; items: { type: 'string' }; maxItems: number; description: string };
    };
    required: string[];
  };
}

export const DesktopTerminalToolDefinition: DesktopTerminalToolDefinitionShape = {
  name: 'run_on_desktop',
  description: DESKTOP_TERMINAL_TOOL_DESCRIPTION,
  schema: {
    type: 'object',
    properties: {
      workspace: {
        type: 'string',
        enum: ['input', 'output'],
        description: 'The user-selected workspace to run in.',
      },
      executable: { type: 'string', description: 'Executable to run directly, without a shell.' },
      args: {
        type: 'array',
        items: { type: 'string' },
        maxItems: 100,
        description: 'Arguments passed directly to the executable.',
      },
    },
    required: ['workspace', 'executable'],
  },
};

/**
 * Pause the graph while Electron runs a structured process request. The standard
 * ask-user interrupt supplies a durable cross-device resume channel: on the
 * first pass `interrupt()` pauses; on the resume pass it returns the Electron
 * result, which is the ToolMessage the model actually receives.
 */
export function createDesktopTerminalTool(): DynamicStructuredTool<
  typeof desktopTerminalToolSchema
> {
  return tool(
    async (input: DesktopTerminalInput, config?: { toolCall?: { id?: string } }) => {
      const command: DesktopTerminalCommand = {
        workspace: input.workspace,
        executable: input.executable,
        args: input.args ?? [],
      };
      const resolution = interrupt<DesktopTerminalInterruptPayload, { answer: string }>({
        type: 'ask_user_question',
        question: {
          question: 'Running a command on your desktop…',
          description: 'BSU Research AI will continue when the command finishes.',
          desktop_command: command,
        },
        ...(config?.toolCall?.id != null && config.toolCall.id !== ''
          ? { tool_call_id: config.toolCall.id }
          : {}),
      });
      return resolution.answer;
    },
    {
      name: DesktopTerminalToolDefinition.name,
      description: DESKTOP_TERMINAL_TOOL_DESCRIPTION,
      schema: desktopTerminalToolSchema,
    },
  );
}
