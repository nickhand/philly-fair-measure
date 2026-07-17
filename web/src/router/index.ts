import { createRouter, createWebHistory } from 'vue-router'
import stats from '@/data/siteStats.json'
import { trackPageview } from '@/lib/analytics'
import { annualReportNarrative } from '@/utils/annualReportNarrative'

// Crawl-time defaults live in index.html; these keep the head in sync as the
// SPA navigates (Google renders JS — social scrapers only see index.html).
const SITE_URL = 'https://nickhand.dev/fair-measure'
const DEFAULT_DESCRIPTION =
  "A free, independent check of Philadelphia property assessments. Enter your address, see if the city's value looks fair, and get the evidence to appeal."
const ROBOTS_INDEX = 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1'
const annualReport = stats.annual_report
const annualNarrative = annualReportNarrative(annualReport)

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
      meta: { title: 'Fair Measure' },
    },
    {
      path: '/property/:parcelId',
      name: 'property',
      component: () => import('@/views/PropertyView.vue'),
      props: true,
      meta: {
        title: 'Property report',
        description:
          "The city's assessed value next to an independent open-data estimate, with comparable sales, assessment history, and how this home compares to its peers.",
      },
    },
    {
      path: '/map',
      name: 'map',
      component: () => import('@/views/MapView.vue'),
      meta: {
        title: 'Assessment map',
        description:
          "Every Philadelphia home where the city's assessed value falls outside an independent estimate's range, mapped citywide and searchable by address.",
      },
    },
    {
      path: `/reports/ty-${annualReport.tax_year}`,
      alias: '/report',
      name: 'annual-report',
      component: () => import('@/views/AnnualReportView.vue'),
      meta: {
        title: `Tax Year ${annualReport.tax_year} assessment report`,
        description: `${annualNarrative.headline} See how Philadelphia's assessments changed and check your own property.`,
      },
    },
    {
      path: '/findings',
      name: 'findings',
      component: () => import('@/views/FindingsView.vue'),
      meta: {
        title: 'What we found',
        description:
          "What an independent open-data model found in Philadelphia's Tax Year 2027 assessments: where values miss, which neighborhoods bear it, and why it's fixable.",
      },
    },
    {
      path: '/methodology',
      name: 'methodology',
      component: () => import('@/views/MethodologyView.vue'),
      meta: {
        title: 'How this works',
        description:
          'How Fair Measure estimates what Philadelphia homes are worth: the open data behind it, the model, the uncertainty ranges, and when we say a value looks off.',
      },
    },
    {
      path: '/trust',
      name: 'trust',
      component: () => import('@/views/TrustView.vue'),
      meta: {
        title: 'Why trust these numbers',
        description:
          "How Fair Measure's estimates hold up against industry accuracy standards, plus straight answers to the reasons you might not trust a model.",
      },
    },
    {
      path: '/appeal',
      name: 'appeal',
      component: () => import('@/views/AppealView.vue'),
      meta: {
        title: 'Appeal your assessment',
        description:
          'A free, step-by-step guide to challenging your Philadelphia property assessment: check the facts on file, request a First Level Review, and appeal to the Board of Revision of Taxes.',
      },
    },
    {
      // Leaderboards — intentionally unlinked from public navigation; moves
      // behind a real paywall/admin login when the product tier ships.
      path: '/leaderboards',
      alias: '/admin',
      name: 'admin',
      component: () => import('@/views/AdminView.vue'),
      meta: { title: 'Leaderboards', noindex: true },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { title: 'Page not found', noindex: true },
    },
  ],
  scrollBehavior(to, _from, saved) {
    if (saved) return saved
    if (to.hash) return { el: to.hash, top: 16, behavior: 'smooth' }
    return { top: 0 }
  },
})

router.afterEach((to) => {
  const title = (to.meta.title as string) ?? 'Fair Measure'
  document.title = to.name === 'home' ? title : `${title} · Fair Measure`
  document
    .querySelector('meta[name="description"]')
    ?.setAttribute('content', (to.meta.description as string) ?? DEFAULT_DESCRIPTION)
  document.querySelector('link[rel="canonical"]')?.setAttribute('href', `${SITE_URL}${to.path}`)
  document
    .querySelector('meta[name="robots"]')
    ?.setAttribute('content', to.meta.noindex ? 'noindex, nofollow' : ROBOTS_INDEX)
  trackPageview(to.fullPath)
  // Accessibility: move focus to the main heading on route change so screen
  // readers announce the new page.
  requestAnimationFrame(() => {
    const h1 = document.querySelector('main h1') as HTMLElement | null
    h1?.setAttribute('tabindex', '-1')
    h1?.focus({ preventScroll: true })
  })
})

export default router
