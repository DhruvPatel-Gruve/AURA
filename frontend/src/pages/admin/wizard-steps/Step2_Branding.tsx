import { useState, useEffect, useRef } from 'react'
import { Upload, RefreshCw, Sun, Moon, Minus, Palette } from 'lucide-react'
import { extractBrandingFromLogo, type LogoBrightness } from '@/utils/colorExtractor'
import { cn } from '@/utils/cn'

interface BrandingData {
  company_name: string
  company_logo: string   // base64 data URL
  accent_color: string   // extracted hex
}

interface Props {
  initialData?: Partial<BrandingData>
  onChange: (data: BrandingData, valid: boolean) => void
}

const BRIGHTNESS_META: Record<LogoBrightness, { label: string; detail: string; icon: typeof Sun }> = {
  light: {
    label: 'Light logo detected',
    detail: 'Accent toned up — colour made richer and more saturated to stand out on light backgrounds.',
    icon: Sun,
  },
  dark: {
    label: 'Dark logo detected',
    detail: 'Accent toned down — colour lightened and softened so it doesn\'t look harsh.',
    icon: Moon,
  },
  mid: {
    label: 'Mid-tone logo',
    detail: 'Accent normalised to a balanced, usable shade.',
    icon: Minus,
  },
}

export default function Step2_Branding({ initialData, onChange }: Props) {
  const [companyName, setCompanyName] = useState(initialData?.company_name ?? '')
  const [logoDataUrl, setLogoDataUrl] = useState(initialData?.company_logo ?? '')
  const [accentHex,     setAccentHex]    = useState<string | null>(initialData?.accent_color || null)
  const [brightness,    setBrightness]   = useState<LogoBrightness | null>(null)
  const [noColorFound,  setNoColorFound] = useState(false)
  const [extracting,  setExtracting] = useState(false)
  const [extractErr,  setExtractErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // Emit valid state on any field change
  useEffect(() => {
    const valid = companyName.trim().length > 0
    onChange(
      { company_name: companyName.trim(), company_logo: logoDataUrl, accent_color: accentHex ?? '' },
      valid,
    )
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyName, logoDataUrl, accentHex])

  const handleFile = async (file: File) => {
    if (!file.type.startsWith('image/')) {
      setExtractErr('Please upload a PNG, SVG, or JPEG image.')
      return
    }
    setExtractErr(null)
    setExtracting(true)

    const reader = new FileReader()
    reader.onload = async (e) => {
      try {
        const dataUrl = e.target?.result as string
        const result  = await extractBrandingFromLogo(dataUrl)
        setLogoDataUrl(result.logoDataUrl)
        setAccentHex(result.accentHex)
        setBrightness(result.brightness)
        setNoColorFound(result.accentHex === null)
      } catch {
        setExtractErr('Could not extract colour from logo. You can still continue.')
        setLogoDataUrl(e.target?.result as string)
      } finally {
        setExtracting(false)
      }
    }
    reader.readAsDataURL(file)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) void handleFile(file)
  }

  const clearLogo = () => {
    setLogoDataUrl('')
    setAccentHex(null)
    setBrightness(null)
    setNoColorFound(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  const bMeta = brightness ? BRIGHTNESS_META[brightness] : null

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Company Branding
        </h2>
        <p className="text-sm text-body mt-1">
          Your company name and logo will appear in the dashboard. AURA will extract an accent colour from your logo automatically.
        </p>
      </div>

      {/* Company name */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-body">
          Company Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          placeholder="Acme Corporation"
          maxLength={80}
          className="input-base max-w-sm"
        />
      </div>

      {/* Logo upload */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-body">
          Company Logo
          <span className="ml-1.5 text-xs font-normal text-faint">(PNG, SVG or JPEG — max 5 MB)</span>
        </label>

        {logoDataUrl ? (
          <div className="flex items-start gap-5">
            {/* Preview */}
            <div className="flex flex-col items-center gap-2">
              <div className="h-20 w-40 rounded-lg border border-line bg-white flex items-center justify-center p-3 shadow-card">
                <img src={logoDataUrl} alt="Company logo" className="max-h-full max-w-full object-contain" />
              </div>
              <span className="text-[11px] text-faint">Light background</span>
            </div>
            <div className="flex flex-col items-center gap-2">
              <div className="h-20 w-40 rounded-lg border border-neutral-700 bg-neutral-900 flex items-center justify-center p-3 shadow-card">
                <img src={logoDataUrl} alt="Company logo" className="max-h-full max-w-full object-contain" />
              </div>
              <span className="text-[11px] text-faint">Dark background</span>
            </div>

            <div className="flex flex-col gap-2 mt-1">
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="btn-ghost text-xs flex items-center gap-1.5"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Replace
              </button>
              <button
                type="button"
                onClick={clearLogo}
                className="btn-ghost text-xs text-red-600 hover:text-red-700 dark:text-red-400 flex items-center gap-1.5"
              >
                Remove
              </button>
            </div>
          </div>
        ) : (
          <div
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => fileRef.current?.click()}
            className={cn(
              'flex flex-col items-center justify-center gap-3 cursor-pointer',
              'h-32 max-w-sm rounded-lg border-2 border-dashed',
              'border-line',
              'hover:border-accent hover:bg-accent/5 transition-colors',
            )}
          >
            {extracting ? (
              <RefreshCw className="h-6 w-6 text-accent animate-spin" />
            ) : (
              <Upload className="h-6 w-6 text-faint" />
            )}
            <p className="text-sm text-body text-center px-4">
              {extracting ? 'Extracting accent colour…' : 'Drag & drop your logo here, or click to browse'}
            </p>
          </div>
        )}

        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void handleFile(file)
          }}
        />

        {extractErr && (
          <p className="text-xs text-amber-600 dark:text-amber-400">{extractErr}</p>
        )}
      </div>

      {/* Extracted accent preview */}
      {logoDataUrl && (
        noColorFound ? (
          <div className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/20 p-4 flex items-start gap-3">
            <Palette className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
                No distinct colour found
              </p>
              <p className="text-xs text-amber-700 dark:text-amber-400 mt-0.5">
                Your logo appears to be black, white, or greyscale. AURA&apos;s default green will be kept as the accent colour. You can change it later in Admin Settings.
              </p>
            </div>
          </div>
        ) : accentHex && bMeta ? (
          <div className="rounded-lg border border-line p-4 space-y-3">
            <div className="flex items-center gap-3">
              <div
                className="h-10 w-10 rounded-lg shadow-card shrink-0"
                style={{ backgroundColor: accentHex }}
              />
              <div>
                <p className="text-sm font-medium text-ink flex items-center gap-1.5">
                  <bMeta.icon className="h-3.5 w-3.5" />
                  {bMeta.label}
                </p>
                <p className="text-xs text-faint">{bMeta.detail}</p>
              </div>
              <span className="ml-auto font-mono text-xs text-faint shrink-0">{accentHex}</span>
            </div>

            {/* Live UI preview */}
            <div className="rounded-lg border border-line bg-sunken p-3 space-y-2">
              <p className="overline-label mb-2">Preview</p>
              <div className="flex gap-2 flex-wrap">
                <button
                  type="button"
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-white"
                  style={{ backgroundColor: accentHex }}
                >
                  Primary button
                </button>
                <span
                  className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium text-white"
                  style={{ backgroundColor: accentHex }}
                >
                  Badge
                </span>
                <span
                  className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
                  style={{ backgroundColor: `${accentHex}22`, color: accentHex }}
                >
                  Subtle badge
                </span>
              </div>
            </div>
          </div>
        ) : null
      )}

      {/* Skip hint */}
      {!logoDataUrl && (
        <p className="text-xs text-faint">
          Logo upload is optional — you can add it later from Admin Settings. Company name is required to continue.
        </p>
      )}
    </div>
  )
}
