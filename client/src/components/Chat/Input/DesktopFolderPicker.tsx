import { useAtom } from 'jotai';
import { FolderOpen } from 'lucide-react';
import { Button } from '@librechat/client';
import { desktopInputFolderAtom, desktopOutputFolderAtom } from '~/store/desktopFolders';
import { useLocalize } from '~/hooks';
import cn from '~/utils/cn';

/** Lets the researcher grant the active agent an input and output workspace
 *  through Electron's native folder dialog. The desktop app can access only
 *  folders granted this way during the current session. */
export default function DesktopFolderPicker() {
  const localize = useLocalize();
  const [inputFolder, setInputFolder] = useAtom(desktopInputFolderAtom);
  const [outputFolder, setOutputFolder] = useAtom(desktopOutputFolderAtom);

  const pickInputFolder = async () => {
    const { folderPath } = await window.desktopBridge!.pickFolder();
    if (!folderPath) {
      return;
    }
    setInputFolder(folderPath);
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
