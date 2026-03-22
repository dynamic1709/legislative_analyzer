import { apiUrl } from './api'

const INDIAN_LANGUAGES = {
  en: 'English',
  as: 'Assamese',
  bn: 'Bengali',
  brx: 'Bodo',
  doi: 'Dogri',
  gu: 'Gujarati',
  hi: 'Hindi',
  kn: 'Kannada',
  ks: 'Kashmiri',
  kok: 'Konkani',
  mai: 'Maithili',
  ml: 'Malayalam',
  mni: 'Manipuri',
  mr: 'Marathi',
  ne: 'Nepali',
  or: 'Odia',
  pa: 'Punjabi',
  sa: 'Sanskrit',
  sat: 'Santali',
  sd: 'Sindhi',
  ta: 'Tamil',
  te: 'Telugu',
  ur: 'Urdu',
}

class TranslationService {
  constructor() {
    this.cache = {}
  }

  async translate(text, targetLanguage) {
    // If target is English, return as is
    if (targetLanguage === 'en') {
      return text
    }

    // Create cache key
    const cacheKey = `${text}:${targetLanguage}`
    if (this.cache[cacheKey]) {
      return this.cache[cacheKey]
    }

    try {
      // Send translation request to backend
      const response = await fetch(apiUrl('/translate'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text,
          target_language: targetLanguage,
          source_language: 'en',
        }),
      })

      if (!response.ok) {
        console.error('Translation failed:', response.statusText)
        return text // Fallback to original text
      }

      const data = await response.json()
      const translatedText = data.translated_text || text

      // Cache the result
      this.cache[cacheKey] = translatedText

      return translatedText
    } catch (error) {
      console.error('Translation service error:', error)
      return text // Fallback to original text
    }
  }

  async translateObject(obj, targetLanguage) {
    if (targetLanguage === 'en') {
      return obj
    }

    const translated = {}

    for (const [key, value] of Object.entries(obj)) {
      if (typeof value === 'string') {
        translated[key] = await this.translate(value, targetLanguage)
      } else if (Array.isArray(value)) {
        translated[key] = await Promise.all(
          value.map((item) =>
            typeof item === 'string' ? this.translate(item, targetLanguage) : item
          )
        )
      } else {
        translated[key] = value
      }
    }

    return translated
  }

  getLanguageName(code) {
    return INDIAN_LANGUAGES[code] || 'Unknown'
  }

  getSupportedLanguages() {
    return Object.entries(INDIAN_LANGUAGES).map(([code, name]) => ({
      code,
      name,
    }))
  }
}

export default new TranslationService()
export { INDIAN_LANGUAGES }
