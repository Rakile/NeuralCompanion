export type CommandResult = { draft: string; ideas?: string[] };
export type SlashCommand = {
  name: string;
  description: string;
  usage?: string;
  disabledReason?: string;
  run?: (argument: string, signal: AbortSignal) => Promise<CommandResult | void>;
};

export function parseComposerText(text: string) {
  const value = text.trim();
  if (value.startsWith('//')) return { kind: 'chat' as const, text: value.slice(1) };
  if (!value.startsWith('/')) return { kind: 'chat' as const, text: value };
  const match = /^\/([^\s]*)(?:\s+([\s\S]*))?$/.exec(value);
  return { kind: 'command' as const, name: (match?.[1] || '').toLowerCase(), argument: match?.[2] || '' };
}

export function filterSlashCommands(text: string, commands: SlashCommand[]): SlashCommand[] {
  const parsed = parseComposerText(text);
  if (parsed.kind !== 'command') return [];
  const prefix = parsed.name === 'commands' ? '' : parsed.name;
  return commands.filter(command => command.name.startsWith(prefix));
}

export async function executeSlashCommand(text: string, commands: SlashCommand[], signal: AbortSignal) {
  const parsed = parseComposerText(text);
  if (parsed.kind !== 'command') throw new Error('Enter a slash command.');
  // These are reserved even if an old/misconfigured catalog advertises a handler.
  if (['roleplay', 'audiostory'].includes(parsed.name)) throw new Error(`/${parsed.name}: Coming later.`);
  const command = commands.find(item => item.name === parsed.name);
  if (!command) throw new Error('Unknown command. Type /commands to see the choices. Use // to send a literal slash.');
  if (command.disabledReason) throw new Error(command.disabledReason);
  if (signal.aborted) throw new Error('Command cancelled.');
  if (!command.run) throw new Error('This command is unavailable.');
  return command.run(parsed.argument, signal);
}

export function noCommandArguments(argument: string, usage: string) {
  if (argument) throw new Error(`Use ${usage} without extra text.`);
}

export function parseDraftResult(text: string, command: string): CommandResult {
  if (command === 'ideas') {
    try {
      const value: unknown = JSON.parse(text.replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, ''));
      if (Array.isArray(value) && value.every(item => typeof item === 'string')) {
        const ideas = value.filter(item => item.trim()).slice(0, 5);
        if (ideas.length) return { draft: '', ideas };
      }
    } catch { /* A provider can return plain text; keep it editable. */ }
  }
  return { draft: text };
}
