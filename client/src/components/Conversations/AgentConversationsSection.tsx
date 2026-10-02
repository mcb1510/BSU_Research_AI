import { memo, useMemo } from 'react';
import type { TConversation } from 'librechat-data-provider';
import { useActiveJobs } from '~/data-provider';
import { useLocalize } from '~/hooks';
import Convo from './Convo';

const noop = () => undefined;

function AgentConversationsSection({
  conversations,
  toggleNav,
}: {
  conversations: TConversation[];
  toggleNav: (afterSlide?: () => void) => void;
}) {
  const localize = useLocalize();
  const { data: activeJobsData } = useActiveJobs();
  const activeJobIds = useMemo(
    () => new Set(activeJobsData?.activeJobIds ?? []),
    [activeJobsData?.activeJobIds],
  );

  if (conversations.length === 0) {
    return null;
  }

  return (
    <div className="mb-2">
      <div className="px-3 py-1 text-xs font-medium text-text-secondary">
        {localize('com_sidepanel_tools')}
      </div>
      <ul className="flex flex-col gap-0.5 px-2">
        {conversations.map((conversation) => (
          <li key={conversation.conversationId}>
            <Convo
              conversation={conversation}
              retainView={noop}
              toggleNav={toggleNav}
              isGenerating={activeJobIds.has(conversation.conversationId ?? '')}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

export default memo(AgentConversationsSection);
