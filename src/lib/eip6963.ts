/**
 * EIP-6963: Multi Injected Provider Discovery standard
 * Automatically discovers all installed Web3 wallets (MetaMask, Rabby, Phantom, Coinbase, Trust, Rainbow, OKX, SubWallet, etc.)
 */

export interface EIP6963ProviderInfo {
  uuid: string;
  name: string;
  icon: string;
  rdns: string;
}

export interface EIP6963ProviderDetail {
  info: EIP6963ProviderInfo;
  provider: any;
}

export interface EIP6963AnnounceProviderEvent extends CustomEvent {
  type: 'eip6963:announceProvider';
  detail: EIP6963ProviderDetail;
}

class EIP6963Manager {
  private providers: Map<string, EIP6963ProviderDetail> = new Map();
  private listeners: Array<(providers: EIP6963ProviderDetail[]) => void> = [];

  constructor() {
    if (typeof window !== 'undefined') {
      this.init();
    }
  }

  private init() {
    window.addEventListener('eip6963:announceProvider', (event: any) => {
      if (event && event.detail && event.detail.info && event.detail.info.rdns) {
        this.providers.set(event.detail.info.rdns, event.detail);
        this.notify();
      }
    });

    // Request providers to announce themselves
    try {
      window.dispatchEvent(new Event('eip6963:requestProvider'));
    } catch {}
  }

  public getProviders(): EIP6963ProviderDetail[] {
    return Array.from(this.providers.values());
  }

  public getProviderByRdns(rdns: string): EIP6963ProviderDetail | undefined {
    return this.providers.get(rdns);
  }

  public getProviderByName(name: string): EIP6963ProviderDetail | undefined {
    const lower = name.toLowerCase();
    for (const p of this.providers.values()) {
      if (p.info.name.toLowerCase().includes(lower) || p.info.rdns.toLowerCase().includes(lower)) {
        return p;
      }
    }
    return undefined;
  }

  public subscribe(callback: (providers: EIP6963ProviderDetail[]) => void): () => void {
    this.listeners.push(callback);
    callback(this.getProviders());
    return () => {
      this.listeners = this.listeners.filter((l) => l !== callback);
    };
  }

  private notify() {
    const list = this.getProviders();
    this.listeners.forEach((cb) => cb(list));
  }
}

export const eip6963Manager = new EIP6963Manager();
