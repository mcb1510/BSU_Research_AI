import { useEffect, useRef, useState } from 'react';
import { useAtomValue } from 'jotai';
import { CheckCircle2, XCircle } from 'lucide-react';
import { desktopOutputFolderAtom } from '~/store/desktopFolders';
import { useLocalize } from '~/hooks';
import cn from '~/utils/cn';

/** Exposed by the Electron desktop app's preload script (see
 *  bsu-research-ai-desktop/preload.js). Absent entirely in a regular
 *  browser tab — that's how this component tells the two apart. Every
 *  function here only works on a folder the researcher already picked via
 *  `pickFolder` this session (enforced in main.js, not trusted here). */
declare global {
  interface Window {
    desktopBridge?: {
      pickFolder: () => Promise<{ folderPath: string | null }>;
      writeFile: (
        folderPath: string,
        filename: string,
        content: string,
      ) => Promise<{ path: string }>;
      readFile: (folderPath: string, filename: string) => Promise<{ content: string }>;
      listFolder: (folderPath: string) => Promise<{ files: string[] }>;
    };
  }
}

interface ParsedWriteRequest {
  filename: string;
  content: string;
}

function parseWriteRequest(output: string | null | undefined): ParsedWriteRequest | null {
  if (!output) {
    return null;
  }
  try {
    const parsed = JSON.parse(output) as Record<string, unknown>;
    if (
      parsed.type === 'desktop_write_request' &&
      typeof parsed.filename === 'string' &&
      typeof parsed.content === 'string'
    ) {
      return { filename: parsed.filename, content: parsed.content };
    }
  } catch {
    // Not this tool's output shape — nothing to do.
  }
  return null;
}

type WriteStatus = 'pending' | 'success' | 'error' | 'unsupported';

export default function DesktopWriteResult({ output }: { output?: string | null }) {
  const localize = useLocalize();
  const request = parseWriteRequest(output);
  const outputFolder = useAtomValue(desktopOutputFolderAtom);
  const [status, setStatus] = useState<WriteStatus>('pending');
  const [errorMessage, setErrorMessage] = useState('');
  /** Guards against re-running the write on re-renders — this effect should
   *  fire exactly once per tool result, not once per render. */
  const attemptedRef = useRef(false);

  useEffect(() => {
    if (!request || attemptedRef.current) {
      return;
    }
    attemptedRef.current = true;

    if (typeof window === 'undefined' || !window.desktopBridge) {
      setStatus('unsupported');
      return;
    }

    if (!outputFolder) {
      setStatus('error');
      setErrorMessage(localize('com_ui_desktop_no_output_folder'));
      return;
    }

    window.desktopBridge
      .writeFile(outputFolder, request.filename, request.content)
      .then(() => setStatus('success'))
      .catch((error: Error) => {
        setStatus('error');
        setErrorMessage(error.message);
      });
    // `request` is derived fresh from `output` each render; only `output`
    // identity actually changing should re-trigger this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [output]);

  if (!request) {
    return null;
  }

  return (
    <div
      className={cn(
        'mt-2 flex items-center gap-2 rounded-lg border border-border-medium',
        'bg-surface-secondary px-3 py-2 text-sm',
      )}
    >
      {status === 'success' && (
        <>
          <CheckCircle2 className="text-text-success size-4 shrink-0" />
          <span>
            {localize('com_ui_desktop_write_success')}: {request.filename}
          </span>
        </>
      )}
      {status === 'error' && (
        <>
          <XCircle className="size-4 shrink-0 text-text-destructive" />
          <span>
            {localize('com_ui_desktop_write_error')}: {errorMessage}
          </span>
        </>
      )}
      {status === 'unsupported' && (
        <>
          <XCircle className="size-4 shrink-0 text-text-destructive" />
          <span>{localize('com_ui_desktop_write_unsupported')}</span>
        </>
      )}
      {status === 'pending' && <span className="text-text-secondary">{request.filename}…</span>}
    </div>
  );
}
