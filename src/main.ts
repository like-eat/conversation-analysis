import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { createRouter, createWebHistory } from 'vue-router'

//配置路由规则
const routes = [{ path: '/', redirect: '/home' }]

//创建路由器
const router = createRouter({
  history: createWebHistory(),
  routes,
})

//加载路由器
const app = createApp(App)
app.use(router)

app.use(createPinia())
app.mount('#app')
