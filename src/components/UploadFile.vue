<template>
  <div class="button-container">
    <!-- 隐藏的文件选择 -->
    <input type="file" ref="fileInput" @change="handleFileChange" style="display: none" />

    <!-- 选择文件按钮 -->
    <button class="upload-button" @click="triggerFileSelect">选择文件</button>

    <!-- 上传按钮 -->
    <button
      class="upload-button upload-button--green"
      @click="uploadFile"
      :disabled="!selectedFile"
    >
      上传文件
    </button>

    <!-- 文件名展示 -->
    <p v-if="selectedFile">已选择文件: {{ selectedFile.name }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import axios from 'axios'
import { useFileStore } from '@/stores/FileInfo'

const FileStore = useFileStore()

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)

// 触发文件选择
const triggerFileSelect = () => {
  fileInput.value?.click()
}

// 选择文件后处理
const handleFileChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    selectedFile.value = target.files[0]
  }
}

// 上传文件到后端
const uploadFile = async () => {
  if (!selectedFile.value) return

  const formData = new FormData()
  formData.append('file', selectedFile.value)

  try {
    const response = await axios.post('http://localhost:5000/save_json', formData)
    FileStore.FileContent = response.data
  } catch (error) {
    console.error('发送 JSON 数据失败:', error)
  }
}
</script>

<style scoped>
.button-container {
  margin: 20px;
}

.upload-button {
  background-color: #409eff;
  color: white;
  border: none;
  padding: 8px 16px;
  margin-right: 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: background-color 0.3s ease;
}

.upload-button:hover {
  background-color: #66b1ff;
}

.upload-button--green {
  background-color: #67c23a;
}

.upload-button--green:hover {
  background-color: #85ce61;
}
</style>
