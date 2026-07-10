// Canvas-based dominant color extraction + accent toning.
// All processing is client-side — no server round-trip needed.

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255, gn = g / 255, bn = b / 255
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn)
  const l = (max + min) / 2
  if (max === min) return [0, 0, l]

  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h: number
  switch (max) {
    case rn: h = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6; break
    case gn: h = ((bn - rn) / d + 2) / 6; break
    default: h = ((rn - gn) / d + 4) / 6
  }
  return [h, s, l]
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  if (s === 0) {
    const v = Math.round(l * 255)
    return [v, v, v]
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  const hue2 = (t: number) => {
    if (t < 0) t += 1
    if (t > 1) t -= 1
    if (t < 1 / 6) return p + (q - p) * 6 * t
    if (t < 1 / 2) return q
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6
    return p
  }
  return [
    Math.round(hue2(h + 1 / 3) * 255),
    Math.round(hue2(h) * 255),
    Math.round(hue2(h - 1 / 3) * 255),
  ]
}

function relativeLuminance(r: number, g: number, b: number): number {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`
}

// Draw image onto a capped canvas (max 200px wide) and return the data URL
// for compact storage. Returns both the resized data URL and pixel data.
function drawToCanvas(img: HTMLImageElement): {
  dataUrl: string
  pixels: Uint8ClampedArray
  width: number
  height: number
} {
  const MAX = 200
  const scale = Math.min(1, MAX / Math.max(img.width, img.height))
  const w = Math.round(img.width * scale)
  const h = Math.round(img.height * scale)

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  ctx.drawImage(img, 0, 0, w, h)

  return {
    dataUrl: canvas.toDataURL('image/png'),
    pixels: ctx.getImageData(0, 0, w, h).data,
    width: w,
    height: h,
  }
}

// Extract the most common non-neutral, non-background color.
// Returns null when the logo has no extractable chromatic color (e.g. pure black/white/grey).
function getDominantRgb(pixels: Uint8ClampedArray): [number, number, number] | null {
  const counts: Record<string, number> = {}

  for (let i = 0; i < pixels.length; i += 4) {
    const r = pixels[i], g = pixels[i + 1], b = pixels[i + 2], a = pixels[i + 3]
    if (a < 128) continue                               // transparent
    if (r > 230 && g > 230 && b > 230) continue        // near-white
    if (r < 25  && g < 25  && b < 25)  continue        // near-black
    const sat = Math.max(r, g, b) - Math.min(r, g, b)
    if (sat < 25) continue                              // near-grey

    // Quantize to 8-step buckets
    const key = `${r >> 3},${g >> 3},${b >> 3}`
    counts[key] = (counts[key] ?? 0) + 1
  }

  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]
  if (!top) return null   // no extractable chromatic color — caller should keep current accent

  const [rs, gs, bs] = top[0].split(',').map(Number)
  return [(rs << 3) | 4, (gs << 3) | 4, (bs << 3) | 4]
}

// Apply light/dark toning so the color works as a UI accent:
//   Light logo (high L) → tone UP: saturate + deepen to make it vivid
//   Dark  logo (low L)  → tone DOWN: lighten + soften so it's not muddy
// Then enforce WCAG AA contrast (4.5:1) against white text.
function toneForAccent(r: number, g: number, b: number): string {
  const [h, s, l] = rgbToHsl(r, g, b)

  let targetS: number
  let targetL: number

  if (l > 0.6) {
    // Light-dominant logo → tone UP: rich, saturated shade
    targetS = Math.max(s, 0.65)
    targetL = 0.36
  } else if (l < 0.28) {
    // Dark-dominant logo → tone DOWN: lighter, softer
    targetS = Math.min(s, 0.50)
    targetL = 0.44
  } else {
    // Mid-tone → minor normalisation
    targetS = Math.max(s, 0.55)
    targetL = 0.40
  }

  let [tr, tg, tb] = hslToRgb(h, targetS, targetL)

  // Enforce WCAG AA: contrast with white must be ≥ 4.5:1
  // Max luminance for this: (1.05 / 4.5) − 0.05 ≈ 0.183
  let currentL = targetL
  while (relativeLuminance(tr, tg, tb) > 0.183 && currentL > 0.15) {
    currentL -= 0.02
    ;[tr, tg, tb] = hslToRgb(h, targetS, currentL)
  }

  return rgbToHex(tr, tg, tb)
}

export type LogoBrightness = 'light' | 'dark' | 'mid'

export interface ExtractionResult {
  accentHex:   string | null   // toned accent ready to use; null = no extractable color
  brightness:  LogoBrightness | null
  logoDataUrl: string          // resized data URL for storage
}

export function extractBrandingFromLogo(dataUrl: string): Promise<ExtractionResult> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      try {
        const { dataUrl: resized, pixels } = drawToCanvas(img)
        const dominant = getDominantRgb(pixels)

        if (!dominant) {
          // Logo is black, white, or greyscale — no color to extract, keep current accent
          resolve({ accentHex: null, brightness: null, logoDataUrl: resized })
          return
        }

        const [dr, dg, db] = dominant
        const [, , l] = rgbToHsl(dr, dg, db)
        const brightness: LogoBrightness = l > 0.6 ? 'light' : l < 0.28 ? 'dark' : 'mid'
        const accentHex = toneForAccent(dr, dg, db)

        resolve({ accentHex, brightness, logoDataUrl: resized })
      } catch (err) {
        reject(err)
      }
    }
    img.onerror = () => reject(new Error('Could not load image'))
    img.src = dataUrl
  })
}
