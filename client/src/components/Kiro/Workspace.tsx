import { useEffect, useRef, useState } from 'react';
import { Bot, Send, SquareTerminal } from 'lucide-react';
import { Button, TextareaAutosize } from '@librechat/client';
import { useLocalize } from '~/hooks';

type KiroEvent =
  | { type: 'ready' }
  | { type: 'text'; id: string; text: string }
  | { type: 'tool_start'; id: string; name: string; arguments: unknown }
  | { type: 'tool_result'; id: string; name: string; result: string }
  | { type: 'done'; id: string }
  | { type: 'error'; error: string }
  | { type: 'stopped' };

type KiroMessage = {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'error';
  text: string;
};

function messageClassName(role: KiroMessage['role']): string {
  if (role === 'user') {
    return 'ml-auto max-w-[85%] rounded-xl bg-surface-secondary px-3 py-2 text-sm text-text-primary';
  }
  if (role === 'error') {
    return 'max-w-[85%] rounded-xl border border-border-destructive bg-surface-secondary px-3 py-2 text-sm text-text-destructive';
  }
  return 'max-w-[85%] whitespace-pre-wrap rounded-xl border border-border-light px-3 py-2 text-sm text-text-primary';
}

const isKiroEvent = (value: Record<string, unknown>): value is KiroEvent =>
  typeof value.type === 'string';

export default function KiroWorkspace() {
  const localize = useLocalize();
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<KiroMessage[]>([]);
  const [running, setRunning] = useState(false);
  const [available, setAvailable] = useState<boolean | null>(null);
  const activeRequestId = useRef<string | null>(null);

  useEffect(() => {
    if (!window.desktopBridge) {
      setAvailable(false);
      return;
    }
    window.desktopBridge
      .kiroStatus()
      .then(() => setAvailable(true))
      .catch((error: Error) => {
        setAvailable(false);
        setMessages([{ id: 'setup-error', role: 'error', text: error.message }]);
      });
    return window.desktopBridge.onKiroEvent((rawEvent) => {
      if (!isKiroEvent(rawEvent)) {
        return;
      }
      if ('id' in rawEvent && rawEvent.id !== activeRequestId.current) {
        return;
      }
      if (rawEvent.type === 'text') {
        setMessages((current) => [
          ...current.filter((message) => message.id !== `assistant-${rawEvent.id}`),
          { id: `assistant-${rawEvent.id}`, role: 'assistant', text: rawEvent.text },
        ]);
      } else if (rawEvent.type === 'tool_start') {
        setMessages((current) => [
          ...current,
          {
            id: `tool-start-${rawEvent.id}-${Date.now()}`,
            role: 'tool',
            text: `${localize('com_ui_kiro_running_tool')}: ${rawEvent.name}`,
          },
        ]);
      } else if (rawEvent.type === 'tool_result') {
        setMessages((current) => [
          ...current,
          {
            id: `tool-result-${rawEvent.id}-${Date.now()}`,
            role: 'tool',
            text: `${rawEvent.name}: ${rawEvent.result}`,
          },
        ]);
      } else if (rawEvent.type === 'done') {
        setRunning(false);
        activeRequestId.current = null;
      } else if (rawEvent.type === 'error') {
        setMessages((current) => [
          ...current,
          { id: `error-${Date.now()}`, role: 'error', text: rawEvent.error },
        ]);
        setRunning(false);
        activeRequestId.current = null;
      } else if (rawEvent.type === 'stopped') {
        setRunning(false);
      }
    });
  }, [localize]);

  const send = () => {
    const content = draft.trim();
    if (!content || running || !window.desktopBridge) {
      return;
    }
    const id = crypto.randomUUID();
    activeRequestId.current = id;
    setMessages((current) => [...current, { id, role: 'user', text: content }]);
    setDraft('');
    setRunning(true);
    window.desktopBridge.kiroSend({ id, content }).catch((error: Error) => {
      setMessages((current) => [
        ...current,
        { id: `error-${id}`, role: 'error', text: error.message },
      ]);
      setRunning(false);
      activeRequestId.current = null;
    });
  };

  if (available === false) {
    return (
      <main className="mx-auto flex h-full max-w-3xl items-center px-6">
        <p className="rounded-lg border border-border-medium bg-surface-secondary p-4 text-text-secondary">
          {localize('com_ui_kiro_desktop_only')}
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex h-full w-full max-w-4xl flex-col px-4 py-6 sm:px-6">
      <header className="mb-5 flex items-center gap-3">
        <div className="rounded-lg bg-surface-secondary p-2">
          <Bot className="size-6 text-text-primary" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-text-primary">{localize('com_ui_kiro')}</h1>
          <p className="text-sm text-text-secondary">
            {localize('com_ui_kiro_unrestricted_notice')}
          </p>
        </div>
      </header>
      <section className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto rounded-xl border border-border-light bg-surface-primary p-4">
        {messages.length === 0 && (
          <p className="text-sm text-text-secondary">{localize('com_ui_kiro_empty')}</p>
        )}
        {messages.map((message) => (
          <article key={message.id} className={messageClassName(message.role)}>
            {message.role === 'tool' && (
              <SquareTerminal className="mr-2 inline size-4" aria-hidden="true" />
            )}
            {message.text}
          </article>
        ))}
      </section>
      <div className="mt-4 flex gap-2">
        <TextareaAutosize
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
          disabled={running}
          aria-label={localize('com_ui_kiro_placeholder')}
          placeholder={localize('com_ui_kiro_placeholder')}
          className="min-h-12 flex-1"
        />
        <Button
          size="icon"
          aria-label={localize('com_ui_submit')}
          disabled={running || !draft.trim()}
          onClick={send}
        >
          <Send className="size-4" aria-hidden="true" />
        </Button>
      </div>
    </main>
  );
}
