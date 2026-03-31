/** Muss mit Backend `ALLOWED_UI_HEADER_TIMEZONES` übereinstimmen. */
export const HEADER_TIMEZONE_IDS = [
  'UTC',
  'Europe/Berlin',
  'Europe/London',
  'Europe/Paris',
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'America/Sao_Paulo',
  'Asia/Dubai',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Australia/Sydney',
] as const

export type HeaderTimezoneId = (typeof HEADER_TIMEZONE_IDS)[number]
