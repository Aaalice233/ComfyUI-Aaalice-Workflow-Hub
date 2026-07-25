const messages = {
  zh: {
    tooltip: "打开工作流中心（Shift+点击在新窗口打开）",
    title: "工作流中心",
    updatesAvailableOne: "工作流中心有 1 个新版本",
    updatesAvailable: "工作流中心有 {count} 个新版本",
    updateDetailMore: "{items} 等 {total} 个",
    listSeparator: "、",
    untitledWorkflowFile: "未命名工作流.json",
  },
  en: {
    tooltip: "Open Workflow Hub (Shift+click to open in a new window)",
    title: "Workflow Hub",
    updatesAvailableOne: "1 workflow update available",
    updatesAvailable: "{count} workflow updates available",
    updateDetailMore: "{items} and {remaining} more",
    listSeparator: ", ",
    untitledWorkflowFile: "Unsaved Workflow.json",
  },
};

export function resolveHostLocale(value) {
  return value?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function translateHost(locale, key, params = {}) {
  const dictionary = messages[locale] || messages.en;
  const message = dictionary[key] || messages.en[key] || key;
  return message.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? `{${name}}`));
}
