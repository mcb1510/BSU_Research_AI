import { Bot } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button, Spinner } from '@librechat/client';
import { PermissionBits } from 'librechat-data-provider';
import type { ReactNode } from 'react';
import { useListAgentsQuery } from '~/data-provider';
import { useLocalize } from '~/hooks';

export default function Agents() {
  const localize = useLocalize();
  const navigate = useNavigate();
  const { data, isLoading } = useListAgentsQuery({ requiredPermission: PermissionBits.VIEW });
  const agents = data?.data ?? [];
  const hasDesktopAgent = typeof window !== 'undefined' && window.desktopBridge != null;
  let agentContent: ReactNode;
  if (isLoading) {
    agentContent = (
      <div className="flex flex-1 items-center justify-center" aria-live="polite" role="status">
        <Spinner className="text-text-primary" />
      </div>
    );
  } else if (agents.length === 0) {
    agentContent = (
      <p className="rounded-xl border border-border-light bg-surface-primary p-4 text-sm text-text-secondary">
        {localize('com_agents_empty_state_heading')}
      </p>
    );
  } else {
    agentContent = (
      <section className="grid gap-3 sm:grid-cols-2" aria-label={localize('com_agents_all')}>
        {agents.map((agent) => (
          <Button
            key={agent.id}
            variant="outline"
            className="h-auto min-h-24 justify-start rounded-xl border-border-light bg-surface-primary p-4 text-left"
            onClick={() => navigate(`/c/new?agent_id=${encodeURIComponent(agent.id)}`)}
          >
            <span className="min-w-0">
              <span className="block truncate font-medium text-text-primary">
                {agent.name || agent.id}
              </span>
              {agent.description && (
                <span className="mt-1 block whitespace-normal text-sm font-normal text-text-secondary">
                  {agent.description}
                </span>
              )}
            </span>
          </Button>
        ))}
      </section>
    );
  }

  return (
    <main className="mx-auto flex h-full w-full max-w-5xl flex-col overflow-y-auto px-4 py-6 sm:px-6">
      <header className="mb-5">
        <h1 className="text-xl font-semibold text-text-primary">{localize('com_agents_all')}</h1>
        <p className="mt-1 text-sm text-text-secondary">
          {localize('com_agents_marketplace_subtitle')}
        </p>
      </header>
      {hasDesktopAgent && (
        <Button
          variant="outline"
          className="mb-4 h-auto w-full justify-start rounded-xl border-border-light bg-surface-primary p-4 text-left"
          onClick={() => navigate('/agents/kiro')}
        >
          <Bot className="mr-3 size-5 shrink-0 text-text-primary" aria-hidden="true" />
          <span className="min-w-0">
            <span className="block font-medium text-text-primary">{localize('com_ui_kiro')}</span>
            <span className="mt-1 block whitespace-normal text-sm font-normal text-text-secondary">
              {localize('com_ui_kiro_unrestricted_notice')}
            </span>
          </span>
        </Button>
      )}
      {agentContent}
    </main>
  );
}
