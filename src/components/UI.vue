<template>
  <div class="page-container">
    <div class="content-container">
      <div class="dialog-container">
        <DialogBox />
      </div>
      <div class="capsule-graph-container">
        <CapsuleUI />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import DialogBox from './DialogBox.vue'
import CapsuleUI from './CapsuleUI.vue'
</script>

<style>
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
}

.content-container {
  flex: 1 1 100%;
  display: flex;
  flex-direction: row;
  width: 100%;
}
.dialog-container {
  flex: 0 0 50%;
  overflow: auto;
  padding: 10px;
  border-right: 1px solid #ddd;
}

.capsule-graph-container {
  flex: 0 0 50%;
  overflow: hidden;
  display: flex;
  justify-content: flex-start; /* 👈 改成左对齐 */
  align-items: flex-start;
}
</style>
