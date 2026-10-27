import { CheckCircle2, Terminal, XCircle } from 'lucide-react';
import { useLocalize } from '~/hooks';

interface DesktopTerminalResultValue {
  exitCode: number | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  outputTruncated: boolean;
}

function parseTerminalResult(output: string | null | undefined): DesktopTerminalResultValue | null {
  if (!output) {
    return null;
  }
  try {
    const parsed = JSON.parse(output) as Partial<DesktopTerminalResultValue>;
    if (
      (typeof parsed.exitCode === 'number' || parsed.exitCode === null) &&
      typeof parsed.stdout === 'string' &&
      typeof parsed.stderr === 'string' &&
      typeof parsed.timedOut === 'boolean' &&
      typeof parsed.outputTruncated === 'boolean'
    ) {
      return parsed as DesktopTerminalResultValue;
    }
  } catch {
    // Not a completed desktop command result.
  }
  return null;
}

/** Displays a completed command only. Execution occurs in the paused-action card. */
export default function DesktopTerminalResult({ output }: { output?: string | null }) {
  const localize = useLocalize();
  const result = parseTerminalResult(output);
  if (!result) {
    return null;
  }

  const succeeded = result.exitCode === 0 && !result.timedOut;
  const text = [result.stdout, result.stderr].filter(Boolean).join('\n');
  return (
    <div className="mt-2 rounded-lg border border-border-medium bg-surface-secondary px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        {succeeded ? (
          <CheckCircle2 className="text-text-success size-4 shrink-0" />
        ) : (
          <XCircle className="size-4 shrink-0 text-text-destructive" />
        )}
        <Terminal className="size-4 shrink-0 text-text-secondary" />
        <span>
          {succeeded
            ? localize('com_ui_desktop_command_completed')
            : localize('com_ui_desktop_command_failed')}
        </span>
      </div>
      {text ? (
        <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words text-xs">
          {text}
        </pre>
      ) : (
        <p className="mt-2 text-text-secondary">{localize('com_ui_desktop_command_no_output')}</p>
      )}
      {result.outputTruncated && (
        <p className="mt-2 text-text-secondary">
          {localize('com_ui_desktop_command_output_shortened')}
        </p>
      )}
    </div>
  );
}
