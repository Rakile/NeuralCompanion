export type PhoneDebugLevel = 'info' | 'warning' | 'error';

export type PhoneDebugEvent = {
  timestamp: string;
  level: PhoneDebugLevel;
  event: string;
  details: unknown;
};
