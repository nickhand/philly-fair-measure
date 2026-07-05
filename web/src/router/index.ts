import { createRouter, createWebHistory } from 'vue-router'

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
      meta: { title: 'Property report' },
    },
    {
      path: '/map',
      name: 'map',
      component: () => import('@/views/MapView.vue'),
      meta: { title: 'Assessment map' },
    },
    {
      path: '/methodology',
      name: 'methodology',
      component: () => import('@/views/MethodologyView.vue'),
      meta: { title: 'How this works' },
    },
    {
      path: '/trust',
      name: 'trust',
      component: () => import('@/views/TrustView.vue'),
      meta: { title: 'Why trust these numbers' },
    },
    {
      // Staff worklists — intentionally unlinked from public navigation.
      path: '/admin',
      name: 'admin',
      component: () => import('@/views/AdminView.vue'),
      meta: { title: 'Staff' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { title: 'Page not found' },
    },
  ],
  scrollBehavior(_to, _from, saved) {
    return saved ?? { top: 0 }
  },
})

router.afterEach((to) => {
  const title = (to.meta.title as string) ?? 'Fair Measure'
  document.title = to.name === 'home' ? title : `${title} — Fair Measure`
  // Accessibility: move focus to the main heading on route change so screen
  // readers announce the new page.
  requestAnimationFrame(() => {
    const h1 = document.querySelector('main h1') as HTMLElement | null
    h1?.setAttribute('tabindex', '-1')
    h1?.focus({ preventScroll: true })
  })
})

export default router
