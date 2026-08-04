import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom';
import { BarChart3, TrendingUp, Moon, Sun } from 'lucide-react';
import { useState, useEffect } from 'react';
import { Module1 } from '@/pages/Module1';
import { Module2 } from '@/pages/Module2';
import { OAuthCallback } from '@/pages/OAuthCallback';
import { cn } from '@/lib/utils';

function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'));
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
  }, [dark]);
  return (
    <button
      onClick={() => setDark((d) => !d)}
      className="rounded-md p-2 hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
      aria-label="Toggle theme"
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Top nav */}
      <header className="border-b bg-card sticky top-0 z-10">
        <div className="max-w-screen-2xl mx-auto px-4 h-14 flex items-center gap-6">
          <div className="flex items-center gap-2 font-semibold text-primary">
            <BarChart3 className="size-5" />
            <span>Options Analysis</span>
          </div>
          <nav className="flex gap-1">
            {[
              { to: '/module1', label: 'M1 — Intraday Swing', icon: TrendingUp },
              { to: '/module2', label: 'M2 — Overnight Gap', icon: BarChart3 },
            ].map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent',
                  )
                }
              >
                <Icon className="size-4" />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-screen-2xl mx-auto w-full px-4 py-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/oauth/callback" element={<OAuthCallback />} />
        <Route
          path="/module1"
          element={
            <Layout>
              <Module1 />
            </Layout>
          }
        />
        <Route
          path="/module1/:runId"
          element={
            <Layout>
              <Module1 />
            </Layout>
          }
        />
        <Route
          path="/module2"
          element={
            <Layout>
              <Module2 />
            </Layout>
          }
        />
        <Route
          path="/module2/:runId"
          element={
            <Layout>
              <Module2 />
            </Layout>
          }
        />
        <Route path="*" element={<Navigate to="/module1" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
