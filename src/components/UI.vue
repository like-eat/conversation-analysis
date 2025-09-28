<template>
  <div class="page-container">
    <div class="upload-container">
      <UploadFile />
    </div>
    <div class="content-container">
      <div class="dialog-container">
        <DialogBox />
      </div>
      <div class="ellipse-graph-container">
        <EllipseUI />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import UploadFile from './UploadFile.vue'
import DialogBox from './DialogBox.vue'
import EllipseUI from './EllipseUI.vue'
</script>

<style>
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
}

.upload-container {
  flex: 0 0 10%; /* 高度占 10% */
  display: flex;
  align-items: center;
  justify-content: center;
}
.content-container {
  flex: 1 1 90%;
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

.ellipse-graph-container {
  flex: 0 0 50%;
  overflow: hidden;
  display: flex;
  justify-content: flex-start; /* 👈 改成左对齐 */
  align-items: flex-start;
}
</style>
