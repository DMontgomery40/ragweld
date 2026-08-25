import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const ONBOARDING_MAX_STEP = 4;
const ONBOARDING_MIN_STEP = 1;

const clampStep = (step: number) =>
  Math.max(ONBOARDING_MIN_STEP, Math.min(ONBOARDING_MAX_STEP, step));

interface OnboardingStore {
  step: number;
  /** Corpus the wizard created or picked; survives a reload so step 2/3 keep their target. */
  corpusId: string;

  setStep: (step: number) => void;
  nextStep: () => void;
  prevStep: () => void;
  setCorpusId: (corpusId: string) => void;
  reset: () => void;
}

export const useOnboardingStore = create<OnboardingStore>()(
  persist(
    (set, get) => ({
      step: 1,
      corpusId: '',

      setStep: (step) => set({ step: clampStep(step) }),
      nextStep: () => set({ step: clampStep(get().step + 1) }),
      prevStep: () => set({ step: clampStep(get().step - 1) }),
      setCorpusId: (corpusId) => set({ corpusId: String(corpusId || '').trim() }),
      reset: () => set({ step: 1, corpusId: '' }),
    }),
    {
      name: 'tribrid-onboarding-ui',
      partialize: (state) => ({ step: state.step, corpusId: state.corpusId }),
    }
  )
);
