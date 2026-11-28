import { getPositions, getMetrics, getConfig, ApiError } from '@/lib/api';
import { isAuthConfigured } from '@/lib/supabase';
import { getServerAuth } from '@/lib/supabase/server';
import { AppHeader } from '@/components/AppHeader';
import { WatchlistContent } from '@/components/WatchlistContent';
import { TranslatedText } from '@/context/LanguageContext';
import { PortfolioProvider } from '@/context/PortfolioContext';
import { AlertCircle } from 'lucide-react';

export const dynamic = 'force-dynamic';

async function WatchlistDataLoader() {
  const { user, accessToken } = await getServerAuth();
  const canLoadPortfolio = !isAuthConfigured || Boolean(accessToken);
  const [positions, metrics, config] = await Promise.allSettled([
    canLoadPortfolio ? getPositions('no-store', accessToken ?? undefined) : Promise.resolve(null),
    canLoadPortfolio ? getMetrics('no-store', accessToken ?? undefined) : Promise.resolve(null),
    getConfig(),
  ]);
  const connectionError = positions.status === 'rejected' &&
    !(positions.reason instanceof ApiError && positions.reason.status === 401);

  return (
    <div className="flex flex-col gap-6">
      {connectionError && (
        <div role="alert" className="flex items-center gap-3 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-xs text-amber-300">
          <AlertCircle className="size-4 shrink-0" />
          <span><TranslatedText tKey="backendConnectionError" /></span>
        </div>
      )}

      <PortfolioProvider
        serverUserId={user?.id ?? null}
        initialPositions={positions.status === 'fulfilled' ? positions.value?.positions ?? [] : []}
        initialMetrics={metrics.status === 'fulfilled' ? metrics.value : null}
        initialConfig={config.status === 'fulfilled' ? config.value : null}
        initialDataReady={positions.status === 'fulfilled' && metrics.status === 'fulfilled'}
      >
        <WatchlistContent />
      </PortfolioProvider>
    </div>
  );
}

export default function WatchlistPage() {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-950 text-zinc-100">
      <AppHeader />
      <main id="main-content" className="mx-auto flex w-full max-w-[1680px] flex-1 flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
        <WatchlistDataLoader />
      </main>
    </div>
  );
}
