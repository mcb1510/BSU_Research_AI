import { useAtom } from 'jotai';
import { FolderOpen } from 'lucide-react';
import { Button } from '@librechat/client';
import { desktopInputFolderAtom, desktopOutputFolderAtom } from '~/store/desktopFolders';
import { useChatFormContext } from '~/Providers';
import { useLocalize } from '~/hooks';
import cn from '~/utils/cn';

/** Only rendered for the "Test" agent (gated by its caller). Lets the
 *  researcher pick, via the Electron app's real OS folder dialog, which
 *  folder the agent reads its input document from and which folder it
 *  saves its output into — the only two folders the app can touch this
 *  session (see `authorizedFolders` in the desktop app's main.js). */
export default function DesktopFolderPicker() {
  const localize = useLocalize();
  const { setValue } = useChatFormContext();
  const [inputFolder, setInputFolder] = useAtom(desktopInputFolderAtom);
  const [outputFolder, setOutputFolder] = useAtom(desktopOutputFolderAtom);

  const supported = typeof window !== 'undefined' && window.desktopBridge != null;

  if (!supported) {
    return (
      <div className="mb-2 rounded-lg border border-border-medium bg-surface-secondary px-3 py-2 text-xs text-text-secondary">
        {localize('com_ui_desktop_folder_unsupported')}
      </div>
    );
  }

  const pickInputFolder = async () => {
    const { folderPath } = await window.desktopBridge!.pickFolder();
    if (!folderPath) {
      return;
    }
    setInputFolder(folderPath);

    const { files } = await window.desktopBridge!.listFolder(folderPath);
    const firstFile = files[0];
    if (!firstFile) {
      return;
    }
    const { content } = await window.desktopBridge!.readFile(folderPath, firstFile);
    setValue('text', content, { shouldValidate: true });
  };

  const pickOutputFolder = async () => {
    const { folderPath } = await window.desktopBridge!.pickFolder();
    if (folderPath) {
      setOutputFolder(folderPath);
    }
  };

  return (
    <div className={cn('mb-2 flex flex-wrap items-center gap-2 text-xs')}>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={pickInputFolder}
        className="h-7 gap-1.5 px-2.5"
      >
        <FolderOpen className="size-3.5" />
        {localize('com_ui_desktop_choose_input_folder')}
      </Button>
      <span className="max-w-[200px] truncate text-text-secondary" title={inputFolder ?? ''}>
        {inputFolder ?? localize('com_ui_desktop_no_folder_chosen')}
      </span>

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={pickOutputFolder}
        className="h-7 gap-1.5 px-2.5"
      >
        <FolderOpen className="size-3.5" />
        {localize('com_ui_desktop_choose_output_folder')}
      </Button>
      <span className="max-w-[200px] truncate text-text-secondary" title={outputFolder ?? ''}>
        {outputFolder ?? localize('com_ui_desktop_no_folder_chosen')}
      </span>
    </div>
  );
}
