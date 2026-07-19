<template>
  <div class="page-container">
    <div class="content-container">
      <div class="dialog-container">
        <DialogBox :dataset-key="datasetKey" />
      </div>
      <div class="capsule-graph-container">
        <CapsuleUI :dataset-key="datasetKey" @toggle-dataset="toggleDataset" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import DialogBox from './DialogBox.vue'
import CapsuleUI from './CapsuleUI.vue'
import { ref } from 'vue'

type DatasetKey = 'meeting' | 'xinli'
const datasetKey = ref<DatasetKey>('meeting')

function toggleDataset() {
  datasetKey.value = datasetKey.value === 'meeting' ? 'xinli' : 'meeting'
}
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
  min-height: 0; /* 允许 flex 子元素收缩 */
}
.dialog-container {
  flex: 0 0 45%;
  overflow: auto;
  padding: 10px;
  border-right: 1px solid #ddd;
  background: #ffffff;
}

.capsule-graph-container {
  flex: 1 1 auto; /* 自动填充剩余空间 */
  overflow: hidden;
  display: flex;
  justify-content: flex-start;
  align-items: stretch;
  background: #ffffff;
  min-width: 0; /* 允许 flex 收缩 */
}
</style>
