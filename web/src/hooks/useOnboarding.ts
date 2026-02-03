import { ONBOARDING_MAX_STEP, useOnboardingStore } from '@/stores/useOnboardingStore';

export function useOnboarding() {
  const step = useOnboardingStore((s) => s.step);
  const setStep = useOnboardingStore((s) => s.setStep);
  const nextStep = useOnboardingStore((s) => s.nextStep);
  const prevStep = useOnboardingStore((s) => s.prevStep);
  const reset = useOnboardingStore((s) => s.reset);

  return {
    step,
    maxStep: ONBOARDING_MAX_STEP,
    setStep,
    nextStep,
    prevStep,
    reset,
  };
}

