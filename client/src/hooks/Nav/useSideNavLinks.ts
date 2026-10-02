import { useMemo } from 'react';
import { MCPIcon, AttachmentIcon } from '@librechat/client';
import { Bot, Wrench, ScrollText, ArrowRightToLine, SlidersHorizontal } from 'lucide-react';
import {
  Permissions,
  EModelEndpoint,
  PermissionTypes,
  isParamEndpoint,
  isAgentsEndpoint,
} from 'librechat-data-provider';
import type { TInterfaceConfig, TEndpointsConfig } from 'librechat-data-provider';
import type { NavLink } from '~/common';
import {
  useAgentCapabilities,
  useMCPServerManager,
  useGetAgentsConfig,
  useHasAccess,
} from '~/hooks';
import MCPBuilderPanel from '~/components/SidePanel/MCPBuilder/MCPBuilderPanel';
import AgentPanelSwitch from '~/components/SidePanel/Agents/AgentPanelSwitch';
import Parameters from '~/components/SidePanel/Parameters/Panel';
import ToolsPanel from '~/components/SidePanel/Tools/Panel';
import FilesPanel from '~/components/SidePanel/Files/Panel';
import { SkillsAccordion } from '~/components/Skills';

export default function useSideNavLinks({
  hidePanel,
  keyProvided,
  endpoint,
  endpointType,
  interfaceConfig,
  endpointsConfig,
  includeHidePanel = true,
}: {
  hidePanel?: () => void;
  keyProvided: boolean;
  endpoint?: EModelEndpoint | null;
  endpointType?: EModelEndpoint | null;
  interfaceConfig: Partial<TInterfaceConfig>;
  endpointsConfig: TEndpointsConfig;
  includeHidePanel?: boolean;
}) {
  const hasAccessToSkills = useHasAccess({
    permissionType: PermissionTypes.SKILLS,
    permission: Permissions.USE,
  });
  const hasAccessToAgents = useHasAccess({
    permissionType: PermissionTypes.AGENTS,
    permission: Permissions.USE,
  });
  const hasAccessToCreateAgents = useHasAccess({
    permissionType: PermissionTypes.AGENTS,
    permission: Permissions.CREATE,
  });
  const hasAccessToUseMCPSettings = useHasAccess({
    permissionType: PermissionTypes.MCP_SERVERS,
    permission: Permissions.USE,
  });
  const hasAccessToCreateMCP = useHasAccess({
    permissionType: PermissionTypes.MCP_SERVERS,
    permission: Permissions.CREATE,
  });
  const { availableMCPServers } = useMCPServerManager();

  const { agentsConfig } = useGetAgentsConfig({ endpointsConfig });
  const { skillsEnabled } = useAgentCapabilities(agentsConfig?.capabilities);

  const sidePanelEntries = interfaceConfig.sidePanelEntries;

  const Links = useMemo(() => {
    const links: NavLink[] = [];

    if (sidePanelEntries?.tools !== false && hasAccessToAgents) {
      links.push({
        title: 'com_sidepanel_tools',
        label: '',
        icon: Bot,
        id: 'tools',
        Component: ToolsPanel,
      });
    }

    if (
      sidePanelEntries?.agentBuilder !== false &&
      endpointsConfig?.[EModelEndpoint.agents] &&
      hasAccessToAgents &&
      hasAccessToCreateAgents &&
      endpointsConfig[EModelEndpoint.agents].disableBuilder !== true
    ) {
      links.push({
        title: 'com_sidepanel_agent_builder',
        label: '',
        icon: Wrench,
        id: EModelEndpoint.agents,
        Component: AgentPanelSwitch,
      });
    }

    if (sidePanelEntries?.skills !== false && hasAccessToSkills && skillsEnabled) {
      links.push({
        title: 'com_ui_skills',
        label: '',
        icon: ScrollText,
        id: 'skills',
        Component: SkillsAccordion,
      });
    }

    if (sidePanelEntries?.files !== false) {
      links.push({
        title: 'com_sidepanel_attach_files',
        label: '',
        icon: AttachmentIcon,
        id: 'files',
        Component: FilesPanel,
      });
    }

    if (
      sidePanelEntries?.parameters !== false &&
      interfaceConfig.parameters === true &&
      isParamEndpoint(endpoint ?? '', endpointType ?? '') === true &&
      !isAgentsEndpoint(endpoint) &&
      keyProvided
    ) {
      links.push({
        title: 'com_sidepanel_parameters',
        label: '',
        icon: SlidersHorizontal,
        id: 'parameters',
        Component: Parameters,
      });
    }

    if (
      sidePanelEntries?.mcpServers !== false &&
      ((hasAccessToUseMCPSettings && availableMCPServers && availableMCPServers.length > 0) ||
        hasAccessToCreateMCP)
    ) {
      links.push({
        title: 'com_nav_setting_mcp',
        label: '',
        icon: MCPIcon,
        id: 'mcp-builder',
        Component: MCPBuilderPanel,
      });
    }

    if (includeHidePanel && hidePanel) {
      links.push({
        title: 'com_sidepanel_hide_panel',
        label: '',
        icon: ArrowRightToLine,
        onClick: hidePanel,
        id: 'hide-panel',
      });
    }

    return links;
  }, [
    endpoint,
    endpointsConfig,
    keyProvided,
    hasAccessToAgents,
    hasAccessToCreateAgents,
    hasAccessToSkills,
    skillsEnabled,
    interfaceConfig.parameters,
    endpointType,
    availableMCPServers,
    hasAccessToUseMCPSettings,
    hasAccessToCreateMCP,
    includeHidePanel,
    hidePanel,
    sidePanelEntries,
  ]);

  return Links;
}
