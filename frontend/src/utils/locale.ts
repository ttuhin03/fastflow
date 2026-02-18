/**
 * Date/number formatting using current i18n language.
 */

import i18n from '../i18n'

export function getFormatLocale(): string {
  const lang = i18n.language?.split('-')[0] || 'de'
  return lang === 'de' ? 'de-DE' : 'en-US'
}
