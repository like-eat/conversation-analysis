<template>
  <div class="UI">
    <UI />
    <!-- <TestUI /> -->
  </div>
</template>

<script setup lang="ts">
import UI from './components/UI.vue'
import TestUI from './components/TestUI.vue'
</script>

<style scoped>
.UI {
  width: 100vw;
  height: 100vh;
  overflow: auto;
}
</style>
