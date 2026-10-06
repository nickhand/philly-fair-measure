import { computed, onMounted, onUnmounted, ref } from 'vue'
import { SITE } from '@/config/site'

const philadelphiaDate = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function todayInPhiladelphia(): string {
  const parts = philadelphiaDate.formatToParts(new Date())
  const part = (type: string) => parts.find((p) => p.type === type)!.value
  return `${part('year')}-${part('month')}-${part('day')}`
}

/** Deadlines remain current through their Philadelphia calendar date, regardless
 * of the visitor's timezone. Check the clock at minute boundaries (including
 * midnight), and on return to a suspended tab, so no reload/build is required. */
export function useAppealDeadlines() {
  // Identical, date-neutral HTML at build time and on the first hydration pass.
  // The actual clock is read only after mounting, never baked into the site.
  const today = ref<string | null>(null)
  const ready = computed(() => today.value !== null)
  let timer: ReturnType<typeof setTimeout> | undefined

  function refresh() {
    clearTimeout(timer)
    today.value = todayInPhiladelphia()
    timer = setTimeout(refresh, 60_000 - (Date.now() % 60_000))
  }

  onMounted(() => {
    refresh()
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
  })
  onUnmounted(() => {
    clearTimeout(timer)
    window.removeEventListener('focus', refresh)
    document.removeEventListener('visibilitychange', refresh)
  })

  const flrPassed = computed(() => today.value !== null && today.value > SITE.flrDeadlineDate)
  const appealPassed = computed(() => today.value !== null && today.value > SITE.appealDeadlineDate)
  const allPassed = computed(() => flrPassed.value && appealPassed.value)

  return { ready, flrPassed, appealPassed, allPassed }
}
