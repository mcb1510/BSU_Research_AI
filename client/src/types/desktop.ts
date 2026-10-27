export {};

declare global {
  interface Window {
    desktopBridge?: {
      pickFolder: () => Promise<{ folderPath: string | null }>;
      writeFile: (
        folderPath: string,
        relativePath: string,
        content: string,
      ) => Promise<{ path: string }>;
      readFile: (folderPath: string, relativePath: string) => Promise<{ content: string }>;
      listFolder: (folderPath: string) => Promise<{ files: string[] }>;
      runCommand: (
        folderPath: string,
        executable: string,
        args?: string[],
      ) => Promise<{
        exitCode: number | null;
        signal: string | null;
        stdout: string;
        stderr: string;
        timedOut: boolean;
        outputTruncated: boolean;
      }>;
      kiroStatus: () => Promise<{ projectPath: string; running: boolean }>;
      kiroSend: (request: { id: string; content: string }) => Promise<{ accepted: boolean }>;
      stopKiro: () => Promise<{ stopped: boolean }>;
      onKiroEvent: (listener: (event: Record<string, unknown>) => void) => () => void;
    };
  }
}
