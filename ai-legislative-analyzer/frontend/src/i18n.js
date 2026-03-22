import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'
import hi from './locales/hi.json'
import te from './locales/te.json'
import ta from './locales/ta.json'

const resources = {
  en: { translation: en },
  hi: { translation: hi },
  te: { translation: te },
  ta: { translation: ta },
  kn: { translation: en },
  ml: { translation: en },
  bn: { translation: en },
  mr: { translation: en },
}

i18n.use(initReactI18next).init({
  resources,
  lng: 'en',
  fallbackLng: 'en',
  supportedLngs: ['en', 'hi', 'te', 'ta', 'kn', 'ml', 'bn', 'mr'],
  interpolation: {
    escapeValue: false,
  },
})

export default i18n
