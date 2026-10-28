import { useMemo, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Spinner } from '@librechat/client';
import { EModelEndpoint } from 'librechat-data-provider';
import AgentConversationsSection from '~/components/Conversations/AgentConversationsSection';
import { useConversationsInfiniteQuery } from '~/data-provider';
import { useAuthContext, useLocalize } from '~/hooks';

const noop = () => undefined;

export default function AgentsSection() {
  const localize = useLocalize();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuthContext();
  const { data, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useConversationsInfiniteQuery(
      { sortBy: 'updatedAt', sortDirection: 'desc' },
      { enabled: isAuthenticated },
    );
  const conversations = useMemo(
    () =>
      data?.pages
        .flatMap((page) => page.conversations)
        .filter((conversation) => conversation.endpoint === EModelEndpoint.agents) ?? [],
    [data],
  );
  let historyContent: ReactNode;
  if (isLoading) {
    historyContent = (
      <div className="flex flex-1 items-center justify-center" aria-live="polite" role="status">
        <Spinner className="text-text-primary" />
      </div>
    );
  } else if (conversations.length === 0) {
    historyContent = (
      <p className="px-2 text-sm text-text-secondary">
        {localize('com_agents_empty_state_heading')}
      </p>
    );
  } else {
    historyContent = (
      <AgentConversationsSection
        conversations={conversations}
        toggleNav={noop}
        heading="com_ui_chat_history"
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto px-2 pb-3 pt-2">
      <Button
        variant="outline"
        className="mb-3 w-full justify-start"
        onClick={() => navigate('/agents')}
      >
        {localize('com_agents_all')}
      </Button>
      {historyContent}
      {hasNextPage && (
        <Button
          variant="ghost"
          className="mt-2 w-full"
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
        >
          {isFetchingNextPage ? <Spinner className="size-4" /> : localize('com_ui_load_more')}
        </Button>
      )}
    </div>
  );
}
