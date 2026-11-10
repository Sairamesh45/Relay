import React, { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { Analytics as VercelAnalytics } from '@vercel/analytics/react';
import { SpeedInsights } from '@vercel/speed-insights/react';
import { AuthProvider } from '@/context/AuthContext';
import { ToastProvider } from '@/context/ToastContext';
import { AppLayout } from '@/components/layout/AppLayout';

const Landing = lazy(async () => ({
  default: (await import('@/pages/Landing')).Landing,
}));
const Auth = lazy(async () => ({
  default: (await import('@/pages/Auth')).Auth,
}));
const Overview = lazy(() => import('@/pages/Overview'));
const Providers = lazy(() => import('@/pages/Providers'));
const Models = lazy(() => import('@/pages/Models'));
const Keys = lazy(() => import('@/pages/Keys'));
const RequestExplorer = lazy(() => import('@/pages/RequestExplorer'));
const Analytics = lazy(() => import('@/pages/Analytics'));
const Reliability = lazy(() => import('@/pages/Reliability'));
const Settings = lazy(() => import('@/pages/Settings'));
const Docs = lazy(() => import('@/pages/Docs'));

const googleClientId =
  import.meta.env.VITE_GOOGLE_CLIENT_ID || 'dummy-google-client-id';

export const App: React.FC = () => {
  return (
    <GoogleOAuthProvider clientId={googleClientId}>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter>
            <Suspense fallback={<div className="min-h-screen bg-marshmallow" />}>
              <Routes>
                <Route path="/" element={<Landing />} />
                <Route path="/login" element={<Auth />} />
                <Route path="/app" element={<AppLayout />}>
                  <Route index element={<Navigate to="/app/overview" replace />} />
                  <Route path="overview" element={<Overview />} />
                  <Route path="providers" element={<Providers />} />
                  <Route path="models" element={<Models />} />
                  <Route path="keys" element={<Keys />} />
                  <Route path="requests" element={<RequestExplorer />} />
                  <Route path="analytics" element={<Analytics />} />
                  <Route path="reliability" element={<Reliability />} />
                  <Route path="settings" element={<Settings />} />
                  <Route path="docs" element={<Docs />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
            <VercelAnalytics />
            <SpeedInsights />
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </GoogleOAuthProvider>
  );
};

export default App;
