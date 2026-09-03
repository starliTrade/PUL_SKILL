import React, { useState, useRef, useEffect } from 'react';
import { useLanguage } from '../i18n/LanguageContext';
import { SUPPORTED_LANGUAGES, SupportedLanguage } from '../i18n/translations';
import { Globe, Check, ChevronDown } from 'lucide-react';
import { cn } from '../lib/utils';
import { sounds } from '../lib/sound';

interface LanguageSelectorProps {
  className?: string;
}

export const LanguageSelector: React.FC<LanguageSelectorProps> = ({
  className,
}) => {
  const { currentLanguage, langInfo, setLanguage } = useLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const handleSelect = (code: SupportedLanguage) => {
    sounds.playClick();
    setLanguage(code);
    setIsOpen(false);
  };

  return (
    <div
      className={cn('relative inline-flex items-center justify-center text-left h-8 shrink-0', className)}
      ref={dropdownRef}
      dir="ltr"
      style={{ direction: 'ltr' }}
    >
      {/* Trigger Button: 2 shades darker, 2 sizes smaller, standard centered on navbar x-axis */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          sounds.playClick();
          setIsOpen(!isOpen);
        }}
        type="button"
        className={cn(
          'inline-flex items-center justify-center gap-1 px-1.5 h-5 min-h-[20px] max-h-[20px] rounded transition-all duration-200 cursor-pointer select-none leading-none shrink-0 self-center',
          'bg-black/90 hover:bg-black border border-white/[0.06] hover:border-white/[0.14]',
          'shadow-[0_2px_6px_rgba(0,0,0,0.5)] text-zinc-300 hover:text-white group/lang focus:outline-none',
          isOpen && 'border-sky-500/40 ring-1 ring-sky-500/20 bg-black text-white'
        )}
        aria-label="Select Language"
        title={`Language: ${langInfo.nativeName} (${langInfo.name})`}
      >
        <span className="text-[11px] leading-none select-none inline-flex items-center justify-center shrink-0">
          {langInfo.flag}
        </span>
        <ChevronDown
          className={cn(
            'w-2 h-2 text-zinc-400 opacity-60 group-hover/lang:opacity-100 group-hover/lang:text-zinc-200 transition-all shrink-0',
            isOpen && 'rotate-180 opacity-100 text-sky-400'
          )}
        />
      </button>

      {/* Popover Dropdown Menu */}
      {isOpen && (
        <div
          onClick={(e) => e.stopPropagation()}
          className={cn(
            'absolute left-0 top-full mt-1.5 w-36 rounded-xl py-1 z-[100] overflow-hidden',
            'bg-zinc-950/95 backdrop-blur-2xl border border-white/[0.1] shadow-[0_16px_40px_rgba(0,0,0,0.9),0_0_0_1px_rgba(255,255,255,0.06)]',
            'animate-in fade-in zoom-in-95 duration-150 origin-top-left'
          )}
        >
          <div className="flex flex-col gap-0.5 px-1 py-0.5">
            {Object.values(SUPPORTED_LANGUAGES).map((item) => {
              const isSelected = item.code === currentLanguage;
              return (
                <button
                  key={item.code}
                  onClick={() => handleSelect(item.code)}
                  className={cn(
                    'w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-colors cursor-pointer text-left',
                    isSelected
                      ? 'bg-sky-500/15 text-sky-300 font-semibold border border-sky-500/30'
                      : 'text-zinc-300 hover:text-white hover:bg-white/[0.05]'
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-base leading-none select-none">{item.flag}</span>
                    <span className="font-medium text-xs tracking-tight">{item.nativeName}</span>
                  </div>
                  {isSelected && <Check className="w-3.5 h-3.5 text-sky-400 shrink-0" />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
