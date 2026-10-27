import { useEffect, useRef, useState } from 'react';
import { useAtomValue } from 'jotai';
import { Terminal, XCircle } from 'lucide-react';
import type { Agents } from 'librechat-data-provider';
import { desktopInputFolderAtom, desktopOutputFolderAtom } from '~/store/desktopFolders';
import { useResumeSubmit } from './ApprovalContext';
import { useLocalize } from '~/hooks';

const MAX_RESULT_CHARS = 12_000;

interface DesktopCommand {
  workspace: 'input' | 'output';
  executable: string;
  args: string[];
}

interface DesktopQuestion extends Agents.AskUserQuestionRequest {
  desktop_command?: DesktopCommand;
}

export function getDesktopCommand(question: Agents.AskUserQuestionRequest): DesktopCommand | null {
  const command = (question as DesktopQuestion).desktop_command;
  if (
    command == null ||
    (command.workspace !== 'input' && command.workspace !== 'output') ||
    typeof command.executable !== 'string' ||
    !Array.isArray(command.args) ||
    !command.args.every((arg) => typeof arg === 'string')
  ) {
    return null;
  }
  return command;
}

function boundOutput(
  stdout: string,
  stderr: string,
): Pick<
  Awaited<ReturnType<NonNullable<Window['desktopBridge']>['runCommand']>>,
  'stdout' | 'stderr' | 'outputTruncated'
> {
  const combined = `${stdout}${stdout && stderr ? '\n' : ''}${stderr}`;
  if (combined.length <= MAX_RESULT_CHARS) {
    return { stdout, stderr, outputTruncated: false };
  }
  return {
    stdout: combined.slice(0, MAX_RESULT_CHARS),
    stderr: '',
    outputTruncated: true,
  };
}

/** Runs a paused desktop command exactly once, then resumes its tool call with the result. */
export default function DesktopTerminalExecution({
  actionId,
  command,
}: {
  actionId: string;
  command: DesktopCommand;
}) {
  const localize = useLocalize();
  const inputFolder = useAtomValue(desktopInputFolderAtom);
  const outputFolder = useAtomValue(desktopOutputFolderAtom);
  const { submitAskAnswer } = useResumeSubmit();
  const attempted = useRef(false);
  const [error, setError] = useState('');
  const commandText = [command.executable, ...command.args].join(' ');

  const run = () => {
    if (attempted.current) {
      return;
    }
    attempted.current = true;
    const folder = command.workspace === 'input' ? inputFolder : outputFolder;
    if (typeof window === 'undefined' || !window.desktopBridge) {
      submitAskAnswer(
        actionId,
        JSON.stringify({
          exitCode: null,
          signal: null,
          stdout: '',
          stderr: localize('com_ui_desktop_command_unsupported'),
          timedOut: false,
          outputTruncated: false,
        }),
      );
      return;
    }
    if (!folder) {
      submitAskAnswer(
        actionId,
        JSON.stringify({
          exitCode: null,
          signal: null,
          stdout: '',
          stderr: localize('com_ui_desktop_workspace_required'),
          timedOut: false,
          outputTruncated: false,
        }),
      );
      return;
    }
    window.desktopBridge
      .runCommand(folder, command.executable, command.args)
      .then((result) => {
        const bounded = boundOutput(result.stdout, result.stderr);
        submitAskAnswer(
          actionId,
          JSON.stringify({
            ...result,
            ...bounded,
            outputTruncated: result.outputTruncated || bounded.outputTruncated,
          }),
        );
      })
      .catch((runError: Error) => {
        setError(runError.message);
      });
  };

  useEffect(() => {
    run();
    // A paused command must be executed once, even if state updates re-render this card.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actionId]);

  return (
    <div className="my-2 rounded-lg border border-border-medium bg-surface-secondary px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        {error ? (
          <XCircle className="size-4 shrink-0 text-text-destructive" />
        ) : (
          <Terminal className="size-4 shrink-0 text-text-secondary" />
        )}
        <span className="font-mono text-xs">{commandText}</span>
      </div>
      {error ? (
        <p className="mt-2 text-text-destructive">{error}</p>
      ) : (
        <p className="mt-2 text-text-secondary">{localize('com_ui_desktop_command_running')}</p>
      )}
      {error && (
        <button
          type="button"
          className="mt-2 text-sm underline"
          onClick={() => {
            attempted.current = false;
            setError('');
            run();
          }}
        >
          {localize('com_ui_retry')}
        </button>
      )}
    </div>
  );
}
