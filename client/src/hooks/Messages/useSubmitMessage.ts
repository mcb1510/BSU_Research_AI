import { useCallback } from 'react';
import type { TMessage } from 'librechat-data-provider';
import { useChatContext, useChatFormContext, useAddedChatContext } from '~/Providers';
import { useGetLatestMessage } from '~/hooks/Messages/useLatestMessage';

export default function useSubmitMessage() {
  const methods = useChatFormContext();
  const { conversation: addedConvo } = useAddedChatContext();
  const { ask, index, getMessages, setMessages } = useChatContext();
  const getLatestMessage = useGetLatestMessage(index);

  const submitMessage = useCallback(
    (data?: {
      text: string;
      overrideFiles?: TMessage['files'];
      overrideQuotes?: string[];
      overrideManualSkills?: string[];
      overrideClientRequestId?: string;
      overrideRecoverySteerId?: string;
      overrideExpectedPredecessorCreatedAt?: number;
      overrideQueuedMessageOrigin?: unknown;
    }) => {
      if (!data) {
        return console.warn('No data provided to submitMessage');
      }
      const latestMessage = getLatestMessage();
      const rootMessages = getMessages();
      const isLatestInRootMessages = rootMessages?.some(
        (message) => message.messageId === latestMessage?.messageId,
      );
      if (!isLatestInRootMessages && latestMessage) {
        setMessages([...(rootMessages || []), latestMessage]);
      }

      const submitted = ask(
        {
          text: data.text,
          ...(data.overrideRecoverySteerId != null && {
            overrideUserMessageId: data.overrideRecoverySteerId,
          }),
        },
        {
          addedConvo: addedConvo ?? undefined,
          // Queued during-run messages carry their own consumed attachments,
          // quote chips, and manual skill picks (undefined = drain composer).
          overrideFiles: data.overrideFiles,
          overrideQuotes: data.overrideQuotes,
          overrideManualSkills: data.overrideManualSkills,
          overrideClientRequestId: data.overrideClientRequestId,
          overrideRecoverySteerId: data.overrideRecoverySteerId,
          overrideExpectedPredecessorCreatedAt: data.overrideExpectedPredecessorCreatedAt,
          overrideQueuedMessageOrigin: data.overrideQueuedMessageOrigin,
        },
      );
      if (submitted === false) {
        return false;
      }
      methods.reset();
    },
    [ask, methods, addedConvo, setMessages, getMessages, getLatestMessage],
  );

  return { submitMessage };
}
