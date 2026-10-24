# 🖥️ PortfolioMaster Frontend

Production-ready Next.js 16 (App Router) client application for **PortfolioMaster / watchlistTracker (WT)**.

## 🏗️ Architecture

- **Framework**: Next.js 16.4 (React 19) with App Router and Turbopack.
- **State Management**: React Context (`PortfolioContext`) with real-time SSE stream reader and Supabase client-side session subscription.
- **Data Table**: `@tanstack/react-table` v8 with virtualized responsive layout, inline editing, and column resizing.
- **Styling**: Tailwind CSS v4 with custom dark mode design system and financial typography (`tabular-nums`).
- **Authentication**: Supabase Auth (session stored securely in localStorage, bearer tokens attached via fetch interceptor).
- **Hosting Target**: [Vercel](https://vercel.com) (Root Directory: `frontend`).

---

## 🚀 Local Development

### 1. Prerequisites
- Node.js >= 20.x (Recommended: 24.x LTS)
- npm >= 10.x

### 2. Environment Variables
Create `.env.local` in `frontend/`:
```env
# URL of your backend API (optional for local dev; Next.js proxies /api to http://localhost:8000 by default)
NEXT_PUBLIC_API_URL=http://localhost:8000

# Supabase Project Credentials (from Supabase Dashboard -> Settings -> API)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here
```

### 3. Install & Run
```bash
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🧪 Testing & Verification

Run the test and verification suite:
```bash
# Type check without emitting files
npx tsc --noEmit

# Lint check
npm run lint

# Automated integration and regression test suite
npm test

# Production build verification
npm run build
```

---

## 🌐 Production Deployment on Vercel

1. In the Vercel dashboard, click **Add New Project** and import the `PortfolioMaster` repository.
2. In **Project Settings**:
   - **Root Directory**: `frontend`
   - **Framework Preset**: `Next.js`
   - **Build Command**: `next build`
   - **Install Command**: `npm install`
3. Configure **Environment Variables** in Vercel:
   | Variable | Value / Description |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | Full URL of your deployed Render service (e.g. `https://portfoliomaster-backend.onrender.com`) |
   | `NEXT_PUBLIC_SUPABASE_URL` | Your Supabase project URL (`https://xyz.supabase.co`) |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Your Supabase public anon key |
4. Deploy. Vercel automatically deploys preview environments for pull requests and updates production on merges to `main`.
