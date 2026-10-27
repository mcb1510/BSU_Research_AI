import { DesktopTerminalToolDefinition } from './desktopTerminal';

describe('desktop terminal tool', () => {
  test('explains that command output is returned to the agent after the desktop resumes it', () => {
    expect(DesktopTerminalToolDefinition.description).toMatch(
      /pauses until the desktop app returns/i,
    );
  });

  test('publishes the input workspace and direct-process arguments', () => {
    expect(DesktopTerminalToolDefinition).toMatchObject({
      name: 'run_on_desktop',
      schema: {
        required: ['workspace', 'executable'],
        properties: {
          workspace: { enum: ['input', 'output'] },
          args: { maxItems: 100 },
        },
      },
    });
  });
});
