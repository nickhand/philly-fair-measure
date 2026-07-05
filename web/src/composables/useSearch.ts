import { ref, shallowRef } from 'vue'
import { api } from '@/api/client'
import type { SearchHit } from '@/api/types'

const DEBOUNCE_MS = 200
const MIN_CHARS = 2

/** Debounced, abortable address search. Stale responses never land. */
export function useSearch() {
  const hits = shallowRef<SearchHit[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined

  function query(q: string) {
    clearTimeout(timer)
    controller?.abort()
    error.value = null
    // Stale results are cleared IMMEDIATELY (not after the debounce) so a fast
    // typer hitting Enter can never select a match from the previous query.
    hits.value = []
    if (q.trim().length < MIN_CHARS) {
      loading.value = false
      return
    }
    loading.value = true
    timer = setTimeout(async () => {
      controller = new AbortController()
      try {
        hits.value = await api.search(q, controller.signal)
        loading.value = false
      } catch (err) {
        if ((err as Error).name === 'AbortError') return // superseded
        error.value = 'Search is not responding. Please try again.'
        hits.value = []
        loading.value = false
      }
    }, DEBOUNCE_MS)
  }

  function reset() {
    clearTimeout(timer)
    controller?.abort()
    hits.value = []
    loading.value = false
    error.value = null
  }

  return { hits, loading, error, query, reset }
}
