import React, { createContext, useContext, useState, useEffect } from 'react';
import { interpolate } from '../lib/interpolate';
import { SupportedLanguage, SUPPORTED_LANGUAGES, translations, LanguageInfo } from './translations';

interface LanguageContextType {
  currentLanguage: SupportedLanguage;
  langInfo: LanguageInfo;
  isRTL: boolean;
  setLanguage: (lang: SupportedLanguage) => void;
  t: (key: keyof typeof translations.en, params?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextType | null>(null);

const STORAGE_KEY = 'pulsar_lang';

/**
 * Intelligent Language Detector
 * Checks localStorage first, then inspects navigator.languages & navigator.language
 */
function detectInitialLanguage(): SupportedLanguage {
  if (typeof window === 'undefined') return 'en';

  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && saved in SUPPORTED_LANGUAGES) {
      return saved as SupportedLanguage;
    }
  } catch (e) {
    // ignore
  }

  // System & Browser Locale auto-detection
  const browserLangs = navigator.languages ? [...navigator.languages] : [navigator.language || 'en'];
  
  for (const raw of browserLangs) {
    const code = raw.toLowerCase().trim();
    if (code.startsWith('fa')) return 'fa';
    if (code.startsWith('ar')) return 'ar';
    if (code.startsWith('tr')) return 'tr';
    if (code.startsWith('zh')) return 'zh';
    if (code.startsWith('en')) return 'en';
  }

  return 'en';
}

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentLanguage, setCurrentLanguageState] = useState<SupportedLanguage>(() => detectInitialLanguage());

  const langInfo = SUPPORTED_LANGUAGES[currentLanguage] || SUPPORTED_LANGUAGES.en;
  const isRTL = langInfo.dir === 'rtl';

  useEffect(() => {
    // Apply HTML attributes dynamically
    document.documentElement.lang = currentLanguage;
    document.documentElement.dir = isRTL ? 'rtl' : 'ltr';

    if (isRTL) {
      document.documentElement.classList.add('rtl');
    } else {
      document.documentElement.classList.remove('rtl');
    }
  }, [currentLanguage, isRTL]);

  const setLanguage = (lang: SupportedLanguage) => {
    if (lang in SUPPORTED_LANGUAGES) {
      setCurrentLanguageState(lang);
      try {
        localStorage.setItem(STORAGE_KEY, lang);
      } catch (e) {
        // ignore
      }
    }
  };

  const t = (key: keyof typeof translations.en, params?: Record<string, string | number>): string => {
    const langDict = translations[currentLanguage] || translations.en;
    let text = (langDict as Record<string, string>)[key] || (translations.en as Record<string, string>)[key] || key;

    // Audit M43: the old inline version built a RegExp from the KEY and passed
    // the VALUE as a replacement string, so a key with a metacharacter broke the
    // pattern and a value containing `$&` was interpreted as a replacement.
    return interpolate(text, params);
  };

  return (
    <LanguageContext.Provider
      value={{
        currentLanguage,
        langInfo,
        isRTL,
        setLanguage,
        t,
      }}
    >
      {children}
    </LanguageContext.Provider>
  );
};

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
}
