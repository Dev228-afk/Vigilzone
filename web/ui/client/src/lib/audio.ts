/**
 * Audio Utility System for VigilZone
 * Manages the shared AudioContext and handles browser autoplay restrictions.
 */

// Global constant keys for persistence (Future DB migration path)
export const VZ_SETTINGS_KEYS = {
  NOTIFY_SOUND: 'vz_notify_sound',
};

let sharedAudioContext: AudioContext | null = null;

/**
 * Gets or initializes the shared AudioContext.
 */
export function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;

  if (!sharedAudioContext) {
    const AudioContextCtor = window.AudioContext || (window as any).webkitAudioContext;
    if (AudioContextCtor) {
      sharedAudioContext = new AudioContextCtor();
    }
  }
  return sharedAudioContext;
}

/**
 * Resumes the AudioContext if it is suspended.
 * This should be called from a user interaction (click).
 */
export async function unlockAudio(): Promise<void> {
  const ctx = getAudioContext();
  if (ctx && ctx.state === 'suspended') {
    try {
      await ctx.resume();
      console.log('[Audio] Context resumed successfully via user interaction');
    } catch (err) {
      console.error('[Audio] Failed to resume context:', err);
    }
  }
}

/**
 * Plays a high-fidelity notification chime (Modern Ping).
 * Uses a dual-tone frequency with exponential decay.
 */
export function playChime(): void {
  const ctx = getAudioContext();
  if (!ctx || ctx.state !== 'running') return;

  // Check user preference
  const soundEnabled = localStorage.getItem(VZ_SETTINGS_KEYS.NOTIFY_SOUND) !== 'false';
  if (!soundEnabled) return;

  try {
    const now = ctx.currentTime;

    // Create dual oscillators for a richer "chime" sound
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gainNode = ctx.createGain();

    osc1.type = 'sine';
    osc2.type = 'sine';

    // C5 (523.25Hz) and E5 (659.25Hz) create a pleasant major third chime
    osc1.frequency.setValueAtTime(523.25, now);
    osc2.frequency.setValueAtTime(679.25, now);

    // Exponential decay ramp for a natural impact sound
    gainNode.gain.setValueAtTime(0, now);
    gainNode.gain.linearRampToValueAtTime(0.2, now + 0.02); // Quick attack
    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.6); // Smooth decay

    osc1.connect(gainNode);
    osc2.connect(gainNode);
    gainNode.connect(ctx.destination);

    osc1.start(now);
    osc2.start(now);

    osc1.stop(now + 0.7);
    osc2.stop(now + 0.7);
  } catch (err) {
    console.warn('[Audio] Playback failed:', err);
  }
}
