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
      'When the user uploads a PDF paper, you must and can only use the paper_summarizer tool to summarize it. ' +
      'Pass every paragraph of the paper as a separate entry in the paragraphs array, copied ' +
      'verbatim from the text you can see — do not read, describe, or summarize the paper ' +
      'yourself. You must include EVERY paragraph, with no exceptions, no matter how long the ' +
      "paper is. Do not select a 'representative sample' or a subset of 'key' paragraphs — " +
      'omitting any paragraph is not acceptable, regardless of length or effort. Do not ' +
      'overthink this or reason about whether it is practical — just follow this instruction ' +
      'exactly as written. Otherwise, ask them to upload the paper first.',
    provider: 'Muse Glimmer',
    model: 'muse-glimmer',
    tools: ['paper_summarizer'],
  },
  {
    id: 'agent_test',
    name: 'Test',
    description: 'Writes a short story to a folder you choose. Only works in the desktop app.',
    instructions:
      'Write a short story about lions. Once you have written it, use the write_to_desktop ' +
      'tool with a short filename ending in .md and the story as content. This only works ' +
      'inside the BSU Research AI desktop app, where the user has chosen an output folder — ' +
      'if the user is in a web browser instead, tell them so plainly.',
    provider: 'Nemotron (DGX Spark)',
    model: 'nemotron-3.5-bolt',
    tools: ['write_to_desktop'],
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
      logger?.info(`[syncDefaultAgents] ${existing ? 'Updated' : 'Created'} "${definition.name}".`);
    } catch (error) {
      logger?.error(`[syncDefaultAgents] Error syncing agent "${definition.name}":`, error);
    }
  }
}
