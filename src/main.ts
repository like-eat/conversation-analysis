import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

//配置路由规则

//创建路由器

//加载路由器

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
