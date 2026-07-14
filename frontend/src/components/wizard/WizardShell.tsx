import React from 'react'
import { Check, Zap } from 'lucide-react'
import { cn } from '@/utils/cn'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'

const STEP_LABELS = [
  'Welcome',
  'Provider',
  'Branding',
  'Connection',
  'AI Config',
  'Categories',
  'Teams',
  'Agent Config',
  'Knowledge',
  'Review',
]

interface WizardShellProps {
  currentStep: number    // 1-indexed
  canProceed:  boolean
  saving:      boolean
  isLastStep?: boolean
  launching?:  boolean
  saveError?:  string | null
  onBack:      () => void
  onNext:      () => void
  children:    React.ReactNode
}

export function WizardShell({
  currentStep,
  canProceed,
  saving,
  isLastStep = false,
  launching  = false,
  saveError  = null,
  onBack,
  onNext,
  children,
}: WizardShellProps) {
  const total = STEP_LABELS.length
  const busy  = saving || launching

  return (
    <div className="min-h-screen flex flex-col bg-canvas">
      {/* ── Top bar ────────────────────────────────────────────────────────── */}
      <header className="relative z-10 flex items-center justify-between h-13 px-6
                         border-b border-line bg-surface">
        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-lg bg-accent flex items-center justify-center">
            <Zap className="h-3.5 w-3.5 text-accent-fg" />
          </div>
          <span className="text-sm font-semibold text-ink">AURA Setup</span>
        </div>
        <span className="font-mono text-xs text-faint">
          Step {currentStep} of {total}
        </span>
      </header>

      {/* ── Step indicator ─────────────────────────────────────────────────── */}
      <div className="relative z-10 bg-surface border-b border-line px-6 pt-4 pb-5">
        <div className="max-w-3xl mx-auto">
          <ol className="flex items-start w-full">
            {STEP_LABELS.map((label, i) => {
              const n       = i + 1
              const isLast  = i === total - 1
              const done    = n < currentStep
              const active  = n === currentStep

              return (
                <li key={n} className={cn('flex flex-col', !isLast && 'flex-1')}>
                  {/* Circle + connecting line */}
                  <div className="flex items-center">
                    <div
                      className={cn(
                        'h-7 w-7 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-mono font-semibold tabular-nums',
                        done
                          ? 'bg-accent text-accent-fg'
                          : active
                            ? 'ring-2 ring-accent text-accent bg-accent-subtle'
                            : 'bg-sunken text-faint',
                      )}
                    >
                      {done ? <Check className="h-3.5 w-3.5" /> : n}
                    </div>
                    {!isLast && (
                      <div
                        className={cn(
                          'flex-1 h-px mx-1.5',
                          done ? 'bg-accent' : 'bg-line',
                        )}
                      />
                    )}
                  </div>
                  {/* Label */}
                  <span
                    className={cn(
                      'mt-1.5 text-overline font-medium uppercase hidden sm:block',
                      active
                        ? 'text-accent'
                        : done
                          ? 'text-body'
                          : 'text-faint',
                    )}
                  >
                    {label}
                  </span>
                </li>
              )
            })}
          </ol>
        </div>
      </div>

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <main className="relative z-10 flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-3xl mx-auto">
          {children}
        </div>
      </main>

      {/* ── Footer nav ─────────────────────────────────────────────────────── */}
      <footer className="relative z-10 border-t border-line bg-surface px-6 py-3">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <button
            type="button"
            onClick={onBack}
            disabled={currentStep === 1 || busy}
            className="btn-secondary"
          >
            Back
          </button>

          <div className="flex items-center gap-3">
            {saveError && (
              <span className="text-xs text-red-600 dark:text-red-400">{saveError}</span>
            )}
            <button
              type="button"
              onClick={onNext}
              disabled={!canProceed || busy}
              className="btn-primary min-w-[110px]"
            >
              {busy ? (
                <LoadingSpinner size="sm" />
              ) : isLastStep ? (
                'Launch AURA'
              ) : (
                'Continue'
              )}
            </button>
          </div>
        </div>
      </footer>
    </div>
  )
}
