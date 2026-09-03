import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Search,
  UserPlus,
  UserCheck,
  Swords,
  X,
  Zap,
  Shield,
  Sparkles,
  ExternalLink,
  Users,
  Copy,
  Check,
  Clock,
  Trophy,
} from 'lucide-react';
import { realWeb3Manager, FriendProfile, SEED_PLAYERS } from '../lib/realWeb3';
import { sounds } from '../lib/sound';
import { usePulsarStore } from '../store/usePulsarStore';
import { cn } from '../lib/utils';
import { PulsarDynamicAvatar } from './PulsarDynamicAvatar';
import { useLanguage } from '../i18n/LanguageContext';

interface FriendChallengeModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedStake: number;
  onStartDuel: (opponentName: string, stake: number) => void;
}

export const FriendChallengeModal: React.FC<FriendChallengeModalProps> = ({
  isOpen,
  onClose,
  selectedStake,
  onStartDuel,
}) => {
  const { t } = useLanguage();
  const { wallet, stats } = usePulsarStore();
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'search' | 'saved'>('search');
  const [searchResults, setSearchResults] = useState<FriendProfile[]>([]);
  const [savedFriends, setSavedFriends] = useState<FriendProfile[]>([]);
  const [savedAddresses, setSavedAddresses] = useState<string[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [copiedAddr, setCopiedAddr] = useState<string | null>(null);

  const [toastMsg, setToastMsg] = useState<{ text: string; type: 'info' | 'success' | 'warn' } | null>(null);

  // Load saved friends on open
  useEffect(() => {
    if (isOpen) {
      if (wallet.connected && wallet.address) {
        const friends = realWeb3Manager.getSavedFriendsList(wallet.address);
        setSavedFriends(friends);
        setSavedAddresses(friends.map((f) => f.address.toLowerCase()));
      } else {
        setSavedFriends([]);
        setSavedAddresses([]);
      }
      // Pre-populate search with seed accounts for instant user feedback
      setSearchResults(SEED_PLAYERS);
      setToastMsg(null);
    }
  }, [isOpen, wallet.connected, wallet.address]);

  // Toast timer
  useEffect(() => {
    if (toastMsg) {
      const timer = setTimeout(() => setToastMsg(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toastMsg]);

  // Handle Search Input with debounce
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(SEED_PLAYERS);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    const timer = setTimeout(async () => {
      const res = await realWeb3Manager.searchPlayers(searchQuery);
      setSearchResults(res);
      setIsSearching(false);
    }, 200);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  const handleToggleSaveFriend = async (player: FriendProfile) => {
    if (!wallet.connected || !wallet.address) {
      sounds.playError();
      setToastMsg({
        text: t('connectWalletToSaveFriends'),
        type: 'warn',
      });
      return;
    }

    sounds.playClick();
    const isNowSaved = await realWeb3Manager.toggleFriend(wallet.address, player);
    const cleanAddr = player.address.toLowerCase();

    if (isNowSaved) {
      setSavedAddresses((prev) => [...prev, cleanAddr]);
      setSavedFriends((prev) => [...prev, player]);
      setToastMsg({
        text: `✓ ${player.playerId || player.shortAddress}`,
        type: 'success',
      });
    } else {
      setSavedAddresses((prev) => prev.filter((a) => a !== cleanAddr));
      setSavedFriends((prev) => prev.filter((f) => f.address.toLowerCase() !== cleanAddr));
      setToastMsg({
        text: `${player.playerId || player.shortAddress}`,
        type: 'info',
      });
    }
  };

  const handleChallenge = (player: FriendProfile) => {
    sounds.playGo();
    onClose();
    onStartDuel(player.playerId || player.shortAddress, selectedStake);
  };

  const handleCopy = (address: string) => {
    navigator.clipboard.writeText(address);
    setCopiedAddr(address);
    sounds.playClick();
    setTimeout(() => setCopiedAddr(null), 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[999999] flex items-center justify-center p-3 sm:p-4">
      {/* Backdrop */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 bg-black/80 backdrop-blur-md"
      />

      {/* Modal Box */}
      <motion.div
        initial={{ scale: 0.95, opacity: 0, y: 10 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.95, opacity: 0, y: 10 }}
        className="relative z-10 w-full max-w-md linear-card-elevated p-4 sm:p-5 border border-white/[0.08] shadow-[0_16px_50px_rgba(0,0,0,0.9)] max-h-[90vh] flex flex-col"
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500/20 to-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400">
              <Users className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white tracking-tight">{t('friendModalTitle')}</h3>
              <p className="text-[10px] text-zinc-400">{t('friendModalSub')}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800/80 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="grid grid-cols-2 gap-1 p-1 bg-zinc-900/80 rounded-xl border border-white/[0.04] my-2 text-xs">
          <button
            onClick={() => {
              sounds.playClick();
              setActiveTab('search');
            }}
            className={cn(
              'py-1.5 rounded-lg font-medium transition-all cursor-pointer flex items-center justify-center gap-1.5',
              activeTab === 'search'
                ? 'bg-white text-black font-semibold shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200'
            )}
          >
            <Search className="w-3.5 h-3.5" />
            <span>{t('searchPlayers')}</span>
          </button>
          <button
            onClick={() => {
              sounds.playClick();
              setActiveTab('saved');
            }}
            className={cn(
              'py-1.5 rounded-lg font-medium transition-all cursor-pointer flex items-center justify-center gap-1.5',
              activeTab === 'saved'
                ? 'bg-white text-black font-semibold shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200'
            )}
          >
            <UserCheck className="w-3.5 h-3.5" />
            <span>{t('savedFriends', { count: savedFriends.length })}</span>
          </button>
        </div>

        {/* User's own Player ID bar */}
        {wallet.connected && wallet.playerId ? (
          <div className="mb-2 px-3 py-1.5 rounded-lg bg-sky-500/10 border border-sky-500/20 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-[10px] text-sky-400 font-medium">{t('yourPlayerId')}</span>
              <span className="font-bold text-white tracking-tight truncate font-mono text-[11px]">
                {wallet.playerId}
              </span>
            </div>
            <button
              onClick={() => handleCopy(wallet.playerId || '')}
              className="text-[10px] text-sky-300 hover:text-white flex items-center gap-1 bg-sky-500/20 hover:bg-sky-500/30 px-2 py-0.5 rounded cursor-pointer transition-colors"
            >
              {copiedAddr === wallet.playerId ? (
                <>
                  <Check className="w-3 h-3 text-emerald-400" />
                  <span className="text-emerald-400 font-medium">{t('copied')}</span>
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3" />
                  <span>{t('copyId')}</span>
                </>
              )}
            </button>
          </div>
        ) : (
          <div className="mb-2 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center gap-2 text-[11px] text-amber-300">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
            <span>{t('connectWalletToSaveFriends')}</span>
          </div>
        )}

        {/* Dynamic Toast Message Banner */}
        <AnimatePresence>
          {toastMsg && (
            <motion.div
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className={cn(
                'mb-2 px-3 py-1.5 rounded-lg text-xs flex items-center justify-between border font-medium',
                toastMsg.type === 'warn' && 'bg-rose-500/15 border-rose-500/30 text-rose-300',
                toastMsg.type === 'success' && 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300',
                toastMsg.type === 'info' && 'bg-sky-500/15 border-sky-500/30 text-sky-300'
              )}
            >
              <span>{toastMsg.text}</span>
              <button
                onClick={() => setToastMsg(null)}
                className="p-0.5 text-zinc-400 hover:text-white ml-2 cursor-pointer"
              >
                <X className="w-3 h-3" />
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Search Tab Content */}
        {activeTab === 'search' && (
          <div className="space-y-3 flex-1 flex flex-col min-h-0 overflow-hidden">
            {/* Input Box */}
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('searchPlaceholder')}
                className="w-full bg-zinc-900/90 border border-white/[0.08] focus:border-sky-500/50 focus:ring-1 focus:ring-sky-500/50 rounded-xl py-2.5 px-9 text-xs text-white placeholder-zinc-500 transition-all outline-none"
              />
              <Search className="w-4 h-4 text-zinc-500 absolute left-3 top-3" />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 top-2.5 text-zinc-500 hover:text-zinc-300"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Quick Demo Test Pills */}
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className="text-zinc-500 text-[10px]">{t('testTargets')}</span>
              {SEED_PLAYERS.map((seed) => (
                <button
                  key={seed.address}
                  onClick={() => {
                    sounds.playClick();
                    setSearchQuery(seed.playerId);
                  }}
                  className="px-2 py-0.5 rounded-md bg-zinc-900/80 hover:bg-zinc-800 border border-white/[0.04] hover:border-white/[0.1] text-zinc-300 font-mono text-[10px] transition-all cursor-pointer"
                >
                  {seed.playerId}
                </button>
              ))}
            </div>

            {/* Results List */}
            <div className="flex-1 overflow-y-auto space-y-2 pr-1 min-h-[160px] no-scrollbar">
              {searchResults.length === 0 ? (
                <div className="p-6 text-center text-xs text-zinc-500 space-y-1">
                  <Search className="w-6 h-6 mx-auto text-zinc-600 mb-1" />
                  <p className="text-zinc-300 font-medium">No player found</p>
                </div>
              ) : (
                searchResults.map((player) => {
                  const isSaved = savedAddresses.includes(player.address.toLowerCase());
                  return (
                    <div
                      key={player.address}
                      className="linear-card p-3 border border-white/[0.05] hover:border-white/[0.12] transition-all space-y-2 bg-zinc-900/40"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <PulsarDynamicAvatar level={player.level} size="sm" showBadge={false} />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs font-bold text-white tracking-tight truncate">
                                {player.playerId}
                              </span>
                              <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                                {t('levelLabel')} {player.level}
                              </span>
                            </div>
                            <div className="flex items-center gap-1 text-[10px] text-zinc-400 font-mono">
                              <span>{player.shortAddress}</span>
                              <button
                                onClick={() => handleCopy(player.address)}
                                className="hover:text-white"
                                title={t('copyAddress')}
                              >
                                {copiedAddr === player.address ? (
                                  <Check className="w-3 h-3 text-emerald-400" />
                                ) : (
                                  <Copy className="w-3 h-3 text-zinc-500" />
                                )}
                              </button>
                            </div>
                          </div>
                        </div>

                        {/* Save Friend Button */}
                        <button
                          onClick={() => handleToggleSaveFriend(player)}
                          className={cn(
                            'px-2.5 py-1 rounded-lg border text-xs transition-all cursor-pointer flex items-center gap-1.5 active:scale-95 group',
                            isSaved
                              ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300 hover:bg-rose-500/15 hover:border-rose-500/30 hover:text-rose-300'
                              : 'bg-zinc-800/80 border-white/[0.08] text-zinc-300 hover:text-white hover:bg-zinc-700/80 hover:border-sky-500/30'
                          )}
                        >
                          {isSaved ? (
                            <>
                              <UserCheck className="w-3.5 h-3.5 text-emerald-400 group-hover:hidden" />
                              <X className="w-3.5 h-3.5 text-rose-400 hidden group-hover:inline" />
                              <span className="text-[10px] font-semibold group-hover:hidden">{t('saved')}</span>
                              <span className="text-[10px] font-semibold hidden group-hover:inline">✕</span>
                            </>
                          ) : (
                            <>
                              <UserPlus className="w-3.5 h-3.5 text-sky-400" />
                              <span className="text-[10px] font-semibold">{t('saveFriend')}</span>
                            </>
                          )}
                        </button>
                      </div>

                      {/* Stat Metrics Grid */}
                      <div className="grid grid-cols-3 gap-1.5 py-1 px-2 rounded-lg bg-black/40 border border-white/[0.03] text-[10px] font-mono">
                        <div>
                          <span className="text-zinc-500">{t('bestSpeed')}: </span>
                          <span className="text-emerald-400 font-bold">
                            {player.bestReactionMs > 0 ? `${player.bestReactionMs}ms` : '—'}
                          </span>
                        </div>
                        <div>
                          <span className="text-zinc-500">{t('winRate')}: </span>
                          <span className="text-zinc-200 font-bold">{player.winRate}%</span>
                        </div>
                        <div>
                          <span className="text-zinc-500">{t('totalMatches')}: </span>
                          <span className="text-zinc-200">{player.totalMatches}</span>
                        </div>
                      </div>

                      {/* Duel Action Button */}
                      <button
                        onClick={() => handleChallenge(player)}
                        className="w-full bg-white hover:bg-zinc-200 text-black font-semibold text-xs py-2 rounded-lg transition-all flex items-center justify-center gap-1.5 cursor-pointer shadow-sm active:scale-98"
                      >
                        <Swords className="w-3.5 h-3.5 fill-black" />
                        <span>{t('challengeRival')} ({selectedStake} USDT)</span>
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* Saved Friends Tab Content */}
        {activeTab === 'saved' && (
          <div className="space-y-3 flex-1 flex flex-col min-h-0 overflow-hidden">
            {savedFriends.length === 0 ? (
              <div className="p-8 text-center text-xs text-zinc-500 space-y-2 my-auto">
                <Users className="w-8 h-8 mx-auto text-zinc-600" />
                <p className="text-zinc-300 font-medium">{t('savedFriends', { count: 0 })}</p>
                <p className="text-[11px] text-zinc-500 max-w-xs mx-auto">
                  {t('searchPlaceholder')}
                </p>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto space-y-2 pr-1 no-scrollbar">
                {savedFriends.map((friend) => (
                  <div
                    key={friend.address}
                    className="linear-card p-3 border border-white/[0.05] space-y-2 bg-zinc-900/40"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <PulsarDynamicAvatar level={friend.level} size="sm" showBadge={false} />
                        <div>
                          <div className="text-xs font-bold text-white">{friend.playerId}</div>
                          <div className="text-[10px] text-zinc-400 font-mono">{friend.shortAddress}</div>
                        </div>
                      </div>

                      <button
                        onClick={() => handleToggleSaveFriend(friend)}
                        className="text-zinc-500 hover:text-rose-400 text-[10px] p-1 transition-colors cursor-pointer"
                        title="Remove Friend"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    <div className="flex items-center justify-between text-[10px] font-mono text-zinc-400 px-2 py-1 rounded bg-black/40">
                      <span>{t('reactionTime')}: {friend.bestReactionMs}ms</span>
                      <span>{t('winRate')}: {friend.winRate}%</span>
                      <span>{t('levelLabel')} {friend.level}</span>
                    </div>

                    <button
                      onClick={() => handleChallenge(friend)}
                      className="w-full bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs py-2 rounded-lg transition-all flex items-center justify-center gap-1.5 cursor-pointer shadow-sm"
                    >
                      <Swords className="w-3.5 h-3.5 fill-black" />
                      <span>{t('challengeRival')} ({selectedStake} USDT)</span>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Footer info */}
        <div className="pt-3 mt-2 border-t border-white/[0.04] flex items-center justify-between text-[10px] text-zinc-500">
          <div className="flex items-center gap-1">
            <Shield className="w-3 h-3 text-emerald-400" />
            <span>{t('antiCheatHardwareStatus')}</span>
          </div>
          <span className="font-mono text-emerald-400/90 font-medium">{t('platformFee')}</span>
        </div>
      </motion.div>
    </div>
  );
};
