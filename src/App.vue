<template>
  <div class="UI">
    <UI />
    <!-- <TestGraph /> -->
  </div>
</template>

<script setup lang="ts">
import UI from './components/UI.vue'
import TestGraph from './components/TestGraph.vue'
</script>

<style scoped>
.UI {
  width: 100vw;
  height: 100vh;
  overflow: auto;
}
</style>
