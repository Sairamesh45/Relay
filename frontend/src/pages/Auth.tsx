import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { GoogleLogin, CredentialResponse } from '@react-oauth/google';
import { useAuth } from '@/context/AuthContext';

export const Auth: React.FC = () => {
  const { user, signInWithGoogle, error: authError } = useAuth();
  const navigate = useNavigate();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      navigate('/app/overview', { replace: true });
    }
  }, [user, navigate]);

  const handleGoogleSuccess = async (credentialResponse: CredentialResponse) => {
    if (!credentialResponse.credential) {
      setErrorMessage('No ID token received from Google.');
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await signInWithGoogle(credentialResponse.credential);
      navigate('/app/overview');
    } catch (err: any) {
      setErrorMessage(err?.message || 'Google Sign-In failed.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="grid grid-cols-[1.1fr_1fr] min-h-screen bg-marshmallow font-body text-ink max-app:grid-cols-1">
      {/* Art Panel */}
      <div
        className="m-[14px] rounded-[28px] p-12 text-white flex flex-col justify-between shadow-2xl max-app:min-h-[280px] max-app:p-8"
        style={{
          background: `radial-gradient(70% 80% at 0 100%, #FF66E0, transparent 62%),
                       radial-gradient(80% 90% at 100% 0, #7A5CFF, transparent 60%),
                       #5B3DFF`,
        }}
      >
        <span className="flex items-center gap-[10px] font-display font-semibold text-[19px] tracking-[-0.02em] text-white m-0">
          <span className="w-[26px] h-[26px] rounded-[8px] bg-white grid place-items-center">
            <i className="w-[10px] h-[10px] rounded-full bg-gradient-to-br from-violet to-pink block" />
          </span>
          Relay
        </span>

        <h1 className="font-display font-light text-[68px] leading-appHeadline tracking-headline max-w-[8ch] max-app:text-[44px]">
          One API.<br />Every model.
        </h1>

        <span className="text-[13px] text-white/80">
          Connect the AI accounts you already have.
        </span>
      </div>

      {/* Auth Panel */}
      <div className="grid place-content-center p-12 max-w-[440px] mx-auto w-full gap-6 max-app:p-6">
        <div>
          <h2 className="font-display font-normal text-[26px] leading-appHeadline text-ink">
            Welcome back to Relay
          </h2>
          <p className="text-[15px] text-mute mt-2">
            Sign in with your Google account to access your gateway dashboard, model routes, and virtual keys.
          </p>
        </div>

        {(errorMessage || authError) && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-2xl text-sm flex items-start gap-2.5 shadow-sm">
            <svg
              className="w-5 h-5 text-red-500 shrink-0 mt-0.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <div className="text-xs leading-relaxed space-y-1">
              <span className="font-semibold block text-sm">Sign-In Notice</span>
              <span>{errorMessage || authError}</span>
            </div>
          </div>
        )}

        {/* Google OAuth Card */}
        <div className="p-6 rounded-2xl border border-line bg-white/80 shadow-sm flex flex-col items-center gap-4">
          <p className="text-xs text-mute font-medium text-center">
            Continue securely with Google Single Sign-On
          </p>
          <div className="flex justify-center w-full min-h-[44px]">
            <GoogleLogin
              onSuccess={handleGoogleSuccess}
              onError={() => {
                setErrorMessage(
                  'Google Sign-In failed: The OAuth client was not found or has expired. Please check GOOGLE_CLIENT_ID in your configuration.'
                );
              }}
              shape="pill"
              size="large"
              width="320"
              text="continue_with"
            />
          </div>
          {isSubmitting && (
            <div className="flex items-center gap-2 text-xs text-violet animate-pulse">
              <span className="w-3.5 h-3.5 rounded-full border-2 border-violet border-t-transparent animate-spin" />
              <span>Verifying Google account...</span>
            </div>
          )}
        </div>

        <p className="text-[12px] text-mute text-center leading-relaxed">
          Sessions are secured via HttpOnly cookies. Your provider keys and telemetry remain strictly isolated to your account.
        </p>
      </div>
    </div>
  );
};

export default Auth;
