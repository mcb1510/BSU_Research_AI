import { atom } from 'jotai';

/** Not persisted to localStorage on purpose: the Electron main process only
 *  authorizes a folder for the lifetime of the picker interaction that
 *  selected it (see `authorizedFolders` in main.js) — restoring a path from
 *  a previous session wouldn't actually be writable again without a fresh
 *  pick, so there's nothing useful to persist. */
export const desktopInputFolderAtom = atom<string | null>(null);
export const desktopOutputFolderAtom = atom<string | null>(null);
