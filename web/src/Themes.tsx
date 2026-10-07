import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode, CSSProperties } from 'react'
import { Check, Palette, Pause, Play } from 'lucide-react'
import Modal from './Dialog'
import { readStorage, writeStorage } from './storage'

export const THEMES = [
  { id: 'aurora', name: 'Aurora', description: 'Northern lights, quietly in motion.', preview: 'linear-gradient(135deg,#12271f,#353052,#0b1718)' },
  { id: 'cosmic', name: 'Cosmic', description: 'Midnight skies and drifting starlight.', preview: 'radial-gradient(ellipse at 25% 25%,#5467a6,#11192b 75%)' },
  { id: 'ember', name: 'Ember', description: 'Warm charcoal and rising embers.', preview: 'radial-gradient(ellipse at 20% 100%,#b96731,#241511 75%)' },
  { id: 'daylight', name: 'Daylight', description: 'A bright, calm place to think.', preview: 'linear-gradient(135deg,#f9fbff,#d7e9fa,#dff1e8)' },
  { id: 'atoms', name: 'Atoms', description: 'Orbiting ideas, connected energy.', preview: 'radial-gradient(circle at 50% 50%,#787147,#19271b 48%,#101810)' },
  { id: 'deep-sea', name: 'Deep Sea', description: 'Ocean light beneath the surface.', preview: 'linear-gradient(155deg,#175b68,#102939 45%,#071923)' },
  { id: 'deep-galaxy', name: 'Deep Galaxy', description: 'Nebulae, distant worlds, possibility.', preview: 'radial-gradient(ellipse at 60% 30%,#5f3479,#243052 50%,#110e23)' },
] as const
type ThemeId = typeof THEMES[number]['id']
type Motion = 'auto' | 'on' | 'off'
type ThemeContextValue = { theme: ThemeId; motion: Motion; setTheme: (theme: ThemeId) => void; setMotion: (motion: Motion) => void }
const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, changeTheme] = useState<ThemeId>(() => {
    const saved = readStorage('agentverse-theme')
    return THEMES.find(t => t.id === saved)?.id || 'aurora'
  })
  const [motion, changeMotion] = useState<Motion>(() => {
    const saved = readStorage('agentverse-motion')
    return saved === 'on' || saved === 'off' ? saved : 'auto'
  })
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [visible, setVisible] = useState(() => !document.hidden)
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(media.matches)
    const visibility = () => setVisible(!document.hidden)
    media.addEventListener('change', update); document.addEventListener('visibilitychange', visibility)
    return () => { media.removeEventListener('change', update); document.removeEventListener('visibilitychange', visibility) }
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.dataset.motion = motion === 'off' || motion === 'auto' && reduced ? 'off' : visible ? 'on' : 'paused'
  }, [theme, motion, reduced, visible])
  const setTheme = (value: ThemeId) => { changeTheme(value); writeStorage('agentverse-theme', value) }
  const setMotion = (value: Motion) => { changeMotion(value); writeStorage('agentverse-motion', value) }
  return <ThemeContext.Provider value={{ theme, motion, setTheme, setMotion }}><Ambient theme={theme} />{children}</ThemeContext.Provider>
}

function Ambient({ theme }: { theme: ThemeId }) {
  const stars = theme === 'cosmic' || theme === 'deep-galaxy'
  return <div className={`ambient ambient-${theme}`} aria-hidden="true">
    <div className="ambient-glow glow-one" /><div className="ambient-glow glow-two" /><div className="ambient-glow glow-three" />
    {stars && <div className="starfield">{Array.from({ length: 24 }, (_, i) => <i key={i} style={{ left: `${(i * 37 + 9) % 100}%`, top: `${(i * 23 + 7) % 100}%`, '--delay': `${i * -1.7}s`, '--duration': `${8 + i % 7}s` } as CSSProperties} />)}</div>}
    {theme === 'atoms' && <div className="atom-scene"><div className="atom-core" />{[0, 1, 2].map(i => <div className={`atom-plane plane-${i}`} key={i}><div className="atom-orbit"><i /></div></div>)}</div>}
    {theme === 'deep-sea' && <><div className="sea-caustics" /><div className="sea-bubbles">{Array.from({ length: 9 }, (_, i) => <i key={i} style={{ left: `${10 + i * 10}%`, '--delay': `${i * -4}s`, '--duration': `${32 + i * 2}s`, '--size': `${5 + i % 4 * 4}px` } as CSSProperties} />)}</div></>}
    {theme === 'ember' && <div className="ember-particles">{Array.from({ length: 12 }, (_, i) => <i key={i} style={{ left: `${5 + i * 8}%`, '--delay': `${i * -3}s`, '--duration': `${26 + i % 4 * 3}s` } as CSSProperties} />)}</div>}
  </div>
}

export function ThemePicker() {
  const context = useContext(ThemeContext)
  const [open, setOpen] = useState(false)
  if (!context) return null
  return <><button className="theme-button" aria-label="Appearance" title="Themes and background motion" onClick={() => setOpen(true)}><Palette size={16} /><span>{THEMES.find(t => t.id === context.theme)?.name}</span></button>
    {open && <Modal title="A workspace that feels like yours." description="Seven atmospheres. The same clear, focused workspace." close={() => setOpen(false)}>
      <div className="theme-grid">{THEMES.map(theme => <button key={theme.id} className={`theme-option ${theme.id === context.theme ? 'chosen' : ''}`} aria-pressed={theme.id === context.theme} onClick={() => context.setTheme(theme.id)}>
        <span className={`theme-preview preview-${theme.id}`} style={{ background: theme.preview }}>{theme.id === context.theme && <span className="theme-check"><Check size={15} /></span>}</span>
        <strong>{theme.name}</strong><small>{theme.description}</small>
      </button>)}</div>
      <div className="motion-controls"><div><strong>Background motion</strong><p>Subtle, slow animation behind your workspace. Pauses when the tab is hidden.</p></div><div className="motion-options" role="group" aria-label="Background motion">
        <button aria-pressed={context.motion === 'auto'} onClick={() => context.setMotion('auto')}>System</button>
        <button aria-pressed={context.motion === 'on'} onClick={() => context.setMotion('on')}><Play size={12} />On</button>
        <button aria-pressed={context.motion === 'off'} onClick={() => context.setMotion('off')}><Pause size={12} />Off</button>
      </div></div><p className="form-hint">System follows your device’s reduced-motion preference. Reduced motion is always respected. Your choices are saved in this browser.</p>
      <div className="dialog-actions"><button className="button primary" onClick={() => setOpen(false)}><Check size={15} />Done</button></div>
    </Modal>}
  </>
}
