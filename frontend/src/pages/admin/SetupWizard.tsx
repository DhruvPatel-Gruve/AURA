import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { setupApi } from '@/api/setup.api'
import { WizardShell } from '@/components/wizard/WizardShell'
import { useConfigStore, DEFAULT_ACCENT } from '@/store/configStore'

import Step1_Welcome             from './wizard-steps/Step1_Welcome'
import Step2_ChooseProvider      from './wizard-steps/Step2_ChooseProvider'
import Step3_Branding            from './wizard-steps/Step2_Branding'
import Step4_JSMConnection       from './wizard-steps/Step2_JSMConnection'
import Step4_ZendeskConnection   from './wizard-steps/Step4_ZendeskConnection'
import Step5_ModelAIConfig       from './wizard-steps/Step5_ModelAIConfig'
import Step6_CategoriesSLA       from './wizard-steps/Step3_CategoriesSLA'
import Step7_TeamsUsers          from './wizard-steps/Step4_TeamsUsers'
import Step8_AgentConfig         from './wizard-steps/Step5_AgentConfig'
import Step9_KnowledgeIngestion  from './wizard-steps/Step6_KnowledgeIngestion'
import Step10_ReviewLaunch       from './wizard-steps/Step7_ReviewLaunch'

const TOTAL_STEPS = 10

interface Props {
  onLaunch?: () => void
}

export default function SetupWizard({ onLaunch }: Props) {
  const navigate             = useNavigate()
  const { setCompanyBranding, setAccentColor } = useConfigStore()

  const [currentStep,  setCurrentStep]  = useState(1)
  const [stepData,     setStepData]     = useState<Record<number, unknown>>({})
  const [canProceed,   setCanProceed]   = useState(true)
  const [saving,       setSaving]       = useState(false)
  const [launching,    setLaunching]    = useState(false)
  const [saveError,    setSaveError]    = useState<string | null>(null)

  // Restore saved progress from backend on mount
  useEffect(() => {
    setupApi.getProgress()
      .then(({ steps }) => {
        if (Object.keys(steps).length > 0) {
          setStepData(steps as Record<number, unknown>)
          const maxSaved = Math.max(...Object.keys(steps).map(Number))
          setCurrentStep(Math.min(maxSaved + 1, TOTAL_STEPS))
        }
      })
      .catch(() => { /* start fresh if backend unreachable */ })
  }, [])

  const handleChange = useCallback((data: unknown, valid: boolean) => {
    setStepData((prev) => ({ ...prev, [currentStep]: data }))
    setCanProceed(valid)
    // Live accent preview: apply client colour as soon as step 3 (Branding) produces one,
    // reset to AURA green if the logo is cleared or yields no extractable colour.
    if (currentStep === 3) {
      const b = data as { accent_color?: string }
      setAccentColor(b?.accent_color || DEFAULT_ACCENT)
    }
  }, [currentStep, setAccentColor])

  const handleNext = async () => {
    setSaveError(null)

    if (currentStep === TOTAL_STEPS) {
      setLaunching(true)
      try {
        await setupApi.complete()
        // Apply branding immediately after launch
        const b3 = stepData[3] as { company_name?: string; company_logo?: string; accent_color?: string } | undefined
        if (b3) {
          setCompanyBranding(b3.company_name ?? '', b3.company_logo ?? '', b3.accent_color ?? '')
        }
        onLaunch?.()
        navigate('/admin', { replace: true })
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? 'Could not complete setup'
        setSaveError(msg)
      } finally {
        setLaunching(false)
      }
      return
    }

    setSaving(true)
    try {
      await setupApi.saveStep({
        step: currentStep,
        data: (stepData[currentStep] ?? {}) as Record<string, unknown>,
      })
      setCurrentStep((s) => s + 1)
      setCanProceed(false)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Failed to save step'
      setSaveError(msg)
    } finally {
      setSaving(false)
    }
  }

  const handleBack = () => {
    if (currentStep > 1) {
      setSaveError(null)
      setCurrentStep((s) => s - 1)
      setCanProceed(true)
    }
  }

  const stepKey  = `step-${currentStep}`
  const provider = ((stepData[2] as { itsm_provider?: string } | undefined)?.itsm_provider ?? 'jira') as 'jira' | 'zendesk'

  return (
    <WizardShell
      currentStep={currentStep}
      canProceed={canProceed}
      saving={saving}
      isLastStep={currentStep === TOTAL_STEPS}
      launching={launching}
      saveError={saveError}
      onBack={handleBack}
      onNext={handleNext}
    >
      {currentStep === 1 && (
        <Step1_Welcome
          key={stepKey}
          initialData={stepData[1] as Parameters<typeof Step1_Welcome>[0]['initialData']}
          onChange={handleChange}
        />
      )}
      {currentStep === 2 && (
        <Step2_ChooseProvider
          key={stepKey}
          initialData={stepData[2] as Parameters<typeof Step2_ChooseProvider>[0]['initialData']}
          onChange={handleChange}
        />
      )}
      {currentStep === 3 && (
        <Step3_Branding
          key={stepKey}
          initialData={stepData[3] as Parameters<typeof Step3_Branding>[0]['initialData']}
          onChange={handleChange}
        />
      )}
      {currentStep === 4 && (
        (provider === 'zendesk' ? (
          <Step4_ZendeskConnection
            key={stepKey}
            initialData={stepData[4] as Parameters<typeof Step4_ZendeskConnection>[0]['initialData']}
            onChange={handleChange}
          />
        ) : (
          <Step4_JSMConnection
            key={stepKey}
            initialData={stepData[4] as Parameters<typeof Step4_JSMConnection>[0]['initialData']}
            onChange={handleChange}
          />
        ))
      )}
      {currentStep === 5 && (
        <Step5_ModelAIConfig
          key={stepKey}
          initialData={stepData[5] as Parameters<typeof Step5_ModelAIConfig>[0]['initialData']}
          onChange={handleChange}
        />
      )}
      {currentStep === 6 && (
        <Step6_CategoriesSLA
          key={stepKey}
          initialData={stepData[6] as Parameters<typeof Step6_CategoriesSLA>[0]['initialData']}
          onChange={handleChange}
        />
      )}
      {currentStep === 7 && (
        <Step7_TeamsUsers
          key={stepKey}
          initialData={stepData[7] as Parameters<typeof Step7_TeamsUsers>[0]['initialData']}
          onChange={handleChange}
        />
      )}
      {currentStep === 8 && (
        <Step8_AgentConfig
          key={stepKey}
          provider={provider}
          initialData={stepData[8] as Parameters<typeof Step8_AgentConfig>[0]['initialData']}
          onChange={handleChange}
        />
      )}
      {currentStep === 9 && (
        <Step9_KnowledgeIngestion
          key={stepKey}
          provider={provider}
          initialData={stepData[9] as Parameters<typeof Step9_KnowledgeIngestion>[0]['initialData']}
          onChange={handleChange}
        />
      )}
      {currentStep === 10 && (
        <Step10_ReviewLaunch
          key={stepKey}
          savedSteps={stepData}
          onChange={handleChange}
        />
      )}
    </WizardShell>
  )
}
