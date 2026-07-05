import './assets/main.css'

import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { initAnalytics } from './lib/analytics'

initAnalytics()
createApp(App).use(router).mount('#app')
