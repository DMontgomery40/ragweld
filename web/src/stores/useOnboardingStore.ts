import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const ONBOARDING_MAX_STEP = 5;
const ONBOARDING_MIN_STEP = 1;

const clampStep = (step: number) =>
  Math.max(ONBOARDING_MIN_STEP, Math.min(ONBOARDING_MAX_STEP, step));

interface OnboardingStore {
  step: number;

  setStep: (step: number) => void;
  nextStep: () => void;
  prevStep: () => void;
  reset: () => void;
}

export const useOnboardingStore = create<OnboardingStore>()(
  persist(
    (set, get) => ({
      step: 1,

      setStep: (step) => set({ step: clampStep(step) }),
      nextStep: () => set({ step: clampStep(get().step + 1) }),
      prevStep: () => set({ step: clampStep(get().step - 1) }),
      reset: () => set({ step: 1 }),
    }),
    {
      name: 'tribrid-onboarding-ui',
      partialize: (state) => ({ step: state.step }),
    }
  )
);

