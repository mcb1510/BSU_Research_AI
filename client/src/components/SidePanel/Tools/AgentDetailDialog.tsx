import { memo } from 'react';
import {
  Button,
  OGDialog,
  OGDialogContent,
  OGDialogTitle,
  OGDialogDescription,
} from '@librechat/client';
import type { Agent } from 'librechat-data-provider';
import { renderAgentAvatar } from '~/utils/agents';
import { useLocalize } from '~/hooks';

function AgentDetailDialog({
  agent,
  onOpenChange,
}: {
  agent: Agent | null;
  onOpenChange: (open: boolean) => void;
}) {
  const localize = useLocalize();

  return (
    <OGDialog open={agent != null} onOpenChange={onOpenChange}>
      <OGDialogContent className="w-11/12 max-w-md">
        {agent && (
          <>
            <div className="flex flex-col items-center gap-3 text-center">
              {renderAgentAvatar(agent, { size: 'lg' })}
              <OGDialogTitle>{agent.name || localize('com_ui_untitled')}</OGDialogTitle>
              <OGDialogDescription>
                {agent.description || localize('com_ui_tools_no_description')}
              </OGDialogDescription>
            </div>
            <Button
              className="mt-4 w-full"
              onClick={() => {
                /** A client-side route change to the same `/c/new` path won't
                 *  re-run the one-time "apply URL settings" logic that reads
                 *  `agent_id` — that logic is built for a fresh page load, so
                 *  this forces one instead of using router navigation. */
                window.location.href = `/c/new?agent_id=${agent.id}`;
              }}
            >
              {localize('com_ui_select')}
            </Button>
          </>
        )}
      </OGDialogContent>
    </OGDialog>
  );
}

export default memo(AgentDetailDialog);
