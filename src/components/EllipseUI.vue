<template>
  <div class="svg-container" ref="UIcontainer"></div>
</template>

<script setup lang="ts">
import * as d3 from 'd3'
import { onMounted, ref, watch } from 'vue'
import type { Conversation, Slot } from '@/types/index'
import { useFileStore } from '@/stores/FileInfo'

const FileStore = useFileStore()
const UIcontainer = ref<HTMLElement | null>(null)
const data = [
  [
    {
      domain: 'JSON解析错误',
      slots: [
        { sentence: 'Traceback (most recent call last):', slot: '错误追溯', color: '#B0CFF6' },
        {
          sentence:
            'Traceback (most recent call last): File "c:\\Users\\PC\\Desktop\\code_vis25\\long_conversation\\LLM-long_conversation\\py\\LLM_Extraction.py", line 96, in result = llm_extract_information(content) ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ File "c:\\Users\\PC\\Desktop\\code_vis25\\long_conversation\\LLM-long_conversation\\py\\LLM_Extraction.py", line 64, in llm_extract_information result = json.loads(completion.choices[0].message.content) ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ File "D:\\conda\\envs\\longconversion_env\\Lib\\json_init_.py", line 346, in loads return _default_decoder.decode(s) ^^^^^^^^^^^^^^^^^^^^^^^^^^ File "D:\\conda\\envs\\longconversion_env\\Lib\\json\\decoder.py", line 338, in decode obj, end = self.raw_decode(s, idx=_w(s, 0).end()) ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ File "D:\\conda\\envs\\longconversion_env\\Lib\\json\\decoder.py", line 356, in raw_decode raise JSONDecodeError("Expecting value", s, err.value) from None json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)',
          slot: '代码路径',
          color: '#B0CFF6',
        },
      ],
      color: '#1E77E8',
    },
  ],
  [
    {
      domain: '对话抽取',
      slots: [
        {
          sentence: '你帮我把上面那段模拟对话的轮数取 消，然后重新生成一边，像是正常的对话',
          slot: '轮数修改',
          color: '#FFC9A9',
        },
        { sentence: '你帮我把主题和任务抽取一下，说明轮数', slot: '主题抽取', color: '#FFC9A9' },
        {
          sentence: ' 这段对话传入到小模型（主题模型）当中会将对话的主题抽取出来吗',
          slot: '小模型应用',
          color: '#FFC9A9',
        },
        {
          sentence: '我现在不是抽取问题，而是抽取对话的主题和子主题',
          slot: '子主题抽取',
          color: '#FFC9A9',
        },
        { sentence: '好像有个新项目要讨论。', slot: '新项目', color: '#FFC9A9' },
        {
          sentence:
            '我有一段长对话，我想将这段对话当中的主题给抽取出来，同时将对话当中的无关紧要的句子给过滤掉，有什么办法',
          slot: '主题过滤',
          color: '#FFC9A9',
        },
      ],
      color: '#FF660C',
    },
    {
      domain: '主题模型',
      slots: [
        {
          sentence: '这段对话传入到小模型（主题模型）当中会将对话的主题抽取出来吗',
          slot: '模型功能',
          color: '#B4E6B4',
        },
        { sentence: '主题模型有哪些', slot: '模型种类', color: '#B4E6B4' },
      ],
      color: '#2BBA2B',
    },
    {
      domain: '话题讨论',
      slots: [
        { sentence: '你觉得人们日常会聊哪些话题呢', slot: '日常话题', color: '#F9B3B3' },
        { sentence: '能不能给我个例子，以生活和工作为大主题', slot: '主题例子', color: '#F9B3B3' },
        {
          sentence: '但有的时候-1的噪音类并不是没有用处的，例如聊到天气怎么样其实也算生活类的对话',
          slot: '噪音用途',
          color: '#F9B3B3',
        },
      ],
      color: '#EF2628',
    },
    {
      domain: '主题修改',
      slots: [
        {
          sentence: '你觉得读研和学业这两个主题是不是有点接近，能不能把读研换一个别的话题',
          slot: '主题替换',
          color: '#D9C9F0',
        },
      ],
      color: '#9366D6',
    },
  ],
  [
    {
      domain: 'DST应用',
      slots: [
        { sentence: 'DST是 什么', slot: 'DST定义', color: '#D6C3BF' },
        { sentence: 'DST可以和LLM结合起来吗', slot: 'DST与LLM结合', color: '#D6C3BF' },
        { sentence: 'DST格式是什么', slot: 'DST格式定义', color: '#D6C3BF' },
        {
          sentence: 'DST格式类似于树结构吗，domain是父节点，每个slot是一个子节点',
          slot: '格式结构',
          color: '#D6C3BF',
        },
        { sentence: '大模型输出给DST的内容是什么', slot: '输 入内容', color: '#D6C3BF' },
        {
          sentence: '所以LLM输出给DST的内容就已经是DST格式的了吗？',
          slot: '内容格式化',
          color: '#D6C3BF',
        },
        { sentence: '这些主题能转换成DST格式吗，', slot: ' 主题转换', color: '#D6C3BF' },
        { sentence: '现在将对话的主题给我转换成DST格式', slot: '主题转换请求', color: '#D6C3BF' },
        { sentence: '介绍一下什么是DST', slot: 'DST定义', color: '#D6C3BF' },
        { sentence: '介绍一下DST格式是什么', slot: 'DST格式定义', color: '#D6C3BF' },
        {
          sentence: '我可以将输出结果为DST格式添加到prompt里面吗',
          slot: '格式应用',
          color: '#D6C3BF',
        },
        {
          sentence: '我输出的DST格式想修改一下，这样输出可以吗：',
          slot: '格式修改',
          color: '#D6C3BF',
        },
      ],
      color: '#8C5649',
    },
  ],
  [
    {
      domain: '数据返回',
      slots: [
        { sentence: '这个返回的result是什么样的', slot: 'result格式', color: '#F4CFE9' },
        { sentence: '我设定的返回格式是：', slot: '格式设定', color: '#F4CFE9' },
        { sentence: '你还记得我的LLM抽取出来的结果吗：', slot: 'LLM结果', color: '#F4CFE9' },
        {
          sentence: '这个后端大模型抽取出来的result怎么返回前端呢',
          slot: '大模型结果',
          color: '#F4CFE9',
        },
        {
          sentence: '我最终返回的结果是这样的，backendData的newVal：',
          slot: '最终结果',
          color: '#F4CFE9',
        },
      ],
      color: '#E277C1',
    },
    {
      domain: '前后端数据传输',
      slots: [
        { sentence: '这是我的前端往后端传入数据的部分：', slot: '传入数据', color: '#D1D1D1' },
        {
          sentence:
            '其实我的数据是写在后端的，我只想将后端运行的结果传给前端，现在不需要前端传给后端数据',
          slot: '数据传输方向',
          color: '#D1D1D1',
        },
        {
          sentence: '我现 在data从后端输入，那我前端在哪里接收呢',
          slot: '前端接收',
          color: '#D1D1D1',
        },
        { sentence: "console.log('后端返回数据:', data)", slot: '数据接收输出', color: '#D1D1D1' },
        {
          sentence:
            '为什么我后端返回了正确的结果，但是前端却没有渲染出来，是不是要添加一个watch来监听后端数据',
          slot: '数据监听',
          color: '#D1D1D1',
        },
      ],
      color: '#7C7C7C',
    },
  ],
  [
    {
      domain: '椭圆图形操作',
      slots: [
        { sentence: '可动态生成多个椭圆且支持滚轮缩放', slot: '动态生成', color: '#E7E7B1' },
        {
          sentence:
            '我能实现一个大椭圆里面套一个小椭圆的效果吗，意思就算说当我对大椭圆放大的时候 ，就可以看到大椭圆当中的小椭圆',
          slot: '大椭圆缩放',
          color: '#E7E7B1',
        },
        {
          sentence: '在大椭圆里放多个小椭圆，实现“嵌套层级可视化”',
          slot: '嵌套层级',
          color: '#E7E7B1',
        },
        {
          sentence:
            '每个椭圆的大小我并不想让他设置成一样大，而是根据slots里面的数量来决定大小，例如默认大椭圆为cx50，cy30，如果slots有两个slot，就设置为1.2倍，如果有三个就设置为1.4倍，具体是1+0.2*（x-1），x是slots里面的数量',
          slot: '大小设置',
          color: '#E7E7B1',
        },
        {
          sentence: '小椭圆大小是一定的，我控制的是大椭圆的大小',
          slot: '小椭圆固定',
          color: '#E7E7B1',
        },
        {
          sentence: '现在小椭圆在大椭圆里面的分布是怎么设置的',
          slot: '分布设置',
          color: '#E7E7B1',
        },
        { sentence: '大椭圆悬浮效果这个能够实现吗？', slot: '悬浮效果', color: '#E7E7B1' },
        {
          sentence: '小椭圆的宽度可 以自己设定吗，根据大椭圆的宽度来',
          slot: '宽度设定',
          color: '#E7E7B1',
        },
        {
          sentence: '宽度不应该是一半，比如有的大椭圆里面有三个小椭圆，有的有两个',
          slot: '比例问题',
          color: '#E7E7B1',
        },
        { sentence: '缩放时文字大小自适应怎么设置', slot: '文字自适应', color: '#E7E7B1' },
      ],
      color: '#BCBC21',
    },
  ],
  [
    {
      domain: '输出问题',
      slots: [
        { sentence: '输出是这个：', slot: ' 当前输出', color: '#ADE8ED' },
        { sentence: '现在输出是这样的：', slot: '当前输出', color: '#ADE8ED' },
        { sentence: '只输出了这个：', slot: '当前输出', color: '#ADE8ED' },
        { sentence: '这个输出示例是不是有问题：', slot: '输出示例问题', color: '#ADE8ED' },
      ],
      color: '#16BFCE',
    },
    {
      domain: '代码问题',
      slots: [{ sentence: '下面代码有错误吗', slot: '代码错误检查', color: '#C5B7E4' }],
      color: '#5B33B2',
    },
    {
      domain: 'factor区别',
      slots: [{ sentence: 'factor高低的区别是什么', slot: 'factor高低区别', color: '#FAEAAB' }],
      color: '#F2C40F',
    },
  ],
  [
    {
      domain: '颜色设置问题',
      slots: [
        {
          sentence: '还是不对，我通过debug发现是小椭圆颜色设置的问题',
          slot: '小椭圆颜色',
          color: '#AEDBD2',
        },
        { sentence: '我抽取出来给他加颜色：', slot: '加颜色方法', color: '#AEDBD2' },
        { sentence: '这里怎么添加颜色：', slot: '颜色添加方法', color: '#AEDBD2' },
      ],
      color: '#19997F',
    },
    {
      domain: '代码实现',
      slots: [
        {
          sentence:
            'File "c:\\Users\\PC\\Desktop\\code_vis25\\long_conversation\\LLM-long_conversation\\py\\test.py", line 58, in colored_results = assign_colors(results)',
          slot: '代码行位置',
          color: '#EDBBD2',
        },
        { sentence: '这是我的输出结果，里面本身不含color', slot: '输出结果内容', color: '#EDBBD2' },
        {
          sentence: '当我这样写的时候就没有报错：color_palette = plt.cm.tab10.colors',
          slot: '解决报错方法',
          color: '#EDBBD2',
        },
        {
          sentence: '我想自己定义一个color_palette，不再使用：',
          slot: '自定义调色板',
          color: '#EDBBD2',
        },
        {
          sentence: 'def lighten_color(color, factor=0.75):',
          slot: '颜色函数定义',
          color: '#EDBBD2',
        },
        { sentence: 'color_palette = [', slot: '调色板代码', color: '#EDBBD2' },
      ],
      color: '#CC3F7F',
    },
  ],
  [
    {
      domain: '鼠标滚轮缩放',
      slots: [
        { sentence: '我不需要按钮，我是通过鼠标滚轮实现放大', slot: '实现放大', color: '#E4E4E4' },
        { sentence: '这是一个鼠标滚轮缩放的事件吗', slot: '缩放事件', color: '#E4E4E4' },
      ],
      color: '#B2B2B2',
    },
    {
      domain: '小椭圆显示',
      slots: [
        {
          sentence: '就是一开始小椭圆是不显示的，在放大1.25倍之后，小椭圆才出现',
          slot: '显示问题',
          color: '#C0C0C0',
        },
        { sentence: '加上小椭圆渐现动画', slot: '渐现动画', color: '#C0C0C0' },
        {
          sentence: '我的小椭圆的位置信息正确保存下来了，但是我放大的时候并没有出现',
          slot: '位置信息',
          color: '#C0C0C0',
        },
        { sentence: ' 为啥放大不显示小椭圆：', slot: '放大不显示', color: '#C0C0C0' },
        { sentence: '只有一个小椭圆的时候我想让它居中显示', slot: '居中显示', color: '#C0C0C0' },
        { sentence: '小椭圆我也想 放在中心显示：', slot: '中心显示', color: '#C0C0C0' },
      ],
      color: '#4C4C4C',
    },
  ],
  [
    {
      domain: '数据可视化设计',
      slots: [
        {
          sentence: '我想让大椭圆表示domain，小椭圆表示slot，tooltip小椭圆 时显示sentence的内容',
          slot: '设计需求',
          color: '#B7D2F5',
        },
        { sentence: '我想让他按照一行分布在大椭圆里面', slot: '布局方式', color: '#B7D2F5' },
        {
          sentence:
            '我想增加一个判断，当 只有一个小椭圆的时候，我固定小椭圆大小，当有多个小椭圆的时候，再按照下面的方法来',
          slot: '形状大小调整',
          color: '#B7D2F5',
        },
        {
          sentence: '我现在的大椭圆是在X轴分布，我想让他按照Y轴分布',
          slot: '轴向布局',
          color: '#B7D2F5',
        },
      ],
      color: '#337FE5',
    },
    {
      domain: '算法与模型',
      slots: [
        {
          sentence: '但是其实BERTopic抽出的主题簇还可以细分成更小的簇，LLM可以做到这些吗',
          slot: '主题细分',
          color: '#F5D6AE',
        },
      ],
      color: '#E58C19',
    },
    {
      domain: '计数器与矩形',
      slots: [
        {
          sentence: '我想设置一个计数器，根据我输入的个数来创建矩形',
          slot: '计数器功能',
          color: '#C9E8BB',
        },
      ],
      color: '#66BF3F',
    },
  ],
  [
    {
      domain: 'BERTopic',
      slots: [
        { sentence: '我需要BERTopic', slot: '需求', color: '#EDAEC0' },
        { sentence: '那我该怎么调用bertopic呢', slot: '调用方法', color: '#EDAEC0' },
        { sentence: '介绍一下BERTopic', slot: '基本介绍', color: '#EDAEC0' },
      ],
      color: '#CC194C',
    },
    {
      domain: '设计流程',
      slots: [{ sentence: '你现在了解我的设计流程了吗', slot: '了解情况', color: '#B0CFF6' }],
      color: '#1E77E8',
    },
    {
      domain: '技术路线',
      slots: [
        { sentence: '我的目标是这个：', slot: '目标', color: '#FFC9A9' },
        { sentence: '这是我的一个整体技术路线：', slot: '整体路线', color: '#FFC9A9' },
      ],
      color: '#FF660C',
    },
    {
      domain: 'Flask',
      slots: [{ sentence: '我想用flask', slot: '使用计划', color: '#B4E6B4' }],
      color: '#2BBA2B',
    },
  ],
  [
    {
      domain: '对话处理',
      slots: [
        {
          sentence:
            '现在我的想法是：将用户的对话的输入先输入到BERTopic中，然后将BERTopic的输出再输出给LLM，最后用后端输出结果',
          slot: '输入流程',
          color: '#F9B3B3',
        },
        {
          sentence:
            '现在我的想法是：将用户的对话的输入先输入到BERTopic中，然后将BERTopic的输出再输出给LLM，最后从后端输出到前端，下面我分别给你代码部分',
          slot: '前后端输出',
          color: '#F9B3B3',
        },
        {
          sentence: '这是后端接收，同时输入到LLM，我是想输入到BERTopic中：',
          slot: '后端接收',
          color: '#F9B3B3',
        },
      ],
      color: '#EF2628',
    },
    {
      domain: 'BERTopic使用',
      slots: [
        {
          sentence: '我想把BERTopic的代码写成一个def bertopic_extraction_information',
          slot: '代码实现',
          color: '#D9C9F0',
        },
      ],
      color: '#9366D6',
    },
    {
      domain: 'LLM调用',
      slots: [
        { sentence: '第三个路由 调用LLM抽取问题', slot: '抽取问题', color: '#D6C3BF' },
        {
          sentence: '我想使用方法3，你能帮我修改一下我的prompt吗',
          slot: '修改prompt',
          color: '#D6C3BF',
        },
      ],
      color: '#8C5649',
    },
  ],
  [
    {
      domain: '虚拟环境管理',
      slots: [
        { sentence: 'anconda怎么创建一个虚拟环境', slot: '创建环境', color: '#F4CFE9' },
        {
          sentence: '我创建好了这个虚拟环境， 我怎么在VScode里面使用呢',
          slot: '在VScode使用',
          color: '#F4CFE9',
        },
        { sentence: '我想删除conda里面的虚拟环境', slot: '删除环境', color: '#F4CFE9' },
        {
          sentence: '我需要创建一个虚拟环境吗，不能直接使用base吗',
          slot: '是否需创建',
          color: '#F4CFE9',
        },
      ],
      color: '#E277C1',
    },
    {
      domain: 'API使用',
      slots: [{ sentence: 'Openai调用API的代码是哪些', slot: 'OpenAI API调用', color: '#D1D1D1' }],
      color: '#7C7C7C',
    },
  ],
  [
    {
      domain: '日常生活',
      slots: [
        { sentence: '朋友请我去吃日料', slot: '吃日料', color: '#E7E7B1' },
        { sentence: '每天早上坚持做瑜伽', slot: '做瑜伽', color: '#E7E7B1' },
        { sentence: '最近咖啡喝太多了', slot: '喝咖啡', color: '#E7E7B1' },
        { sentence: '昨天去健身房举铁', slot: '健身举铁', color: '#E7E7B1' },
        { sentence: '打排球的时候扭伤了手腕', slot: '打排球', color: '#E7E7B1' },
        { sentence: '最近在学打羽毛球', slot: '学打羽毛球', color: '#E7E7B1' },
        { sentence: '我昨天吃了火锅', slot: '吃火锅', color: '#E7E7B1' },
        { sentence: '我准备周末去游泳', slot: '去游泳', color: '#E7E7B1' },
        { sentence: '周末打算去逛街', slot: '去逛街', color: '#E7E7B1' },
        { sentence: ' 天气真好', slot: '天气', color: '#E7E7B1' },
      ],
      color: '#BCBC21',
    },
    {
      domain: '编程与技术',
      slots: [
        { sentence: 'python', slot: 'Python编程', color: '#ADE8ED' },
        { sentence: 'notebook', slot: 'Notebook使用', color: '#ADE8ED' },
        { sentence: 'jupyter', slot: 'Jupyter使用', color: '#ADE8ED' },
        { sentence: 'means', slot: 'Means算法', color: '#ADE8ED' },
        { sentence: 'pandas', slot: 'Pandas库', color: '#ADE8ED' },
        { sentence: '支持向量机可以做文本分类吗', slot: '支持向量机', color: '#ADE8ED' },
        { sentence: '我想学习', slot: '学习意愿', color: '#ADE8ED' },
        { sentence: '怎么安装', slot: '软件安装', color: '#ADE8ED' },
        { sentence: '快速排序适合处理大数据吗', slot: '快速排序', color: '#ADE8ED' },
        { sentence: '如何 用', slot: '使用方法', color: '#ADE8ED' },
      ],
      color: '#16BFCE',
    },
    {
      domain: '技术问题',
      slots: [
        { sentence: '无法解析导入“jieba”', slot: 'Jieba问题', color: '#C5B7E4' },
        { sentence: '为啥字体没显示：', slot: '字体问题', color: '#C5B7E4' },
      ],
      color: '#5B33B2',
    },
  ],
  [
    {
      domain: '椭圆颜色设置',
      slots: [
        { sentence: '这样，我每个椭圆的颜色我想设置一下', slot: '颜色设置', color: '#FAEAAB' },
        {
          sentence: '我在data里面存储每个大椭圆和小椭圆对应的颜色，创建椭圆的时候直接使用',
          slot: '颜色存储',
          color: '#FAEAAB',
        },
        {
          sentence: '我现在把小椭圆的颜色 也输入到data里面了：',
          slot: '小椭圆颜色',
          color: '#FAEAAB',
        },
      ],
      color: '#F2C40F',
    },
    {
      domain: '颜色色系生成',
      slots: [
        { sentence: '给我生成十个颜色色系和对应的浅色色系', slot: '生成色系', color: '#AEDBD2' },
        { sentence: '最多只有10个颜色循环吗', slot: '颜色循环限制', color: '#AEDBD2' },
      ],
      color: '#19997F',
    },
  ],
  [
    {
      domain: '论文问题',
      slots: [{ sentence: '论文当中的pipeline代表什么', slot: 'pipeline含义', color: '#EDBBD2' }],
      color: '#CC3F7F',
    },
    {
      domain: 'pip安装',
      slots: [
        {
          sentence: 'Requirement already satisfied: pip in d:\\anaconda\\lib\\site-packages (25.2)',
          slot: 'pip已安装',
          color: '#E4E4E4',
        },
      ],
      color: '#B2B2B2',
    },
    {
      domain: 'pip错误',
      slots: [
        {
          sentence: 'pip : 无法将“pip”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请',
          slot: '命令无法识别',
          color: '#C0C0C0',
        },
        {
          sentence: 'pip : 无法将“pip”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请',
          slot: '命令无法识别',
          color: '#C0C0C0',
        },
        { sentence: '我想在PATH里面加入pip', slot: 'PATH设置', color: '#C0C0C0' },
      ],
      color: '#4C4C4C',
    },
  ],
  [
    {
      domain: '子模型使用',
      slots: [
        {
          sentence: '如果我是想对长对话当中的关键信息抽取，子模型在哪里使用会比较好',
          slot: '关键信息抽取',
          color: '#B7D2F5',
        },
        {
          sentence: '给我个例子，说明子模型是如何筛选的，一个长对话的例子',
          slot: '筛选例子',
          color: '#B7D2F5',
        },
        {
          sentence: '小模型其实并没有将关键的具体信息或者任务抽取出来，只是处理了无关紧要的对话吗',
          slot: '处理效果',
          color: '#B7D2F5',
        },
      ],
      color: '#337FE5',
    },
    {
      domain: 'API模型记忆',
      slots: [{ sentence: '调用API模型不会记得之前的对话吗', slot: '对话记忆', color: '#F5D6AE' }],
      color: '#E58C19',
    },
    {
      domain: '对话分析需求',
      slots: [
        {
          sentence: '对的，其实我只需要 分析user的对话就好了',
          slot: '用户对话分析',
          color: '#C9E8BB',
        },
      ],
      color: '#66BF3F',
    },
  ],
  [
    {
      domain: '长对话分析',
      slots: [
        { sentence: '对话状态跟踪可以应用到长对话分析中吗', slot: '状态跟踪', color: '#EDAEC0' },
        { sentence: '长对话在会议记录当中有什么作用', slot: '会议记录', color: '#EDAEC0' },
        {
          sentence:
            '“长对话是指由多轮、多阶段交互组成的对话形式。目前，长对话广泛应用于多个场景，包括 AI 聊天助手、在线客服、会议记录、医患交流 等。然而长对话信息量大，关键信息容易淹没，上下文切换开销大。 例如，当我和大模型聊了一整天，形成了这么长的对话，我很难…… 如果能够对长对话进行梳理，我们就能……。”',
          slot: '应用场景',
          color: '#EDAEC0',
        },
      ],
      color: '#CC194C',
    },
    {
      domain: '主题抽取',
      slots: [
        {
          sentence: 'NLP领域有哪些从长文本对话中抽取主题的论文呢',
          slot: '相关论文',
          color: '#B0CFF6',
        },
        {
          sentence: '从长对话中抽取主题的这个流程经过了哪些发展过程',
          slot: '发展过程',
          color: '#B0CFF6',
        },
      ],
      color: '#1E77E8',
    },
  ],
  [
    {
      domain: '错误信息分析',
      slots: [
        {
          sentence:
            'ValueError: numpy.dtype size changed, may indicate binary incompatibility. Expected 96 from C header, got 88 from PyObject',
          slot: 'numpy错误',
          color: '#FFC9A9',
        },
        {
          sentence:
            '属性“slots”在类型“{ x: number; y: number; sentence: string; slot: string; }”上不存在。你是否指的是“slot”?',
          slot: '属性错误',
          color: '#FFC9A9',
        },
        {
          sentence:
            "我在进行.attr('fill', domainData.color)时，类型“string | undefined”的参数不能赋给类型“string | number | boolean | readonly (string | number)[] | ValueFn<SVGEllipseElement, unknown, string | number | boolean | readonly (string | number)[] | null> | null”的参数。",
          slot: '类型不兼容',
          color: '#FFC9A9',
        },
        {
          sentence:
            "Uncaught (in promise) TypeError: Cannot read properties of undefined (reading 'length')",
          slot: '未捕获错误',
          color: '#FFC9A9',
        },
        { sentence: 'TypeError: data.flat is not a function', slot: '类型错误', color: '#FFC9A9' },
      ],
      color: '#FF660C',
    },
  ],
  [
    {
      domain: 'BERTopic功能',
      slots: [
        {
          sentence: 'BERTopic能将一段对话当中的主题抽取出来吗',
          slot: '主题抽取',
          color: '#B4E6B4',
        },
        {
          sentence: 'BERTopic能够将对话当中的无 关紧要的句子给过滤掉吗',
          slot: '过滤功能',
          color: '#B4E6B4',
        },
      ],
      color: '#2BBA2B',
    },
    {
      domain: '关键词抽取',
      slots: [
        { sentence: 'BERTopic的关键词抽取是怎么抽取的', slot: '抽取方法', color: '#F9B3B3' },
        {
          sentence: '所以，BERTopic抽取出来的关键词，一定是在句子当中出现过的词吗',
          slot: '关键词限制',
          color: '#F9B3B3',
        },
      ],
      color: '#EF2628',
    },
    {
      domain: '主题命名',
      slots: [
        {
          sentence:
            'BERTopic做预处理，按语义聚类，但是他不会给出这个主题的名字，后续还要大模型重新去判断主题的名字',
          slot: '命名依赖',
          color: '#D9C9F0',
        },
      ],
      color: '#9366D6',
    },
  ],
  [
    {
      domain: 'Miniconda安装',
      slots: [
        { sentence: '我准备下载一个py3.12的miniconda', slot: '安装准备', color: '#D6C3BF' },
        { sentence: '我添加在D:\\conda里面的路径', slot: '路径设置', color: '#D6C3BF' },
        { sentence: 'conda --version', slot: '版本检查', color: '#D6C3BF' },
        {
          sentence: 'usage: conda-script.py [-h] [-v] [--no-plugins] [-V] COMMAND ...',
          slot: '使用说明',
          color: '#D6C3BF',
        },
        { sentence: 'conda activate longconversion_env', slot: '环境激活', color: '#D6C3BF' },
      ],
      color: '#8C5649',
    },
  ],
  [
    {
      domain: 'Anaconda环境管理',
      slots: [
        {
          sentence: '我想在anaconda里面创建一个python3.11的环境',
          slot: '创建环境',
          color: '#F4CFE9',
        },
        { sentence: '我想卸载anaconda和python环境，重新下载', slot: '环境卸载', color: '#F4CFE9' },
      ],
      color: '#E277C1',
    },
    {
      domain: 'VSCode设置',
      slots: [
        { sentence: 'vscode里面怎么更换python解释器', slot: '更换解释器', color: '#D1D1D1' },
        {
          sentence: '我更换了解释器，但是为什么查看python版本的时候还是旧版本',
          slot: '版本问题',
          color: '#D1D1D1',
        },
      ],
      color: '#7C7C7C',
    },
    {
      domain: 'Python版本',
      slots: [
        {
          sentence: '我没有使用虚拟环境，我使用的是python3.9.12，可以使用吗',
          slot: '旧版本使用',
          color: '#E7E7B1',
        },
      ],
      color: '#BCBC21',
    },
  ],
  [
    {
      domain: '旅行计划',
      slots: [{ sentence: '昨天没休息够，好像去爬山。', slot: '爬山意愿', color: '#ADE8ED' }],
      color: '#16BFCE',
    },
    {
      domain: '技术介绍',
      slots: [{ sentence: '介绍一下FAISS', slot: 'FAISS介绍', color: '#C5B7E4' }],
      color: '#5B33B2',
    },
  ],
  [
    {
      domain: '模块导入错误',
      slots: [
        {
          sentence: "ModuleNotFoundError: No module named 'bertopic'",
          slot: 'bertopic模块缺失',
          color: '#FAEAAB',
        },
        {
          sentence:
            "ImportError: cannot import name 'HDBSCAN' from 'sklearn.cluster' (D:\\anaconda\\lib\\site-packages\\sklearn\\cluster_init_.py)",
          slot: 'HDBSCAN导入失败',
          color: '#FAEAAB',
        },
        {
          sentence: 'ImportError: numpy.core.multiarray failed to import',
          slot: 'numpy导入失败',
          color: '#FAEAAB',
        },
      ],
      color: '#F2C40F',
    },
    {
      domain: '依赖版本问题',
      slots: [
        {
          sentence:
            'ERROR: Could not find a version that satisfies the requirement scipy==1.10.1 (from versions: none)',
          slot: 'scipy版本不兼容',
          color: '#AEDBD2',
        },
      ],
      color: '#19997F',
    },
    {
      domain: 'API路由',
      slots: [
        {
          sentence: "@app.route('/extract_question', methods=['POST'])",
          slot: 'API路由设置',
          color: '#EDBBD2',
        },
      ],
      color: '#CC3F7F',
    },
  ],
  [
    {
      domain: '领域检测',
      slots: [{ sentence: '帮我改成自动检测domain', slot: '自动检测', color: '#E4E4E4' }],
      color: '#B2B2B2',
    },
    {
      domain: '数据库检索',
      slots: [
        {
          sentence: '去哪个数据库检索呢，是我自己生成的数据库吗',
          slot: '检索数据库',
          color: '#C0C0C0',
        },
      ],
      color: '#4C4C4C',
    },
  ],
  [
    {
      domain: '表达方式',
      slots: [
        { sentence: '应为声明或语句', slot: '语句形式', color: '#B7D2F5' },
        { sentence: '这样写是对的吗', slot: '正确写法', color: '#B7D2F5' },
      ],
      color: '#337FE5',
    },
    {
      domain: '错误处理',
      slots: [{ sentence: '这一步出错了：', slot: '出错原因', color: '#F5D6AE' }],
      color: '#E58C19',
    },
    {
      domain: '非语言表达',
      slots: [{ sentence: '为什么要加这个表情😅', slot: '表情使用', color: '#C9E8BB' }],
      color: '#66BF3F',
    },
  ],
  [
    {
      domain: '子模型与LLM配合',
      slots: [
        {
          sentence: '我可以使用一些子模型与LLM相配合吗，例如主题提取，任务识别这种子模型',
          slot: '子模型使用',
          color: '#EDAEC0',
        },
        {
          sentence: '这个例子中，子模型输入到LLM当中的内容是什么',
          slot: '子模型输入内容',
          color: '#EDAEC0',
        },
        {
          sentence:
            '那我将小模型抽取出的结果传入到LLM当中，让其将对话中的关键信息抽取出来，LLM会抽出来什么',
          slot: '关键信息抽取',
          color: '#EDAEC0',
        },
        {
          sentence:
            '那我现在想将小模型的结果输入到LLM当中进行一个抽取，然后将最后抽取出来的结果再返回前端',
          slot: '结果处理与传递',
          color: '#EDAEC0',
        },
      ],
      color: '#CC194C',
    },
  ],
  [
    {
      domain: '大模型功能',
      slots: [
        { sentence: '大模型有记忆裁剪的功能吗', slot: '记忆裁剪', color: '#B0CFF6' },
        { sentence: '大模型API有遗忘功能吗', slot: '遗忘功能', color: '#B0CFF6' },
      ],
      color: '#1E77E8',
    },
    {
      domain: '技术概念',
      slots: [
        {
          sentence: 'RAG (Retrieval-Augmented Generation)是什么',
          slot: 'RAG介绍',
          color: '#FFC9A9',
        },
      ],
      color: '#FF660C',
    },
  ],
  [
    {
      domain: '编程代码',
      slots: [
        {
          sentence: 'const container = ref<HTMLElement | null>(null)',
          slot: '容器定义',
          color: '#B4E6B4',
        },
        { sentence: 'const data = [', slot: '数据初始化', color: '#B4E6B4' },
        {
          sentence: 'const backendData = ref<Conversation[]>([]) //  后端数据',
          slot: '后端存储',
          color: '#B4E6B4',
        },
        {
          sentence: 'const ellipsesData = data.map((domainData) => {',
          slot: '数据映射',
          color: '#B4E6B4',
        },
      ],
      color: '#2BBA2B',
    },
  ],
  [
    {
      domain: '排序算法',
      slots: [
        { sentence: '排序算法有哪些，快速排序适用于什么场景', slot: '快速排序', color: '#F9B3B3' },
      ],
      color: '#EF2628',
    },
    {
      domain: '聚类算法',
      slots: [
        { sentence: '聚类算法有哪些', slot: '算法种类', color: '#D9C9F0' },
        { sentence: '写一个K-means算法代码', slot: 'K-means代码', color: '#D9C9F0' },
        { sentence: '如何将K-means算法效果呈现出来', slot: '效果呈现', color: '#D9C9F0' },
      ],
      color: '#9366D6',
    },
    {
      domain: 'vegalite',
      slots: [
        { sentence: 'vgealite是前端可视化库吗', slot: '库介绍', color: '#D6C3BF' },
        { sentence: ' 用vegalite写一个条形图', slot: '条形图', color: '#D6C3BF' },
      ],
      color: '#8C5649',
    },
    {
      domain: '长对话分析',
      slots: [
        { sentence: '长对话分析方法有哪些', slot: '分析方法', color: '#F4CFE9' },
        { sentence: 'DST可以用于长对话分析吗', slot: 'DST应用', color: '#F4CFE9' },
        { sentence: '长对话分析可以与可视化结合在一起吗', slot: '可视化结合', color: '#F4CFE9' },
      ],
      color: '#E277C1',
    },
  ],
  [
    {
      domain: '函数使用',
      slots: [
        { sentence: '我不能定义成一个函数吗？', slot: '函数定义', color: '#D1D1D1' },
        { sentence: '这个函数不是可以生成椭圆吗？', slot: ' 椭圆生成', color: '#D1D1D1' },
      ],
      color: '#7C7C7C',
    },
    {
      domain: 'UI绘制',
      slots: [
        { sentence: 'function drawUI() {', slot: 'UI绘制', color: '#E7E7B1' },
        { sentence: 'function drawUI() {', slot: 'UI绘制', color: '#E7E7B1' },
      ],
      color: '#BCBC21',
    },
  ],
  [
    {
      domain: '使用Conda',
      slots: [
        {
          sentence:
            "CommandNotFoundError: Your shell has not been properly configured to use 'conda activate'.",
          slot: '配置错误',
          color: '#ADE8ED',
        },
      ],
      color: '#16BFCE',
    },
    {
      domain: '文件访问问题',
      slots: [
        {
          sentence: '另一个程序正在使用此文件，进程无法访问。',
          slot: ' 访问受阻',
          color: '#C5B7E4',
        },
      ],
      color: '#5B33B2',
    },
    {
      domain: '加载资源失败',
      slots: [
        {
          sentence: 'Failed to load resource: the server responded with a status of 405',
          slot: '状态码405',
          color: '#FAEAAB',
        },
        {
          sentence: 'Failed to load resource: the server responded with a status of 500',
          slot: '状态码500',
          color: '#FAEAAB',
        },
      ],
      color: '#F2C40F',
    },
  ],
  [
    {
      domain: ' 大模型',
      slots: [
        { sentence: '大模型会输出什么', slot: '模型输出', color: '#AEDBD2' },
        { sentence: '小模型怎么和大模型进行结合', slot: '模型结合', color: '#AEDBD2' },
        {
          sentence: '我可以用大模型的prompt实现小模型＋大模型的效果吗',
          slot: '结合效果',
          color: '#AEDBD2',
        },
      ],
      color: '#19997F',
    },
  ],
  [
    {
      domain: '模型使用',
      slots: [
        {
          sentence: '如果我的方法使用了LLM和 子模型还有DST，那整个过程是什么样的',
          slot: '过程描述',
          color: '#EDBBD2',
        },
        { sentence: '子模型在LLM抽取之前使用吗？', slot: '使用顺序', color: '#EDBBD2' },
        {
          sentence:
            '所以通过这 个prompt，我就可以实现从小模型的输出中，使用LLM进行抽取，同时将输出结果转换成DST的多层次格式了吗',
          slot: '功能实现',
          color: '#EDBBD2',
        },
      ],
      color: '#CC3F7F',
    },
  ],
  [
    {
      domain: '模型过滤',
      slots: [
        {
          sentence:
            '我想从一段长对话当中先进性小模型（主题模型）进行一个大致的过滤，然后将过滤出来的信息再让大模型进行抽取，这样抽取效果是不是更好一点',
          slot: '大致过滤',
          color: '#E4E4E4',
        },
        { sentence: '小模型过滤你推荐我用那些模型', slot: '模型推荐', color: '#E4E4E4' },
        { sentence: '现在我想实现小模型的一个对话过滤', slot: '实现过滤', color: '#E4E4E4' },
      ],
      color: '#B2B2B2',
    },
  ],
  [
    {
      domain: 'D3应用',
      slots: [
        { sentence: '你知道d3吗', slot: '了解D3', color: '#C0C0C0' },
        { sentence: '你用d3帮我生成一个有放大效果的椭圆', slot: '生成图形', color: '#C0C0C0' },
      ],
      color: '#4C4C4C',
    },
    {
      domain: 'Vue3',
      slots: [{ sentence: 'vue3', slot: '版本提及', color: '#B7D2F5' }],
      color: '#337FE5',
    },
  ],
  [
    {
      domain: 'Bertopic使用',
      slots: [
        { sentence: '怎么使用bertopic，给一个完整的使用过程', slot: '使用过程', color: '#F5D6AE' },
        {
          sentence: '我这里得到的result是经过了bertopic抽取过后的结果，就是小模型的结果',
          slot: '结果分析',
          color: '#F5D6AE',
        },
        { sentence: '你觉得最前面的那部分筛选msg的还有作用吗', slot: '消息筛选', color: '#F5D6AE' },
      ],
      color: '#E58C19',
    },
  ],
  [
    {
      domain: '文档编辑',
      slots: [
        { sentence: '把doc给我扩充一下：', slot: '扩充文档', color: '#C9E8BB' },
        { sentence: '这里修改一下：', slot: '文档修改', color: '#C9E8BB' },
      ],
      color: '#66BF3F',
    },
    {
      domain: '代码问 题',
      slots: [{ sentence: '为什么要用两个replace', slot: '使用replace', color: '#EDAEC0' }],
      color: '#CC194C',
    },
  ],
  [
    {
      domain: 'SVG制作',
      slots: [
        { sentence: '我在哪里创建这些：', slot: '创建方法', color: '#B0CFF6' },
        { sentence: ".attr('cx', centerX)", slot: '坐标设置', color: '#B0CFF6' },
        { sentence: '字的位置在哪设置：', slot: '文字定位', color: '#B0CFF6' },
      ],
      color: '#1E77E8',
    },
  ],
  [
    {
      domain: '主题颜色设计',
      slots: [
        {
          sentence:
            '我想大主题和小主题的颜色色系是相同的，大主题颜色更深一点，例如大主题是大红色，小主题是浅红色',
          slot: '颜色 色系',
          color: '#FFC9A9',
        },
        { sentence: '一个大主题的小主题颜色可以是一样的', slot: '颜色一致', color: '#FFC9A9' },
        {
          sentence: '我在prompt里面分布颜色的时候想让他们不同：',
          slot: ' 颜色不同',
          color: '#FFC9A9',
        },
      ],
      color: '#FF660C',
    },
  ],
  [
    {
      domain: '句子顺序',
      slots: [
        {
          sentence: '我想句子保持一个时间顺序，具体来说呢句子的出现顺序不能改变',
          slot: '顺序要求',
          color: '#B4E6B4',
        },
      ],
      color: '#2BBA2B',
    },
    {
      domain: 'slot对应',
      slots: [
        {
          sentence: '这个slot都是通过sentences当中的句子得出来的吧',
          slot: '来源确认',
          color: '#F9B3B3',
        },
        {
          sentence:
            ' 有没有什么办法让slot和sentence一一对应，让我知道选择了那个slot就代表了哪个句子',
          slot: '对应方法',
          color: '#F9B3B3',
        },
      ],
      color: '#EF2628',
    },
  ],
  [
    {
      domain: 'Domain颜色',
      slots: [
        { sentence: '每个domain都分配一个颜色', slot: '颜色分配', color: '#D9C9F0' },
        {
          sentence: '有什么颜色库吗，我想每个domain的颜色都是不同的',
          slot: '颜色库',
          color: '#D9C9F0',
        },
        { sentence: 'domain的颜色怎么调整', slot: '颜色调整', color: '#D9C9F0' },
      ],
      color: '#9366D6',
    },
  ],
  [
    {
      domain: '内容修改',
      slots: [{ sentence: '我想你帮我修改一下这段话：', slot: '修改请求', color: '#D6C3BF' }],
      color: '#8C5649',
    },
    {
      domain: '总结内容',
      slots: [{ sentence: '用一句话总结这三句话：', slot: '总结请求', color: '#F4CFE9' }],
      color: '#E277C1',
    },
  ],
]
const newdata = data.flat()
// 小椭圆点击了哪个句子
const onSlotClick = (sentence: string) => {
  FileStore.selectedMessage = sentence
}
// 大椭圆点击
const onDomainClick = (domainSlots: Slot[]) => {
  if (domainSlots.length > 0) {
    onSlotClick(domainSlots[0].sentence)
  }
}
function drawUI(data: Conversation[]) {
  if (!UIcontainer.value) return

  // 清空上一次生成的 SVG
  d3.select(UIcontainer.value).selectAll('*').remove()

  // 初始椭圆参数
  const width = 1024
  const height = 884
  // 中心点
  const currentX = width / 2
  let beforeY = 70 // 前一个 domain 半径
  let currentY = 70 // 每个 domain 垂直间隔
  const spacing = 100 // 固定间距

  // 创建椭圆
  const svg = d3.select(UIcontainer.value).append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g') // 所有图形都在 g 里，方便缩放
  // 绘制大椭圆，并计算小椭圆位置
  const ellipsesData = data.map((domainData) => {
    const baseRx = 80
    const baseRy = 100
    const scale = 1 + 0.1 * (domainData.slots.length - 1)
    const domainRadiusX = baseRx * scale
    const domainRadiusY = baseRy * scale
    const domainEllipse = g
      .append('ellipse')
      .attr('cx', currentX)
      .attr('cy', currentY)
      .attr('rx', domainRadiusX)
      .attr('ry', domainRadiusY)
      .attr('fill', domainData.color)
      .attr('opacity', 0.5)
      .on('click', () => {
        console.log('点击了 domain:', domainData.domain)
        onDomainClick(domainData.slots)
      })
    const domain = domainData.domain
    const lineHeight = 20 // 让文字均匀分布在椭圆高度内
    const textHeight = domain.length * lineHeight // 总高度
    const startY = currentY - textHeight / 2 // 从中心往上偏移一半

    domain.split('').forEach((char, i) => {
      g.append('text')
        .attr('x', currentX) // 椭圆左边，留 10px 间距
        .attr('y', startY + lineHeight / 2 + i * lineHeight) // 从椭圆顶端开始往下排
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', '#fff')
        .attr('font-size', 16)
        .text(char)
    })

    const slots = domainData.slots.map((slotData, i) => {
      const padding = 10
      let slotWidth: number
      let slotHeight: number
      let y: number
      if (domainData.slots.length === 1) {
        // 🔹只有一个小椭圆时，固定大小
        slotWidth = domainRadiusX * 0.6
        slotHeight = domainRadiusY * 0.6
        y = currentY
      } else {
        const availableHeight = domainRadiusY * 2 - padding * (domainData.slots.length + 1)
        slotWidth = domainRadiusX * 0.6
        slotHeight = availableHeight / domainData.slots.length
        y = currentY - domainRadiusY + padding + slotHeight / 2 + i * (slotHeight + padding)
      }

      const x = currentX

      return {
        ...slotData,
        x,
        y,
        rx: slotWidth / 2,
        ry: slotHeight / 2,
      }
    })

    currentY = currentY + beforeY + domainRadiusY + spacing
    beforeY = domainRadiusY

    return { domainEllipse, slots }
  })

  // 小椭圆组，初始透明度为 0
  const slotsGroup = g.append('g')
  const slotEllipses = slotsGroup
    .selectAll('ellipse')
    .data(ellipsesData.flatMap((d) => d.slots))
    .enter()
    .append('ellipse')
    .on('click', (event, d) => {
      console.log('点击了 slot:', d.slot)
      onSlotClick(d.sentence)
    })
    .attr('cx', (d) => d.x)
    .attr('cy', (d) => d.y)
    .attr('rx', (d) => d.rx) // 固定大小
    .attr('ry', (d) => d.ry) // 固定大小
    .attr('fill', (d) => d.color)
    .attr('opacity', 0) // 初始透明

  // 在小椭圆中心添加文字
  const slotTexts = slotsGroup
    .selectAll('text')
    .data(ellipsesData.flatMap((d) => d.slots))
    .enter()
    .append('text')
    .attr('x', (d) => d.x)
    .attr('y', (d) => d.y)
    .attr('text-anchor', 'middle') // 水平居中
    .attr('dominant-baseline', 'middle') // 垂直居中
    .attr('fill', '#fff') // 字体颜色，可根据小椭圆背景色调整
    .attr('font-size', 15) // 字体大小，可调整
    .text((d) => d.slot) // 显示 slot 名称
    .attr('opacity', 0) // 初始与椭圆透明度一致

  // 缩放事件
  const zoom = d3
    .zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.5, 5])
    .on('zoom', (event) => {
      g.attr('transform', event.transform.toString())
      // 动态调整文字大小
      slotTexts.attr('font-size', 15 / event.transform.k) // 让文字随缩放反向缩放
      if (event.transform.k >= 1.25) {
        // 渐显
        slotEllipses.transition().duration(500).attr('opacity', 0.8)
        slotTexts.transition().duration(500).attr('opacity', 0.8)
      } else {
        // 渐隐
        slotEllipses.transition().duration(500).attr('opacity', 0)
        slotTexts.transition().duration(500).attr('opacity', 0)
      }
    })

  svg.call(zoom)
}
// 监听GPT返回内容的变化
watch(
  () => FileStore.GPTContent,
  (content) => {
    console.log(typeof content)
    try {
      content = content.flat()
      drawUI(content)
    } catch (err) {
      console.error('JSON 解析失败:', err)
    }
  },
  { immediate: true }, // 如果已经有数据，则立即触发
)
onMounted(() => {
  drawUI(newdata)
})
</script>
<style scoped>
/* 可根据需要调整容器大小 */
div {
  width: 850px;
  height: 850px;
  margin-top: 10px;
}
input {
  margin-bottom: 10px;
}
</style>
