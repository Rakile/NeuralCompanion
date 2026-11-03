import type { StoryPlanDraft } from '../api/types';

export function storyPlanToChatPrompt(plan: StoryPlanDraft): string {
  const beats = plan.beats.map((beat, index) => `${index + 1}. ${beat.title}: ${beat.summary}`).join('\n');
  return `Write a long, progressive story called ${plan.title}.\n\n${plan.premise}\n\n` +
    `Constraints: ${plan.constraints}\n\nPlanned beats:\n${beats}\n\n` +
    (plan.pace ? `Story pace: ${plan.pace}. Develop each beat over roughly ${{slow:'5–8',medium:'3–4',fast:'1–2'}[plan.pace]} replies.\n\n` : '') +
    `Begin with: ${plan.opening_cue}\n\nDevelop one scene at a time. Do not complete the entire outline in one reply.`;
}
