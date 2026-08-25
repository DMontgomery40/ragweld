import { ONBOARDING_MAX_STEP, useOnboardingStore } from '@/stores/useOnboardingStore';

export function useOnboarding() {
  const step = useOnboardingStore((s) => s.step);
  const corpusId = useOnboardingStore((s) => s.corpusId);
  const setStep = useOnboardingStore((s) => s.setStep);
  const nextStep = useOnboardingStore((s) => s.nextStep);
  const prevStep = useOnboardingStore((s) => s.prevStep);
  const setCorpusId = useOnboardingStore((s) => s.setCorpusId);
  const reset = useOnboardingStore((s) => s.reset);

  return {
    step,
    corpusId,
    maxStep: ONBOARDING_MAX_STEP,
    setStep,
    nextStep,
    prevStep,
    setCorpusId,
    reset,
  };
}
