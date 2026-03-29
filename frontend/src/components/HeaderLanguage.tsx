import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import './HeaderTime.css'

const STORAGE_KEY_VARIANT = 'headerLangVariant'
type Variant = 'default' | 'dual'

function loadVariant(): Variant {
  try {
    const v = localStorage.getItem(STORAGE_KEY_VARIANT)
    if (v === 'default' || v === 'dual') return v
  } catch {
    /* localStorage unzugreifbar (z. B. privater Modus) */
  }
  return 'default'
}

export default function HeaderLanguage() {
  const { t } = useTranslation()
  const [variant, setVariant] = useState<Variant>(() => loadVariant())

  const isDe = i18n.language?.startsWith('de')

  const cycleVariant = useCallback(() => {
    const next: Variant = variant === 'default' ? 'dual' : 'default'
    setVariant(next)
    try {
      localStorage.setItem(STORAGE_KEY_VARIANT, next)
    } catch {
      /* z. B. privater Modus, Speicher voll */
    }
  }, [variant])

  const toggleLang = useCallback(() => {
    i18n.changeLanguage(isDe ? 'en' : 'de')
  }, [isDe])

  return (
    <div className="header-time-container" role="group" aria-label={t('nav.languageSwitcher')}>
      {variant === 'default' ? (
        <>
          <div className="header-time-content">
            <span className="header-time-clock">
              {isDe ? t('language.nativeDe') : t('language.nativeEn')}
            </span>
          </div>
          <button
            type="button"
            className={`header-time-toggle ${isDe ? 'utc' : 'cet'}`}
            onClick={toggleLang}
            title={t('headerLanguage.toggle')}
          >
            {isDe ? t('language.de') : t('language.en')}
          </button>
        </>
      ) : (
        <div className="header-time-dual">
          <button
            type="button"
            className={`header-lang-dual-btn ${isDe ? 'ht-dual-utc' : 'ht-dual-cet'}`}
            onClick={() => i18n.changeLanguage('de')}
            title={t('headerLanguage.selectDe')}
          >
            {t('language.nativeDe')}
          </button>
          <span className="ht-dual-sep">·</span>
          <button
            type="button"
            className={`header-lang-dual-btn ${!isDe ? 'ht-dual-utc' : 'ht-dual-cet'}`}
            onClick={() => i18n.changeLanguage('en')}
            title={t('headerLanguage.selectEn')}
          >
            {t('language.nativeEn')}
          </button>
        </div>
      )}
      <button
        type="button"
        className="header-time-cycle"
        onClick={cycleVariant}
        title={variant === 'default' ? t('headerLanguage.showDual') : t('headerLanguage.showStandard')}
        aria-label={t('headerLanguage.switchDisplay')}
      >
        ◐
      </button>
    </div>
  )
}
