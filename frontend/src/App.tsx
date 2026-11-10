import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { Analytics as VercelAnalytics } from '@vercel/analytics/react';
import { SpeedInsights } from '@vercel/speed-insights/react';
import { AuthProvider } from '@/context/AuthContext';
import { ToastProvider } from '@/context/ToastContext';
import { AppLayout } from '@/components/layout/AppLayout';
import { Landing } from '@/pages/Landing';
import { Auth } from '@/pages/Auth';
import { Overview } from '@/pages/Overview';
import { Providers } from '@/pages/Providers';
import { Models } from '@/pages/Models';
import { Keys } from '@/pages/Keys';
import { RequestExplorer } from '@/pages/RequestExplorer';
import { Analytics } from '@/pages/Analytics';
import { Reliability } from '@/pages/Reliability';
import { Settings } from '@/pages/Settings';
import { Docs } from '@/pages/Docs';

const googleClientId =
  import.meta.env.VITE_GOOGLE_CLIENT_ID || 'dummy-google-client-id';

export const App: React.FC = () => {
  return (
    <GoogleOAuthProvider clientId={googleClientId}>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter>
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
            <VercelAnalytics />
            <SpeedInsights />
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </GoogleOAuthProvider>
  );
};

export default App;
