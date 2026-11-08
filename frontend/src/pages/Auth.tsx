import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { GoogleLogin, CredentialResponse } from '@react-oauth/google';
import { useAuth } from '@/context/AuthContext';

export const Auth: React.FC = () => {
  const { user, signInWithGoogle, isDevMode, error: authError } = useAuth();
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

  const handleDevSignIn = async () => {
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await signInWithGoogle();
      navigate('/app/overview');
    } catch (err: any) {
      setErrorMessage(err?.message || 'Dev Sign-In failed.');
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

      {/* Form Area */}
      <div className="grid place-content-center p-12 max-w-[430px] mx-auto w-full gap-5 max-app:p-6">
        <div>
          <h2 className="font-display font-normal text-[22px] leading-appHeadline text-ink">
            Welcome back
          </h2>
          <p className="text-[15px] text-mute mt-1">
            Sign in with Google to open your dashboard.
          </p>
        </div>

        {(errorMessage || authError) && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-3.5 py-2.5 rounded-xl text-sm flex items-start gap-2">
            <span className="font-semibold shrink-0">Error:</span>
            <span>{errorMessage || authError}</span>
          </div>
        )}

        <div className="flex flex-col gap-3 w-full">
          {/* Dev Mode Primary Fast-Pass */}
          {isDevMode && (
            <div className="space-y-3">
              <button
                type="button"
                onClick={handleDevSignIn}
                disabled={isSubmitting}
                className="inline-flex items-center justify-center gap-2 bg-violet text-white font-medium text-[14px] rounded-pill py-3 px-5 hover:bg-violet-dark transition-all cursor-pointer w-full shadow-md disabled:opacity-50"
              >
                <span>{isSubmitting ? 'Signing in…' : 'Continue as Sai Ramesh (sairamesh189@gmail.com)'}</span>
              </button>
              <div className="text-center text-[12px] text-mute flex items-center justify-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span>3 Providers Active &bull; 84 Free Models &bull; Instant Access</span>
              </div>
              <div className="flex items-center gap-2 my-2 text-mute text-xs">
                <hr className="flex-1 border-line" />
                <span>or use Google OAuth</span>
                <hr className="flex-1 border-line" />
              </div>
            </div>
          )}

          {/* Native Google OAuth Button */}
          <div className="flex justify-center w-full min-h-[44px]">
            <GoogleLogin
              onSuccess={handleGoogleSuccess}
              onError={() => {
                setErrorMessage('Google Sign-In failed: The OAuth Client ID in your .env is invalid or not registered in Google Cloud Console. Click "Continue with Developer Identity" above to proceed without Google.');
              }}
              shape="pill"
              size="large"
              width="100%"
              text="continue_with"
            />
          </div>
        </div>

        {isDevMode && (
          <div className="text-center text-[12px] text-mute bg-ink/5 p-2 rounded-lg">
            Development Mode &bull; Uses local auth bypass when Google Client ID is unconfigured
          </div>
        )}

        <p className="text-[13px] text-mute text-center leading-relaxed">
          Sessions are secured via HttpOnly cookies. Relay never exposes access tokens to client JavaScript.
        </p>
      </div>
    </div>
  );
};
