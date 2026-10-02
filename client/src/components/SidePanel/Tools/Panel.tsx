import { memo, useState } from 'react';
import { Spinner } from '@librechat/client';
import { PermissionBits } from 'librechat-data-provider';
import type { Agent } from 'librechat-data-provider';
import { useListAgentsQuery } from '~/data-provider';
import AgentDetailDialog from './AgentDetailDialog';
import { renderAgentAvatar } from '~/utils/agents';
import { useLocalize } from '~/hooks';

function ToolsPanel() {
  const localize = useLocalize();
  /** The default params require EDIT permission (Agent Builder's "agents I can
   *  edit" view) — this panel needs VIEW, since researchers can use an agent
   *  that's shared with them without being able to edit it. */
  const { data, isLoading } = useListAgentsQuery({ requiredPermission: PermissionBits.VIEW });
  const agents = data?.data ?? [];
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  return (
    <div className="h-full overflow-y-auto p-2">
      <h2 className="mb-2 px-2 text-sm font-medium text-text-primary">
        {localize('com_sidepanel_tools')}
      </h2>
      {isLoading && (
        <div className="flex justify-center p-4">
          <Spinner />
        </div>
      )}
      {!isLoading && agents.length === 0 && (
        <p className="px-2 text-sm text-text-secondary">{localize('com_ui_tools_empty')}</p>
      )}
      <ul className="flex flex-col gap-1">
        {agents.map((agent) => (
          <li key={agent.id}>
            <button
              type="button"
              onClick={() => setSelectedAgent(agent)}
              className="flex w-full items-center gap-3 rounded-lg p-2 text-left hover:bg-surface-hover"
            >
              {renderAgentAvatar(agent, { size: 'icon', showBorder: false })}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-text-primary">
                  {agent.name || localize('com_ui_untitled')}
                </div>
                {agent.description && (
                  <div className="truncate text-xs text-text-secondary">{agent.description}</div>
                )}
              </div>
            </button>
          </li>
        ))}
      </ul>
      <AgentDetailDialog
        agent={selectedAgent}
        onOpenChange={(open) => !open && setSelectedAgent(null)}
      />
    </div>
  );
}

export default memo(ToolsPanel);
