import { PrincipalType, ResourceType, PermissionBits } from 'librechat-data-provider';
import type { IAgent, IUser } from '@librechat/data-schemas';

export interface DefaultAgentDefinition {
  id: string;
  name: string;
  description?: string;
  instructions?: string;
  provider: string;
  model: string;
  tools?: string[];
}

/**
 * Agents kept in sync on every backend startup. Edit this list and restart
 * the backend to add, rename, or retool one — no script to run, no Agent
 * Builder click-through. Each one is created or updated here, then made
 * public, so it always matches this file.
 */
export const DEFAULT_AGENTS: DefaultAgentDefinition[] = [
  {
    id: 'agent_paper_summarizer',
    name: 'Paper Summarizer',
    description: 'Summarizes an uploaded research paper, one paragraph at a time.',
    instructions:
      'When the user uploads a PDF paper, use the paper_summarizer tool to summarize it. ' +
      'Otherwise, ask them to upload the paper first.',
    provider: 'Muse Glimmer',
    model: 'muse-glimmer',
    tools: ['paper_summarizer'],
  },
];

export interface SyncDefaultAgentsDeps {
  findUser: (criteria: Record<string, unknown>) => Promise<IUser | null>;
  getAgent: (criteria: Record<string, unknown>) => Promise<IAgent | null>;
  createAgent: (data: Record<string, unknown>) => Promise<IAgent>;
  updateAgent: (
    criteria: Record<string, unknown>,
    data: Record<string, unknown>,
    options?: Record<string, unknown>,
  ) => Promise<IAgent | null>;
  grantPermission: (
    principalType: string,
    principalId: unknown,
    resourceType: string,
    resourceId: unknown,
    permBits: number,
    grantedBy?: unknown,
  ) => Promise<unknown>;
  /** The account every default agent is authored by and granted from. */
  authorEmail: string;
  logger?: { info: (msg: string) => void; error: (msg: string, err?: unknown) => void };
}

/** Creates or updates every agent in {@link DEFAULT_AGENTS} and grants each one
 *  public view access, called once from `seedDatabase` on backend startup. */
export async function syncDefaultAgents(deps: SyncDefaultAgentsDeps): Promise<void> {
  const { findUser, getAgent, createAgent, updateAgent, grantPermission, authorEmail, logger } =
    deps;
  if (DEFAULT_AGENTS.length === 0) {
    return;
  }

  const author = await findUser({ email: authorEmail });
  if (!author) {
    logger?.error(`[syncDefaultAgents] No user found with email "${authorEmail}"; skipping.`);
    return;
  }
  const authorId = (author as unknown as { _id: unknown })._id;

  for (const definition of DEFAULT_AGENTS) {
    const { id, ...fields } = definition;
    try {
      const existing = await getAgent({ id });
      const agent = existing
        ? await updateAgent({ id }, fields, { updatingUserId: authorId })
        : await createAgent({ id, ...fields, author: authorId });

      if (!agent) {
        logger?.error(`[syncDefaultAgents] Failed to save agent "${definition.name}" (${id}).`);
        continue;
      }

      await grantPermission(
        PrincipalType.PUBLIC,
        null,
        ResourceType.AGENT,
        (agent as unknown as { _id: unknown })._id,
        PermissionBits.VIEW,
        authorId,
      );
      logger?.info(
        `[syncDefaultAgents] ${existing ? 'Updated' : 'Created'} "${definition.name}".`,
      );
    } catch (error) {
      logger?.error(`[syncDefaultAgents] Error syncing agent "${definition.name}":`, error);
    }
  }
}
