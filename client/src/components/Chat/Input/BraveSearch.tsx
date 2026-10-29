import React, { memo, useCallback } from 'react';
import { Compass } from 'lucide-react';
import { CheckboxButton } from '@librechat/client';
import { isAgentsEndpoint, Permissions, PermissionTypes } from 'librechat-data-provider';
import { useBadgeRowContext, useChatContext } from '~/Providers';
import { useHasAccess, useLocalize } from '~/hooks';
import { badgeAccents } from './accents';

function BraveSearch() {
  const localize = useLocalize();
  const canUseWebSearch = useHasAccess({
    permissionType: PermissionTypes.WEB_SEARCH,
    permission: Permissions.USE,
  });
  const context = useBadgeRowContext();
  const { conversation } = useChatContext();
  const setBraveSearch = context?.braveSearch.setToggleState;
  const setWebSearch = context?.webSearch.setToggleState;
  const braveSearch = context?.braveSearch.toggleState === true;

  const toggle = useCallback(
    (value: boolean) => {
      setBraveSearch?.(value);
      if (value) {
        setWebSearch?.(false);
      }
    },
    [setBraveSearch, setWebSearch],
  );

  if (!canUseWebSearch || !context || isAgentsEndpoint(conversation?.endpoint)) {
    return null;
  }

  return (
    <CheckboxButton
      checked={braveSearch}
      setValue={({ value }) => toggle(Boolean(value))}
      label={localize('com_ui_brave_search')}
      isCheckedClassName={badgeAccents.blue}
      icon={<Compass className="icon-md" aria-hidden="true" />}
    />
  );
}

export default memo(BraveSearch);
