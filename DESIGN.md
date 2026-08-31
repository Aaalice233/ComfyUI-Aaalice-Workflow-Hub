---
name: "ComfyUI-Aaalice-Workflow-Hub"
description: "冷静、可靠、信息清晰的 ComfyUI 工作流精密工作台"
colors:
  canvas-black: "#0c0d0f"
  surface-base: "#17181b"
  surface-raised: "#1c1e21"
  surface-soft: "#222428"
  field-recessed: "#101113"
  text-primary: "#eeefec"
  text-secondary: "#c7c8c4"
  text-muted: "#8e9196"
  text-faint: "#60636a"
  accent-text: "#121315"
  navigation-blue: "#6ea8ff"
  navigation-blue-hover: "#8bb9ff"
  validation-teal: "#72b39f"
  validation-teal-hover: "#86c0ae"
  archive-violet: "#b394e0"
  archive-violet-hover: "#c3a8e8"
  danger: "#e2797e"
  success: "#8fbaa1"
  warning: "#c7aa72"
typography:
  display:
    fontFamily: "Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "clamp(22px, 3vw, 32px)"
    fontWeight: 620
    lineHeight: 1.25
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 620
    lineHeight: 1.35
    letterSpacing: "normal"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "0.02em"
  meta:
    fontFamily: "Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
  code:
    fontFamily: "Cascadia Code, Consolas, Liberation Mono, monospace"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.02em"
rounded:
  tag: "7px"
  small: "8px"
  control: "10px"
  card: "13px"
  panel: "16px"
  pill: "999px"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.navigation-blue}"
    textColor: "{colors.accent-text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 15px"
    height: "38px"
  button-secondary:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 15px"
    height: "38px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-muted}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 15px"
    height: "38px"
  input-default:
    backgroundColor: "{colors.field-recessed}"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "42px"
  workflow-card:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: "16px"
---

# Design System: ComfyUI-Aaalice-Workflow-Hub

## Overview

**Creative North Star: "精密工作台"**

这套界面像一张经过校准的桌面工作台：深色画布压低环境噪声，清晰的表面层级组织复杂信息，有限的主题色只负责指示当前工作域、交互状态和任务进度。它不追求装饰性的“科技感”，而通过准确的密度、稳定的控件尺寸和可追踪的状态反馈建立专业感与可信度。

整体气质冷静、专业、可信。界面允许承载较高信息密度，但重要操作、选中、聚焦、加载、失败和重试始终拥有明确视觉反馈；动效只帮助用户理解切换、进入和进度变化，不成为注意力中心。

**Key Characteristics:**
- 黑灰分层的桌面工作台，而非纯黑平面。
- 订阅、发布、管理使用各自的低饱和主题色区分工作域。
- 无边框为主，依靠背景明度、内侧高光和柔和阴影表达结构。
- 紧凑但不拥挤，正文和操作文字保持稳定可读。
- 状态优先：进度、成功、警告、失败和焦点一眼可辨。

## Colors

调色板以近黑中性色建立连续层级，再用三种克制的工作域强调色和稳定的语义状态色提供方向。

### Primary
- **导航蓝** (`navigation-blue` / `navigation-blue-hover`)：订阅、发现、下载和默认工作域的强调色，用于主要操作、选中图标、焦点环和进度。

### Secondary
- **校验青** (`validation-teal` / `validation-teal-hover`)：发布流程的强调色，表达资源确认、校验和完成。

### Tertiary
- **归档紫** (`archive-violet` / `archive-violet-hover`)：发布者管理工作域的强调色，区分编辑、归档和版本维护。

### Neutral
- **画布黑** (`canvas-black`)：页面最底层背景。
- **基础表面** (`surface-base`)：常规面板、活动项和账户控件。
- **抬升表面** (`surface-raised`)：卡片、对话框、版本内容和重要分组。
- **柔和表面** (`surface-soft`)：次级按钮、局部状态层和复合控件。
- **凹陷字段** (`field-recessed`)：输入框、搜索框和分段控件的底层。
- **主文本、次级文本、弱文本、极弱文本**：按 `text-primary`、`text-secondary`、`text-muted`、`text-faint` 递减，不能用透明度随意替代层级。

### Named Rules

**The Work-Domain Color Rule.** 每个运行面只由当前工作域主题色主导；订阅蓝、发布青和管理紫不能在同一局部竞争主要操作。

**The State Is Not Decoration Rule.** `danger`、`success`、`warning` 只表达真实状态，不作为装饰色使用。

## Typography

**Display Font:** Inter（回退至 `ui-sans-serif`、system UI 与 Segoe UI）  
**Body Font:** Inter（同一系统回退栈）  
**Label/Mono Font:** Cascadia Code（回退至 Consolas 与 Liberation Mono）仅用于验证码、commit、版本和日志等机器信息。

**Character:** 单一无衬线系统保持工具界面的速度和一致性；层级主要由字号、字重和文本明度建立。等宽字体只强调需要逐字符核对的技术值，不用于普通正文。

### Hierarchy
- **Display**（620，响应式 22–32px，1.25）：详情页主标题和少量关键完成态标题。
- **Headline**（600，18px，1.3）：空状态与对话框主要标题。
- **Title**（620，16px，1.35）：面板标题和重要分组标题。
- **Body**（400，14px，1.55）：正文、说明和大多数表单内容。
- **Label**（600，13px，0.02em）：状态标题、字段标签和紧凑控件文字。
- **Meta**（500，12px，1.4）：版本、时间、来源和辅助信息。

### Named Rules

**The Twelve-Pixel Floor Rule.** 12px 只用于元数据和辅助标签；正文、表单与操作文字使用 14px，不通过缩小文字制造紧凑感。

**The Technical Value Rule.** 只有需要逐字符读取的值使用等宽字体，产品名称、按钮和说明保持无衬线。

## Layout

桌面端采用固定 66px 顶栏和可滚动工作区。顶栏左侧承载品牌，中间是三段主导航，右侧集中设置、活动与账户操作。主体使用 8、12、16、24px 的核心间距节奏；内容卡片采用 `repeat(auto-fill, minmax(270px, 1fr))` 的自适应网格，卡片间距 14px。

详情采用从右侧进入的工作台：桌面端由 176px 版本栏和可滚动版本内容构成，最大宽度 960px；发布控制台最大宽度 860px，使用单列阶段内容和底部固定操作区，不在有限高度内重复堆叠导航信息。

响应式断点为 980px、720px 和 520px。980px 开始压缩品牌与主导航；720px 将目录卡片改为单列、详情版本栏改为横向滚动、表单与工具栏改为纵向或单列；520px 隐藏品牌和导航图标，为主要操作保留空间。最小支持宽度为 320px。

**The Stable Geometry Rule.** 状态变化不能改变列表宽度、按钮尺寸或组件占位；加载、成功和失败在既有几何内切换。

## Elevation & Depth

系统采用“调性分层为主、柔和环境阴影为辅”的混合方式。大多数边界由相邻背景明度、顶部内侧高光和极弱内描边表达；卡片、浮层和抽屉只在需要脱离背景时增加扩散阴影。`shadow-sm` 服务于面板和卡片，`shadow-lg` 服务于活动抽屉和高层浮层；主题色光晕只用于交互和状态反馈。

### Shadow Vocabulary
- **Ambient Small** (`0 8px 24px rgb(0 0 0 / 20%), inset 0 1px rgb(255 255 255 / 4%)`)：基础面板、账户控件和空状态。
- **Ambient Large** (`0 28px 90px rgb(0 0 0 / 44%), inset 0 1px rgb(255 255 255 / 5%)`)：活动抽屉与最高层级浮层。
- **Recessed Field** (`inset 0 0 0 1px rgb(255 255 255 / 4%), inset 0 2px 8px rgb(0 0 0 / 26%)`)：输入框与选择控件。
- **Theme Focus**（主题色弱外圈与内侧高光）：仅用于焦点、选中、当前阶段和活动进度。

### Named Rules

**The Tonal-First Rule.** 静止表面先靠明度和留白分层，不为每张卡片添加边框；阴影只在层级或状态确实变化时增强。

**The No Hard Outline Rule.** 组件边缘不使用 1px 实线或 `inset 0 0 0 1px` 作为主要轮廓；现有极弱内描边只承担高光和聚焦辅助。

## Shapes

界面以轻柔、连续的圆角建立统一触感：标签约 7px，小型操作 8px，标准控件 10px，内容卡片 13px，大型面板和对话框 16px。胶囊形只用于进度条、滚动条和少量明确状态，不将所有标签都处理成胶囊。

图标按钮保持方形占位和紧凑圆角；状态点使用圆形；预览图与容器共享相近圆角并在父容器内裁切。大型面板可以拥有更宽松的圆角，但不能通过叠加多层圆角容器制造视觉噪声。

**The Nested-Radius Rule.** 内层控件圆角必须小于外层容器，并保留清晰的内边距，避免圆角相切。

## Components

### Buttons
- **Shape:** 标准高度 38px，圆角 10px，水平内边距 15px，图标与文字间距 8px。
- **Primary:** 当前工作域主题色背景与深色文字，用于每个局部唯一的主要推进动作；Hover 切换至主题 hover 色并上移 1px。
- **Secondary:** 柔和表面与主文本，用于辅助执行动作；Hover 使用弱主题背景和主题色文字。
- **Ghost:** 透明背景与弱文本，用于返回、取消、刷新和低优先级操作；危险动作只在危险状态下切换红色语义。
- **Focus / Disabled:** Focus 使用主题色焦点反馈；Disabled 保持几何并统一降至 0.42 透明度。

### Chips
- **Style:** 标签使用 7px 圆角和 12px 元数据文字；分段控件使用 11px 外壳、8px 选中层和凹陷字段背景。
- **State:** 选中层通过主题色透明背景滑动，按钮本身不添加描边；来源 chip 为 42px 高的可操作复合项，内部图标按钮固定 30px。

### Cards / Containers
- **Corner Style:** 工作流卡片使用 13px 圆角并裁切预览。
- **Background:** 抬升表面承载内容，预览区域使用更深背景和低饱和图片。
- **Shadow Strategy:** 静止时弱阴影，Hover/Focus 上移 2px并增加主题色内侧高光和环境阴影。
- **Internal Padding:** 内容区 16px，标题、标签和页脚通过 6–15px 的局部节奏分层。

### Inputs / Fields
- **Style:** 高度 42px、圆角 10px、凹陷字段背景和轻微内阴影；textarea 使用 11px × 12px 内边距。
- **Focus:** 主题色内侧高光加 3px 低透明外圈，搜索框由 `focus-within` 统一驱动图标、快捷键和容器状态。
- **Error / Disabled:** 错误使用危险语义色；禁用状态不改变尺寸，选择箭头和控件共同降级。

### Navigation
- **Style:** 66px 半透明顶栏，中间三段主导航使用移动选中层。Active 项文字保持主文本，图标切换为当前主题色并带轻微光晕。
- **Responsive:** 先隐藏辅助品牌文字，再隐藏品牌和导航图标；主要导航和右侧操作始终保留可点击尺寸。

### Detail Workbench

右侧详情抽屉使用版本栏加单版本工作区，封面只作为摘要，不重复纵向展开历史。资源状态集中为三列可点击状态卡，移动端保持三列但压缩高度；版本栏在窄屏转为横向滚动。

### Activity Progress

活动项使用 11px 圆角的基础表面，阶段进度为 6px 分段条，字节进度为 4px 连续条。当前阶段使用主题色，成功使用成功色，失败使用危险色；日志保留深色代码块和真实诊断内容。

### Publish Console

发布控制台是 16px 圆角的单列工作台。上下文栏、步骤导航、阶段正文和底部操作区各司其职；步骤切换使用 0.2s 的轻微上移淡入，底部操作区保持固定，窄屏只隐藏步骤文字而保留数字和顺序。

## Do's and Don'ts

### Do:
- **Do** 使用画布、基础表面、抬升表面、柔和表面和凹陷字段形成连续黑灰层级。
- **Do** 让当前工作域主题色统一驱动主要操作、焦点、选中和进度。
- **Do** 保持按钮 38px、输入 42px 的稳定控件高度，并为重要状态预留固定空间。
- **Do** 使用明确的成功、警告、危险和弱化文本角色表达真实状态。
- **Do** 为 `prefers-reduced-motion` 保留近乎即时的替代过渡。

### Don't:
- **Don't** 同时混用订阅蓝、发布青和管理紫作为竞争强调色。
- **Don't** 用实线边框或 1px inset 描边包围每个弹窗、卡片、输入框和选中层。
- **Don't** 通过小于 12px 的文字、低透明正文或过密堆叠换取紧凑。
- **Don't** 用阴影和光晕装饰静止的普通内容；它们只表达层级、交互和状态。
- **Don't** 让动画延迟操作、伪造进度或在状态切换时造成布局抖动。
